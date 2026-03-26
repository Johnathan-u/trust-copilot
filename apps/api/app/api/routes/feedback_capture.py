"""Feedback capture API (P1-77)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_session
from app.core.database import get_db
from app.services import feedback_capture_service as fc

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackBody(BaseModel):
    questionnaire_id: int
    feedback_type: str
    feedback_text: str | None = None
    rating: int | None = None
    question_id: int | None = None
    answer_id: int | None = None
    submitted_by: str | None = None


@router.post("")
async def capture_feedback(
    body: FeedbackBody,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    result = fc.capture_feedback(
        db, session["workspace_id"], body.questionnaire_id, body.feedback_type,
        feedback_text=body.feedback_text, rating=body.rating,
        question_id=body.question_id, answer_id=body.answer_id,
        submitted_by=body.submitted_by,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/summary")
async def feedback_summary(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return fc.get_feedback_summary(db, session["workspace_id"])
