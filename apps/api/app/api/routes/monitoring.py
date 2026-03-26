"""Monitoring scheduler API (P1-33)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin
from app.core.database import get_db
from app.services import monitoring_scheduler_service as ms

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.post("/run")
async def run_checks(
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = ms.run_daily_checks(db, session["workspace_id"])
    db.commit()
    return result
