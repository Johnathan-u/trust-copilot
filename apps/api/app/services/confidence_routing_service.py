"""Confidence-based routing service (P1-57).

Routes questions to auto-draft (high confidence) or human review queue
(low confidence) with visible reasons.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.questionnaire import Question

logger = logging.getLogger(__name__)

HIGH_CONFIDENCE_THRESHOLD = 70
LOW_CONFIDENCE_THRESHOLD = 40


def route_question(db: Session, question_id: int) -> dict:
    """Evaluate confidence for a question's answer and decide routing."""
    question = db.query(Question).filter(Question.id == question_id).first()
    if not question:
        return {"error": "Question not found"}

    answer = db.query(Answer).filter(
        Answer.question_id == question_id,
    ).order_by(Answer.created_at.desc()).first()

    if not answer:
        return {
            "question_id": question_id,
            "route": "human_review",
            "confidence": None,
            "reasons": ["No answer generated yet"],
        }

    confidence = answer.confidence or 0
    reasons = []

    if answer.gating_reason:
        reasons.append(f"Gating: {answer.gating_reason}")
    if answer.insufficient_reason:
        reasons.append(f"Insufficient: {answer.insufficient_reason}")
    if answer.status == "insufficient_evidence":
        reasons.append("Answer marked as insufficient evidence")

    if confidence >= HIGH_CONFIDENCE_THRESHOLD and not reasons:
        route = "auto_draft"
    elif confidence >= LOW_CONFIDENCE_THRESHOLD:
        route = "review_suggested"
        if not reasons:
            reasons.append("Moderate confidence; human review recommended")
    else:
        route = "human_review"
        if not reasons:
            reasons.append(f"Low confidence ({confidence}%); requires human review")

    return {
        "question_id": question_id,
        "answer_id": answer.id,
        "route": route,
        "confidence": confidence,
        "answer_status": answer.status,
        "reasons": reasons,
    }


def get_review_queue(db: Session, questionnaire_id: int) -> list[dict]:
    """Get all questions in a questionnaire that need human review."""
    questions = db.query(Question).filter(Question.questionnaire_id == questionnaire_id).all()
    queue = []
    for q in questions:
        routing = route_question(db, q.id)
        if routing.get("route") in ("human_review", "review_suggested"):
            queue.append(routing)
    return queue


def route_batch(db: Session, question_ids: list[int]) -> dict:
    """Route a batch of questions, returning counts per route type."""
    results = {"auto_draft": [], "review_suggested": [], "human_review": []}
    for qid in question_ids:
        routing = route_question(db, qid)
        route = routing.get("route", "human_review")
        results[route].append(routing)
    return {
        "total": len(question_ids),
        "auto_draft_count": len(results["auto_draft"]),
        "review_suggested_count": len(results["review_suggested"]),
        "human_review_count": len(results["human_review"]),
        "details": results,
    }


def set_thresholds(high: int = 70, low: int = 40) -> dict:
    """Adjust confidence thresholds (in-memory for now)."""
    global HIGH_CONFIDENCE_THRESHOLD, LOW_CONFIDENCE_THRESHOLD
    HIGH_CONFIDENCE_THRESHOLD = high
    LOW_CONFIDENCE_THRESHOLD = low
    return {"high_threshold": high, "low_threshold": low}


def get_thresholds() -> dict:
    return {"high_threshold": HIGH_CONFIDENCE_THRESHOLD, "low_threshold": LOW_CONFIDENCE_THRESHOLD}
