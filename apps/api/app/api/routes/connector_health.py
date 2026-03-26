"""Connector health API (P1-30)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth_deps import require_session
from app.core.database import get_db
from app.services import connector_health_service as ch

router = APIRouter(prefix="/connector-health", tags=["connector-health"])


@router.get("")
async def get_health(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return ch.get_connector_health(db, session["workspace_id"])
