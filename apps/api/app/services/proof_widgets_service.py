"""Proof widgets service (P0-85) — outcome metrics for in-product display."""

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.document import Document
from app.models.export_record import ExportRecord
from app.models.questionnaire import Question, Questionnaire


def get_proof_widgets(db: Session, workspace_id: int) -> dict:
    """Generate proof widget data showing value delivered."""
    total_questions = (
        db.query(func.count(Question.id))
        .join(Questionnaire)
        .filter(Questionnaire.workspace_id == workspace_id)
        .scalar() or 0
    )
    total_answers = (
        db.query(func.count(Answer.id))
        .join(Question)
        .join(Questionnaire)
        .filter(Questionnaire.workspace_id == workspace_id)
        .scalar() or 0
    )
    questionnaires = (
        db.query(func.count(Questionnaire.id))
        .filter(Questionnaire.workspace_id == workspace_id)
        .scalar() or 0
    )
    docs = (
        db.query(func.count(Document.id))
        .filter(Document.workspace_id == workspace_id)
        .scalar() or 0
    )
    exports = (
        db.query(func.count(ExportRecord.id))
        .filter(ExportRecord.workspace_id == workspace_id)
        .scalar() or 0
    )

    hours_saved = round(total_answers * 0.08, 1)

    return {
        "questions_answered": total_answers,
        "questionnaires_processed": questionnaires,
        "documents_indexed": docs,
        "exports_delivered": exports,
        "hours_saved_estimate": hours_saved,
        "coverage_pct": round(total_answers / total_questions * 100, 1) if total_questions else 0,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
