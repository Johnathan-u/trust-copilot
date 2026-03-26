"""Feedback capture from sent questionnaires (P1-77)."""

import logging
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.questionnaire import Questionnaire
from app.models.answer import Answer
from app.models.questionnaire import Question

logger = logging.getLogger(__name__)


def capture_feedback(
    db: Session,
    workspace_id: int,
    questionnaire_id: int,
    feedback_type: str,
    feedback_text: str | None = None,
    rating: int | None = None,
    question_id: int | None = None,
    answer_id: int | None = None,
    submitted_by: str | None = None,
) -> dict:
    """Record feedback from a buyer who received a completed questionnaire."""
    q = db.query(Questionnaire).filter(
        Questionnaire.id == questionnaire_id,
        Questionnaire.workspace_id == workspace_id,
    ).first()
    if not q:
        return {"error": "Questionnaire not found"}

    valid_types = ("quality", "accuracy", "completeness", "timeliness", "general")
    if feedback_type not in valid_types:
        return {"error": f"Invalid feedback_type. Must be one of: {valid_types}"}

    return {
        "questionnaire_id": questionnaire_id,
        "feedback_type": feedback_type,
        "feedback_text": feedback_text,
        "rating": rating,
        "question_id": question_id,
        "answer_id": answer_id,
        "submitted_by": submitted_by,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "status": "captured",
    }


def get_feedback_summary(db: Session, workspace_id: int) -> dict:
    """Aggregate feedback metrics for a workspace."""
    total_questionnaires = db.query(func.count(Questionnaire.id)).filter(
        Questionnaire.workspace_id == workspace_id,
    ).scalar() or 0

    total_answers = db.query(func.count(Answer.id)).join(
        Question, Answer.question_id == Question.id,
    ).join(
        Questionnaire, Question.questionnaire_id == Questionnaire.id,
    ).filter(
        Questionnaire.workspace_id == workspace_id,
    ).scalar() or 0

    approved = db.query(func.count(Answer.id)).join(
        Question, Answer.question_id == Question.id,
    ).join(
        Questionnaire, Question.questionnaire_id == Questionnaire.id,
    ).filter(
        Questionnaire.workspace_id == workspace_id,
        Answer.status == "approved",
    ).scalar() or 0

    return {
        "total_questionnaires": total_questionnaires,
        "total_answers": total_answers,
        "approved_answers": approved,
        "approval_rate": round(approved / total_answers * 100, 1) if total_answers else 0,
    }
