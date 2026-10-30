"""Deal management service (E1-01)."""

import json
import logging
import re
from datetime import date, datetime, timezone  # noqa: F401
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.deal import DEAL_SCHEMA, DEAL_STAGES, Deal
from app.models.document import Document
from app.models.questionnaire import Questionnaire
from app.models.shareable_space import ShareableSpace
from app.models.user import WorkspaceMember

logger = logging.getLogger(__name__)

_AMOUNT_RE = re.compile(r"^(0|[1-9]\d{0,15})(\.\d{1,2})?$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_JSON_LIST_FIELDS = (
    "requested_frameworks",
    "linked_questionnaire_ids",
    "linked_document_ids",
)
_LINK_FIELDS = ("questionnaire_id", "document_id", "room_id")


class DealNotFound(LookupError):
    """No deal with this id in the caller's workspace."""


class QuestionnaireNotFound(LookupError):
    """No live questionnaire with this id in the deal's workspace."""


class DocumentNotFound(LookupError):
    """No live document with this id in the deal's workspace."""


class RoomNotFound(LookupError):
    """No shareable space with this id in the deal's workspace."""


class OwnerNotFound(LookupError):
    """No workspace member with this user id."""


class AmountInvalid(ValueError):
    """Amount is a float, a boolean, or not a 2-decimal decimal."""


class CurrencyInvalid(ValueError):
    """Currency is not three uppercase letters, or it is missing beside an amount."""


class StageInvalid(ValueError):
    """Stage is outside the typed deal stages."""


class DateInvalid(ValueError):
    """A close date is not a date."""


def parse_amount(value: object) -> Decimal | None:
    """Accept a decimal string or an integer. Reject float and bool."""
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, float):
        raise AmountInvalid("amount must be a decimal string or an integer, never a float")
    if isinstance(value, Decimal):
        quantized = value.quantize(Decimal("0.01"))
        if quantized != value:
            raise AmountInvalid("amount must have at most 2 fractional digits")
        text = format(quantized, "f")
    elif isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip()
    else:
        raise AmountInvalid("amount must be a decimal string or an integer, never a float")
    if not _AMOUNT_RE.fullmatch(text):
        raise AmountInvalid(
            "amount must be a non-negative decimal with at most 2 fractional digits"
        )
    return Decimal(text).quantize(Decimal("0.01"))


def money_text(value: object) -> str | None:
    """Decimal string with two fractional digits, or None. Never a float."""
    if value is None:
        return None
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    return format(amount.quantize(Decimal("0.01")), "f")


def parse_currency(value: object, *, amount_present: bool) -> str | None:
    if value is None:
        if amount_present:
            raise CurrencyInvalid("currency is required when an amount is set")
        return None
    if not isinstance(value, str) or not _CURRENCY_RE.fullmatch(value):
        raise CurrencyInvalid("currency must be a three-letter uppercase ISO code")
    return value


