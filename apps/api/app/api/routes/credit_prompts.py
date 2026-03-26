"""Credit burn prompts API (P1-62)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth_deps import require_session
from app.core.database import get_db
from app.services import credit_prompt_service as cp

router = APIRouter(prefix="/credit-status", tags=["credit-status"])


@router.get("")
async def get_credit_status(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return cp.get_credit_status(db, session["workspace_id"])
