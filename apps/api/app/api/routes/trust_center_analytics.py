"""Trust Center analytics API (P1-67)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin
from app.core.database import get_db
from app.services import trust_center_analytics_service as tca

router = APIRouter(prefix="/trust-center-analytics", tags=["trust-center-analytics"])


@router.get("")
async def get_analytics(
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    return tca.get_trust_center_analytics(db, session["workspace_id"])
