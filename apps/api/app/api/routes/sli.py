"""Reliability SLIs API (P2-101)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin
from app.core.database import get_db
from app.services import sli_service as sli

router = APIRouter(prefix="/sli", tags=["sli"])


@router.get("")
async def get_slis(
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    return sli.get_slis(db)
