"""Reuse analytics API (P1-78)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin
from app.core.database import get_db
from app.services import reuse_analytics_service as ra

router = APIRouter(prefix="/reuse-analytics", tags=["reuse-analytics"])


@router.get("")
async def get_analytics(
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    return ra.get_reuse_analytics(db, session["workspace_id"])
