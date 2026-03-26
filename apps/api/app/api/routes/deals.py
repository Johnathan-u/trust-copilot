"""Deal management API (E1-01, E1-04, E1-05, E1-06, E1-07)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import deal_service as ds
from app.services import revenue_risk_service as rrs
from app.services import deal_room_service as drs
from app.services import deal_deadline_service as dds
from app.services import deal_analytics_service as das

router = APIRouter(prefix="/deals", tags=["deals"])


class CreateDealBody(BaseModel):
    company_name: str
    buyer_contact_name: str | None = None
    buyer_contact_email: str | None = None
    deal_value_arr: float | None = None
    stage: str = "prospect"
    close_date: str | None = None
    requested_frameworks: list[str] | None = None
    notes: str | None = None


class UpdateDealBody(BaseModel):
    company_name: str | None = None
    buyer_contact_name: str | None = None
    buyer_contact_email: str | None = None
    deal_value_arr: float | None = None
    stage: str | None = None
    notes: str | None = None


class LinkBody(BaseModel):
    questionnaire_id: int


@router.post("")
async def create(body: CreateDealBody, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_none=True)
    result = ds.create_deal(db, session["workspace_id"], **data)
    db.commit()
    return result


@router.get("")
async def list_all(stage: str | None = Query(None), session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"deals": ds.list_deals(db, session["workspace_id"], stage)}


@router.get("/analytics")
async def analytics(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return das.get_analytics(db, session["workspace_id"])


@router.get("/revenue-unblocked")
async def revenue_unblocked(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return das.get_revenue_unblocked(db, session["workspace_id"])


@router.get("/risk-ranking")
async def risk_ranking(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"deals": rrs.rank_deals_by_risk(db, session["workspace_id"])}


@router.get("/upcoming-deadlines")
async def upcoming(within_days: int = Query(14, ge=1), session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"deadlines": dds.get_upcoming_deadlines(db, session["workspace_id"], within_days)}


@router.get("/overdue")
async def overdue(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"overdue": dds.get_overdue_deals(db, session["workspace_id"])}


@router.get("/at-risk-this-week")
async def at_risk(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"deals": dds.get_deals_at_risk_this_week(db, session["workspace_id"])}


@router.get("/{deal_id}")
async def get_one(deal_id: int, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    result = ds.get_deal(db, deal_id)
    if not result:
        raise HTTPException(status_code=404)
    return result


@router.get("/{deal_id}/risk")
async def risk_score(deal_id: int, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    result = rrs.score_deal(db, deal_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/{deal_id}/room")
async def deal_room(deal_id: int, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    result = drs.generate_deal_room(db, deal_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.patch("/{deal_id}")
async def update(deal_id: int, body: UpdateDealBody, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    result = ds.update_deal(db, deal_id, **updates)
    if not result:
        raise HTTPException(status_code=404)
    db.commit()
    return result


@router.post("/{deal_id}/link-questionnaire")
async def link_q(deal_id: int, body: LinkBody, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = ds.link_questionnaire(db, deal_id, body.questionnaire_id)
    if not result:
        raise HTTPException(status_code=404)
    db.commit()
    return result


@router.delete("/{deal_id}")
async def delete(deal_id: int, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    if not ds.delete_deal(db, deal_id):
        raise HTTPException(status_code=404)
    db.commit()
    return {"deleted": True}
