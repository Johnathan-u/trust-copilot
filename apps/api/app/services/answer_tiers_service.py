"""Public vs private answer tiers service (P1-69).

Each answer can be: public, nda_gated, customer_specific, or internal.
"""

import logging

from sqlalchemy.orm import Session

from app.models.answer import Answer

logger = logging.getLogger(__name__)

VALID_TIERS = ("public", "nda_gated", "customer_specific", "internal")
DEFAULT_TIER = "internal"


def get_answer_tier(answer: Answer) -> str:
    """Extract the visibility tier from an answer's status or metadata."""
    tier = getattr(answer, "visibility_tier", None)
    if tier and tier in VALID_TIERS:
        return tier
    if answer.status == "approved":
        return "public"
    return DEFAULT_TIER


def set_answer_tier(db: Session, answer_id: int, tier: str) -> dict | None:
    """Set the visibility tier on an answer."""
    if tier not in VALID_TIERS:
        return {"error": f"Invalid tier. Must be one of: {VALID_TIERS}"}
    answer = db.query(Answer).filter(Answer.id == answer_id).first()
    if not answer:
        return None
    answer.visibility_tier = tier
    db.flush()
    return {
        "id": answer.id,
        "tier": tier,
        "status": answer.status,
    }


def classify_answers(db: Session, question_ids: list[int] | None = None) -> dict:
    """Classify all answers by tier."""
    q = db.query(Answer)
    if question_ids:
        q = q.filter(Answer.question_id.in_(question_ids))
    answers = q.all()

    result: dict[str, list[dict]] = {t: [] for t in VALID_TIERS}
    for a in answers:
        tier = get_answer_tier(a)
        result[tier].append({"id": a.id, "status": a.status, "question_id": a.question_id})

    return {
        "total": len(answers),
        "by_tier": {t: len(v) for t, v in result.items()},
        "answers": result,
    }
