"""Evidence search and retrieval API (P1-52)."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth_deps import require_session
from app.core.database import get_db
from app.services import evidence_search_service as svc

router = APIRouter(prefix="/evidence-search", tags=["evidence-search"])


@router.get("")
async def search(
    control_id: int | None = Query(None),
    approval_status: str | None = Query(None),
    source_type: str | None = Query(None),
    created_after: datetime | None = Query(None),
    created_before: datetime | None = Query(None),
    title_query: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return svc.search(
        db, session["workspace_id"],
        control_id=control_id,
        approval_status=approval_status,
        source_type=source_type,
        created_after=created_after,
        created_before=created_before,
        title_query=title_query,
        limit=limit,
        offset=offset,
    )


@router.get("/by-control/{control_id}")
async def by_control(control_id: int, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"evidence": svc.get_by_control(db, session["workspace_id"], control_id)}


@router.get("/stats")
async def stats(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return svc.get_stats(db, session["workspace_id"])
