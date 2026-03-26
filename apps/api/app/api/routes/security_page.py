"""Public security page API (P0-82)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth_deps import require_session
from app.core.database import get_db
from app.services import security_page_service as sp

router = APIRouter(prefix="/security-page", tags=["security-page"])


@router.get("")
async def get_security_page(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return sp.get_public_security_page(db, session["workspace_id"])
