"""Deal management API (E1-01, E1-04, E1-05, E1-06, E1-07)."""

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator, model_validator

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.core.idempotency import (
    IdempotencyKeyError,
    claim as idempotency_claim,
    get as idempotency_get,
    release as idempotency_release,
    scoped_key,
    set as idempotency_set,
)
from app.models.deal import DEAL_STAGES
from app.services import deal_analytics_service as das
from app.services import deal_deadline_service as dds
from app.services import deal_room_service as drs
from app.services import deal_service as ds
from app.services import revenue_risk_service as rrs
from sqlalchemy.orm import Session

router = APIRouter(prefix="/deals", tags=["deals"])

# One body for a missing id and an id in another workspace, so ids can't be probed.
DEAL_NOT_FOUND = "Deal not found"
QUESTIONNAIRE_NOT_FOUND = "Questionnaire not found"
DOCUMENT_NOT_FOUND = "Document not found"
ROOM_NOT_FOUND = "Room not found"
OWNER_NOT_FOUND = "Owner not found"

_Stage = Literal[
    "prospect",
    "discovery",
    "evaluation",
    "negotiation",
    "closed_won",
    "closed_lost",
]


def _deal_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail=DEAL_NOT_FOUND)


def _strict_id(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("id must be an integer")
    if value < 1:
        raise ValueError("id must be a positive integer")
    return value


class CreateDealBody(BaseModel):
    company_name: str
    buyer_contact_name: str | None = None
    buyer_contact_email: str | None = None
    deal_value_arr: Any = None
    currency: str | None = None
    stage: _Stage = "prospect"
    close_date: str | None = None
    expected_close_date: date | None = None
    actual_close_date: date | None = None
    requested_frameworks: list[str] | None = None
    notes: str | None = None
    owner_user_id: Any = None
    questionnaire_id: Any = None
    document_id: Any = None
    room_id: Any = None

    @field_validator("deal_value_arr")
    @classmethod
    def _amount(cls, value: object) -> object:
        return ds.parse_amount(value)

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: object) -> str | None:
        return ds.parse_currency(value, amount_present=False)

    @field_validator("owner_user_id", "questionnaire_id", "document_id", "room_id")
    @classmethod
    def _ids(cls, value: object) -> int | None:
        return _strict_id(value)

    @model_validator(mode="after")
    def _amount_has_currency(self) -> "CreateDealBody":
        if self.deal_value_arr is not None and not self.currency:
            raise ValueError("currency is required when an amount is set")
        return self


class UpdateDealBody(BaseModel):
    company_name: str | None = None
    buyer_contact_name: str | None = None
    buyer_contact_email: str | None = None
    deal_value_arr: Any = None
    currency: str | None = None
    stage: _Stage | None = None
    notes: str | None = None
    expected_close_date: date | None = None
    actual_close_date: date | None = None
    owner_user_id: Any = None
    room_id: Any = None

    @field_validator("deal_value_arr")
    @classmethod
    def _amount(cls, value: object) -> object:
        return ds.parse_amount(value)

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: object) -> str | None:
        return ds.parse_currency(value, amount_present=False)

    @field_validator("owner_user_id", "room_id")
    @classmethod
    def _ids(cls, value: object) -> int | None:
        return _strict_id(value)


class LinkBody(BaseModel):
    questionnaire_id: Any

    @field_validator("questionnaire_id")
    @classmethod
    def _id(cls, value: object) -> int:
        parsed = _strict_id(value)
        if parsed is None:
            raise ValueError("id must be an integer")
        return parsed


class LinkRefsBody(BaseModel):
    questionnaire_id: Any = None
    document_id: Any = None
    room_id: Any = None

    @field_validator("questionnaire_id", "document_id", "room_id")
    @classmethod
    def _ids(cls, value: object) -> int | None:
        return _strict_id(value)

    @model_validator(mode="after")
    def _one_ref(self) -> "LinkRefsBody":
        if all(value is None for value in (self.questionnaire_id, self.document_id, self.room_id)):
            raise ValueError("at least one linked ref is required")
        return self


