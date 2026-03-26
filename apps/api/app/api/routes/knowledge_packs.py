"""Knowledge packs API (P1-59)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth_deps import require_session
from app.core.database import get_db
from app.services import knowledge_pack_service as kp

router = APIRouter(prefix="/knowledge-packs", tags=["knowledge-packs"])


@router.get("")
async def generate_pack(
    questionnaire_id: int | None = Query(None),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return kp.generate_knowledge_pack(db, session["workspace_id"], questionnaire_id)
