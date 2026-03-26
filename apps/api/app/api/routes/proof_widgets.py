"""Proof widgets API (P0-85)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth_deps import require_session
from app.core.database import get_db
from app.services import proof_widgets_service as pw

router = APIRouter(prefix="/proof-widgets", tags=["proof-widgets"])


@router.get("")
async def get_widgets(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return pw.get_proof_widgets(db, session["workspace_id"])
