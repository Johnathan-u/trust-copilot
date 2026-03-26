"""SLA tracking API (P1-61)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin
from app.core.database import get_db
from app.services import sla_tracking_service as sla

router = APIRouter(prefix="/sla", tags=["sla"])


@router.get("")
async def get_sla_metrics(
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    return sla.get_sla_metrics(db, session["workspace_id"])