def _parse_day(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError as exc:
            raise DateInvalid("close date must be an ISO date") from exc
    raise DateInvalid("close date must be an ISO date")


def _parse_close(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DateInvalid("close date must be an ISO date") from exc
    raise DateInvalid("close date must be an ISO date")


def _check_stage(stage: object) -> str:
    if not isinstance(stage, str) or stage not in DEAL_STAGES:
        raise StageInvalid("stage is not a known deal stage")
    return stage


def _workspace_deal(db: Session, deal_id: int, workspace_id: int) -> Deal | None:
    """The deal with this id in this workspace, or None (missing and foreign look the same)."""
    return db.query(Deal).filter(Deal.id == deal_id, Deal.workspace_id == workspace_id).first()


def workspace_questionnaire_exists(db: Session, workspace_id: int, questionnaire_id: int) -> bool:
    """True if questionnaire_id is a live (not soft-deleted) questionnaire in workspace_id."""
    return (
        db.query(Questionnaire.id)
        .filter(
            Questionnaire.id == questionnaire_id,
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_(None),
        )
        .first()
        is not None
    )


def workspace_document_exists(db: Session, workspace_id: int, document_id: int) -> bool:
    """True if document_id is a live document in workspace_id."""
    return (
        db.query(Document.id)
        .filter(
            Document.id == document_id,
            Document.workspace_id == workspace_id,
            Document.deleted_at.is_(None),
        )
        .first()
        is not None
    )


def workspace_room_exists(db: Session, workspace_id: int, room_id: int) -> bool:
    """True if room_id is a shareable space in workspace_id."""
    return (
        db.query(ShareableSpace.id)
        .filter(ShareableSpace.id == room_id, ShareableSpace.workspace_id == workspace_id)
        .first()
        is not None
    )


def workspace_owner_exists(db: Session, workspace_id: int, user_id: int) -> bool:
    """True if user_id is a non-suspended member of workspace_id."""
    return (
        db.query(WorkspaceMember.id)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.suspended.is_(False),
        )
        .first()
        is not None
    )


def _require_owner(db: Session, workspace_id: int, user_id: int) -> None:
    if not workspace_owner_exists(db, workspace_id, user_id):
        raise OwnerNotFound(user_id)


def _require_questionnaire(db: Session, workspace_id: int, questionnaire_id: int) -> None:
    if not workspace_questionnaire_exists(db, workspace_id, questionnaire_id):
        raise QuestionnaireNotFound(questionnaire_id)


def _require_document(db: Session, workspace_id: int, document_id: int) -> None:
    if not workspace_document_exists(db, workspace_id, document_id):
        raise DocumentNotFound(document_id)


def _require_room(db: Session, workspace_id: int, room_id: int) -> None:
    if not workspace_room_exists(db, workspace_id, room_id):
        raise RoomNotFound(room_id)


def _json_list(raw: str | None) -> list:
    return json.loads(raw or "[]")


def _append_id(raw: str | None, item_id: int) -> str:
    ids = _json_list(raw)
    if item_id not in ids:
        ids.append(item_id)
    return json.dumps(ids)


def _prepare_scalars(payload: dict, *, require_currency_with_amount: bool) -> dict:
    """Type-check amount, currency, stage, and dates. Does not write."""
    prepared = dict(payload)
    if "deal_value_arr" in prepared:
        prepared["deal_value_arr"] = parse_amount(prepared["deal_value_arr"])
    if "currency" in prepared or (
        require_currency_with_amount and prepared.get("deal_value_arr") is not None
    ):
        prepared["currency"] = parse_currency(
            prepared.get("currency"),
            amount_present=require_currency_with_amount
            and prepared.get("deal_value_arr") is not None,
        )
    if "stage" in prepared and prepared["stage"] is not None:
        prepared["stage"] = _check_stage(prepared["stage"])
    if "expected_close_date" in prepared:
        prepared["expected_close_date"] = _parse_day(prepared["expected_close_date"])
    if "actual_close_date" in prepared:
        prepared["actual_close_date"] = _parse_day(prepared["actual_close_date"])
    if "close_date" in prepared:
        prepared["close_date"] = _parse_close(prepared["close_date"])
    if prepared.get("expected_close_date") is not None and "close_date" not in payload:
        day = prepared["expected_close_date"]
        prepared["close_date"] = datetime(day.year, day.month, day.day)
    if prepared.get("close_date") is not None and prepared.get("expected_close_date") is None:
        prepared["expected_close_date"] = prepared["close_date"].date()
    return prepared


def _validate_refs(db: Session, workspace_id: int, payload: dict) -> None:
    if payload.get("owner_user_id") is not None:
        _require_owner(db, workspace_id, payload["owner_user_id"])
    if payload.get("questionnaire_id") is not None:
        _require_questionnaire(db, workspace_id, payload["questionnaire_id"])
    if payload.get("document_id") is not None:
        _require_document(db, workspace_id, payload["document_id"])
    if payload.get("room_id") is not None:
        _require_room(db, workspace_id, payload["room_id"])


def _apply_refs(deal: Deal, payload: dict) -> None:
    if payload.get("questionnaire_id") is not None:
        deal.linked_questionnaire_ids = _append_id(
            deal.linked_questionnaire_ids, payload["questionnaire_id"]
        )
    if payload.get("document_id") is not None:
        deal.linked_document_ids = _append_id(deal.linked_document_ids, payload["document_id"])
    if payload.get("room_id") is not None:
        deal.room_id = payload["room_id"]


def _assign(deal: Deal, payload: dict) -> None:
    for key in _JSON_LIST_FIELDS:
        if key in payload:
            value = payload[key]
            setattr(deal, key, json.dumps(value) if isinstance(value, list) else value)
    skip = set(_JSON_LIST_FIELDS) | set(_LINK_FIELDS)
    for key, value in payload.items():
        if key in skip:
            continue
        if hasattr(deal, key):
            setattr(deal, key, value)
    _apply_refs(deal, payload)


def create_deal(db: Session, workspace_id: int, company_name: str, **kwargs) -> dict:
    payload = _prepare_scalars(kwargs, require_currency_with_amount=False)
    _validate_refs(db, workspace_id, payload)
    deal = Deal(workspace_id=workspace_id, company_name=company_name)
    _assign(deal, payload)
    db.add(deal)
    db.flush()
    return _serialize(deal)


def get_deal(db: Session, deal_id: int, *, workspace_id: int) -> dict | None:
    deal = _workspace_deal(db, deal_id, workspace_id)
    return _serialize(deal) if deal else None


def list_deals(db: Session, workspace_id: int, stage: str | None = None) -> list[dict]:
    query = db.query(Deal).filter(Deal.workspace_id == workspace_id)
    if stage:
        query = query.filter(Deal.stage == stage)
    return [_serialize(row) for row in query.order_by(Deal.created_at.desc()).all()]


def update_deal(db: Session, deal_id: int, *, workspace_id: int, **updates) -> dict | None:
    deal = _workspace_deal(db, deal_id, workspace_id)
    if not deal:
        return None
    payload = _prepare_scalars(updates, require_currency_with_amount=False)
    amount = payload.get("deal_value_arr")
    if amount is not None and not payload.get("currency") and not deal.currency:
        raise CurrencyInvalid("currency is required when an amount is set")
    if "currency" in payload and payload["currency"] is None and payload.get("deal_value_arr"):
        raise CurrencyInvalid("currency is required when an amount is set")
    _validate_refs(db, workspace_id, payload)
    _assign(deal, payload)
    db.flush()
    return _serialize(deal)


def delete_deal(db: Session, deal_id: int, *, workspace_id: int) -> bool:
    deal = _workspace_deal(db, deal_id, workspace_id)
    if not deal:
        return False
    db.delete(deal)
    db.flush()
    return True


def link_questionnaire(
    db: Session, deal_id: int, questionnaire_id: int, *, workspace_id: int
) -> dict:
    """Link a questionnaire to a deal; both must belong to workspace_id.

    Raises DealNotFound / QuestionnaireNotFound (the route maps both to 404).
    """
    return link_refs(db, deal_id, workspace_id=workspace_id, questionnaire_id=questionnaire_id)


def link_refs(
    db: Session,
    deal_id: int,
    *,
    workspace_id: int,
    questionnaire_id: int | None = None,
    document_id: int | None = None,
    room_id: int | None = None,
) -> dict:
    """Attach refs only after every one of them is in the workspace.

    A missing or foreign ref raises before any id is written.
    """
    deal = _workspace_deal(db, deal_id, workspace_id)
    if not deal:
        raise DealNotFound(deal_id)
    payload = {
        "questionnaire_id": questionnaire_id,
        "document_id": document_id,
        "room_id": room_id,
    }
    _validate_refs(db, workspace_id, payload)
    _apply_refs(deal, payload)
    db.flush()
    return _serialize(deal)


def _serialize(deal: Deal) -> dict:
    return {
        "schema_version": DEAL_SCHEMA,
        "id": deal.id,
        "workspace_id": deal.workspace_id,
        "company_name": deal.company_name,
        "buyer_contact_name": deal.buyer_contact_name,
        "buyer_contact_email": deal.buyer_contact_email,
        "deal_value_arr": money_text(deal.deal_value_arr),
        "currency": deal.currency,
        "stage": deal.stage,
        "close_date": deal.close_date.isoformat() if deal.close_date else None,
        "expected_close_date": (
            deal.expected_close_date.isoformat() if deal.expected_close_date else None
        ),
        "actual_close_date": deal.actual_close_date.isoformat() if deal.actual_close_date else None,
        "requested_frameworks": _json_list(deal.requested_frameworks),
        "linked_questionnaire_ids": _json_list(deal.linked_questionnaire_ids),
        "linked_document_ids": _json_list(deal.linked_document_ids),
        "room_id": deal.room_id,
        "crm_source": deal.crm_source,
        "crm_external_id": deal.crm_external_id,
        "owner_user_id": deal.owner_user_id,
        "notes": deal.notes,
        "created_at": deal.created_at.isoformat() if deal.created_at else None,
    }