def _idempotency_key(
    request: Request, workspace_id: int, action: str, deal_id: int | None
) -> str | None:
    """Optional key scoped to workspace, action, and deal. Absent means no claim."""
    if "idempotency-key" not in {name.lower() for name in request.headers.keys()}:
        return None
    raw = request.headers.get("Idempotency-Key")
    target = deal_id if deal_id is not None else "new"
    try:
        key = scoped_key(workspace_id, f"deals:{action}", target, raw)
    except IdempotencyKeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return key or None


def _claim_or_replay(db: Session, key: str | None) -> tuple[JSONResponse | None, str | None]:
    if not key:
        return None, None
    cached = idempotency_get(db, key)
    if cached:
        return JSONResponse(content=cached[1], status_code=cached[0]), None
    owner = idempotency_claim(db, key)
    if owner is None:
        cached_again = idempotency_get(db, key)
        if cached_again:
            return JSONResponse(content=cached_again[1], status_code=cached_again[0]), None
        raise HTTPException(
            status_code=409, detail="Request in progress; retry with same Idempotency-Key"
        )
    return None, owner


def _mutate(db: Session, key: str | None, owner: str | None, work) -> dict | JSONResponse:
    try:
        payload = work()
        db.commit()
    except Exception:
        db.rollback()
        if key and owner:
            idempotency_release(db, key, owner=owner)
        raise
    if key and owner:
        try:
            idempotency_set(db, key, 200, payload, owner=owner)
        except Exception:
            db.rollback()
            idempotency_set(db, key, 200, payload, owner=owner)
    return payload


def _map_lookup(exc: Exception) -> HTTPException:
    if isinstance(exc, ds.DealNotFound):
        return _deal_not_found()
    if isinstance(exc, ds.QuestionnaireNotFound):
        return HTTPException(status_code=404, detail=QUESTIONNAIRE_NOT_FOUND)
    if isinstance(exc, ds.DocumentNotFound):
        return HTTPException(status_code=404, detail=DOCUMENT_NOT_FOUND)
    if isinstance(exc, ds.RoomNotFound):
        return HTTPException(status_code=404, detail=ROOM_NOT_FOUND)
    if isinstance(exc, ds.OwnerNotFound):
        return HTTPException(status_code=404, detail=OWNER_NOT_FOUND)
    if isinstance(exc, (ds.AmountInvalid, ds.CurrencyInvalid, ds.StageInvalid, ds.DateInvalid)):
        return HTTPException(status_code=422, detail=str(exc))
    raise exc


