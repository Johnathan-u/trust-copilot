"""Executive dashboard API (P0-87)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin
from app.core.database import get_db
from app.services import executive_dashboard_service as eds

router = APIRouter(prefix="/executive-dashboard", tags=["executive-dashboard"])


@router.get("")
async def get_dashboard(
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    return eds.get_executive_dashboard(db)
