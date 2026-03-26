"""Citation composer API (P1-48)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_session
from app.core.database import get_db
from app.services import citation_composer_service as svc

router = APIRouter(prefix="/citations", tags=["citations"])


class AnswerCitationBody(BaseModel):
    answer_text: str
    control_ids: list[int]


@router.get("/control/{control_id}")
async def compose_for_control(control_id: int, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    result = svc.compose_citations(db, session["workspace_id"], control_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/answer")
async def compose_for_answer(body: AnswerCitationBody, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return svc.compose_answer_citations(db, session["workspace_id"], body.answer_text, body.control_ids)