@router.post("")
async def create(
    body: CreateDealBody,
    request: Request,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    workspace_id = session["workspace_id"]
    key = _idempotency_key(request, workspace_id, "create", None)
    replay, owner = _claim_or_replay(db, key)
    if replay is not None:
        return replay
    data = body.model_dump(exclude_none=True)
    try:
        return _mutate(
            db,
            key,
            owner,
            lambda: ds.create_deal(db, workspace_id, **data),
        )
    except (
        ds.DealNotFound,
        ds.QuestionnaireNotFound,
        ds.DocumentNotFound,
        ds.RoomNotFound,
        ds.OwnerNotFound,
        ds.AmountInvalid,
        ds.CurrencyInvalid,
        ds.StageInvalid,
        ds.DateInvalid,
    ) as exc:
        raise _map_lookup(exc) from None


@router.get("")
async def list_all(
    stage: str | None = Query(None),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    if stage is not None and stage not in DEAL_STAGES:
        raise HTTPException(status_code=422, detail="stage is not a known deal stage")
    return {"deals": ds.list_deals(db, session["workspace_id"], stage)}


@router.get("/analytics")
async def analytics(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return das.get_analytics(db, session["workspace_id"])


@router.get("/revenue-unblocked")
async def revenue_unblocked(
    session: dict = Depends(require_session), db: Session = Depends(get_db)
):
    return das.get_revenue_unblocked(db, session["workspace_id"])


@router.get("/risk-ranking")
async def risk_ranking(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"deals": rrs.rank_deals_by_risk(db, session["workspace_id"])}


@router.get("/upcoming-deadlines")
async def upcoming(
    within_days: int = Query(14, ge=1),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return {"deadlines": dds.get_upcoming_deadlines(db, session["workspace_id"], within_days)}


@router.get("/overdue")
async def overdue(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"overdue": dds.get_overdue_deals(db, session["workspace_id"])}


@router.get("/at-risk-this-week")
async def at_risk(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"deals": dds.get_deals_at_risk_this_week(db, session["workspace_id"])}


@router.get("/{deal_id}")
async def get_one(
    deal_id: int, session: dict = Depends(require_session), db: Session = Depends(get_db)
):
    result = ds.get_deal(db, deal_id, workspace_id=session["workspace_id"])
    if not result:
        raise _deal_not_found()
    return result


@router.get("/{deal_id}/risk")
async def risk_score(
    deal_id: int, session: dict = Depends(require_session), db: Session = Depends(get_db)
):
    result = rrs.score_deal(db, deal_id, workspace_id=session["workspace_id"])
    if "error" in result:
        raise _deal_not_found()
    return result


@router.get("/{deal_id}/room")
async def deal_room(
    deal_id: int, session: dict = Depends(require_session), db: Session = Depends(get_db)
):
    result = drs.generate_deal_room(db, deal_id, workspace_id=session["workspace_id"])
    if "error" in result:
        raise _deal_not_found()
    return result


@router.patch("/{deal_id}")
async def update(
    deal_id: int,
    body: UpdateDealBody,
    request: Request,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    workspace_id = session["workspace_id"]
    key = _idempotency_key(request, workspace_id, "update", deal_id)
    replay, owner = _claim_or_replay(db, key)
    if replay is not None:
        return replay
    updates = {name: value for name, value in body.model_dump().items() if value is not None}
    try:

        def _work() -> dict:
            result = ds.update_deal(db, deal_id, workspace_id=workspace_id, **updates)
            if not result:
                raise ds.DealNotFound(deal_id)
            return result

        return _mutate(db, key, owner, _work)
    except (
        ds.DealNotFound,
        ds.QuestionnaireNotFound,
        ds.DocumentNotFound,
        ds.RoomNotFound,
        ds.OwnerNotFound,
        ds.AmountInvalid,
        ds.CurrencyInvalid,
        ds.StageInvalid,
        ds.DateInvalid,
    ) as exc:
        raise _map_lookup(exc) from None


@router.post("/{deal_id}/link-questionnaire")
async def link_q(
    deal_id: int,
    body: LinkBody,
    request: Request,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    workspace_id = session["workspace_id"]
    key = _idempotency_key(request, workspace_id, "link-questionnaire", deal_id)
    replay, owner = _claim_or_replay(db, key)
    if replay is not None:
        return replay
    try:
        return _mutate(
            db,
            key,
            owner,
            lambda: ds.link_questionnaire(
                db, deal_id, body.questionnaire_id, workspace_id=workspace_id
            ),
        )
    except (ds.DealNotFound, ds.QuestionnaireNotFound) as exc:
        raise _map_lookup(exc) from None


@router.post("/{deal_id}/links")
async def link_refs(
    deal_id: int,
    body: LinkRefsBody,
    request: Request,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    workspace_id = session["workspace_id"]
    key = _idempotency_key(request, workspace_id, "links", deal_id)
    replay, owner = _claim_or_replay(db, key)
    if replay is not None:
        return replay
    try:
        return _mutate(
            db,
            key,
            owner,
            lambda: ds.link_refs(
                db,
                deal_id,
                workspace_id=workspace_id,
                questionnaire_id=body.questionnaire_id,
                document_id=body.document_id,
                room_id=body.room_id,
            ),
        )
    except (
        ds.DealNotFound,
        ds.QuestionnaireNotFound,
        ds.DocumentNotFound,
        ds.RoomNotFound,
    ) as exc:
        raise _map_lookup(exc) from None


@router.delete("/{deal_id}")
async def delete(
    deal_id: int,
    request: Request,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    workspace_id = session["workspace_id"]
    key = _idempotency_key(request, workspace_id, "delete", deal_id)
    replay, owner = _claim_or_replay(db, key)
    if replay is not None:
        return replay
    try:

        def _work() -> dict:
            if not ds.delete_deal(db, deal_id, workspace_id=workspace_id):
                raise ds.DealNotFound(deal_id)
            return {"deleted": True}

        return _mutate(db, key, owner, _work)
    except ds.DealNotFound as exc:
        raise _map_lookup(exc) from None
