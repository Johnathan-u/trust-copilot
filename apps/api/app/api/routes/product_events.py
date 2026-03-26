"""Product events API (P0-86)."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import product_event_service as pe

router = APIRouter(prefix="/events", tags=["events"])


class TrackEventRequest(BaseModel):
    event_type: str
    event_category: str = "general"
    resource_type: str | None = None
    resource_id: int | None = None
    metadata: dict | None = None


@router.post("")
async def track_event(
    req: TrackEventRequest,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    pe.track(
        db, session["workspace_id"], req.event_type,
        user_id=session.get("user_id"),
        event_category=req.event_category,
        resource_type=req.resource_type,
        resource_id=req.resource_id,
        metadata=req.metadata,
    )
    db.commit()
    return {"tracked": True}


@router.get("/counts")
async def event_counts(
    days: int = Query(30, ge=1, le=365),
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    return {"counts": pe.get_event_counts(db, session["workspace_id"], days)}


@router.get("/categories")
async def category_counts(
    days: int = Query(30, ge=1, le=365),
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    return {"categories": pe.get_category_counts(db, session["workspace_id"], days)}


@router.get("/daily")
async def daily_activity(
    days: int = Query(14, ge=1, le=90),
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    return {"activity": pe.get_daily_activity(db, session["workspace_id"], days)}


@router.get("/funnel")
async def funnel(
    days: int = Query(30, ge=1, le=365),
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    return pe.get_funnel(db, session["workspace_id"], days)
