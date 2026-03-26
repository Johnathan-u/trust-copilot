"""Golden answer library service (P1-71, P1-74, P1-75, P1-76)."""

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.golden_answer import GoldenAnswer

logger = logging.getLogger(__name__)


def create_golden_answer(
    db: Session,
    workspace_id: int,
    question_text: str,
    answer_text: str,
    owner_user_id: int | None = None,
    category: str | None = None,
    control_ids: list[int] | None = None,
    evidence_ids: list[int] | None = None,
    confidence: float | None = None,
    review_cycle_days: int = 90,
    source_answer_id: int | None = None,
    customer_override_for: str | None = None,
) -> dict:
    ga = GoldenAnswer(
        workspace_id=workspace_id,
        question_text=question_text,
        answer_text=answer_text,
        owner_user_id=owner_user_id,
        category=category,
        control_ids_json=json.dumps(control_ids or []),
        evidence_ids_json=json.dumps(evidence_ids or []),
        confidence=confidence,
        review_cycle_days=review_cycle_days,
        source_answer_id=source_answer_id,
        customer_override_for=customer_override_for,
        last_reviewed_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(days=review_cycle_days),
    )
    db.add(ga)
    db.flush()
    return _serialize(ga)


def list_golden_answers(
    db: Session,
    workspace_id: int,
    category: str | None = None,
    status: str | None = None,
    customer: str | None = None,
) -> list[dict]:
    q = db.query(GoldenAnswer).filter(GoldenAnswer.workspace_id == workspace_id)
    if category:
        q = q.filter(GoldenAnswer.category == category)
    if status:
        q = q.filter(GoldenAnswer.status == status)
    if customer:
        q = q.filter(GoldenAnswer.customer_override_for == customer)
    return [_serialize(ga) for ga in q.order_by(GoldenAnswer.created_at.desc()).all()]


def get_golden_answer(db: Session, ga_id: int) -> dict | None:
    ga = db.query(GoldenAnswer).filter(GoldenAnswer.id == ga_id).first()
    return _serialize(ga) if ga else None


def update_golden_answer(db: Session, ga_id: int, **updates) -> dict | None:
    ga = db.query(GoldenAnswer).filter(GoldenAnswer.id == ga_id).first()
    if not ga:
        return None
    allowed = {"question_text", "answer_text", "category", "status", "confidence",
               "review_cycle_days", "customer_override_for", "owner_user_id"}
    for k, v in updates.items():
        if k in allowed:
            setattr(ga, k, v)
    db.flush()
    return _serialize(ga)


def review_golden_answer(db: Session, ga_id: int) -> dict | None:
    """Mark a golden answer as reviewed, resetting its expiry."""
    ga = db.query(GoldenAnswer).filter(GoldenAnswer.id == ga_id).first()
    if not ga:
        return None
    ga.last_reviewed_at = datetime.now(timezone.utc)
    cycle = ga.review_cycle_days or 90
    ga.expires_at = datetime.now(timezone.utc) + timedelta(days=cycle)
    ga.status = "approved"
    db.flush()
    return _serialize(ga)


def get_expiring(db: Session, workspace_id: int, within_days: int = 14) -> list[dict]:
    """Get answers expiring soon (P1-75)."""
    threshold = datetime.now(timezone.utc) + timedelta(days=within_days)
    answers = db.query(GoldenAnswer).filter(
        GoldenAnswer.workspace_id == workspace_id,
        GoldenAnswer.expires_at.isnot(None),
        GoldenAnswer.expires_at <= threshold,
        GoldenAnswer.status != "expired",
    ).order_by(GoldenAnswer.expires_at.asc()).all()
    return [_serialize(ga) for ga in answers]


def get_lineage(db: Session, ga_id: int) -> dict:
    """Get answer lineage - source, evidence, controls, reuse (P1-76)."""
    ga = db.query(GoldenAnswer).filter(GoldenAnswer.id == ga_id).first()
    if not ga:
        return {"error": "Golden answer not found"}
    return {
        "id": ga.id,
        "question_text": ga.question_text,
        "answer_text": ga.answer_text,
        "source_answer_id": ga.source_answer_id,
        "control_ids": json.loads(ga.control_ids_json or "[]"),
        "evidence_ids": json.loads(ga.evidence_ids_json or "[]"),
        "owner_user_id": ga.owner_user_id,
        "status": ga.status,
        "reuse_count": ga.reuse_count,
        "customer_override_for": ga.customer_override_for,
        "last_reviewed_at": ga.last_reviewed_at.isoformat() if ga.last_reviewed_at else None,
        "created_at": ga.created_at.isoformat() if ga.created_at else None,
    }


def record_reuse(db: Session, ga_id: int) -> dict | None:
    """Increment reuse counter (P1-73 tracking)."""
    ga = db.query(GoldenAnswer).filter(GoldenAnswer.id == ga_id).first()
    if not ga:
        return None
    ga.reuse_count = (ga.reuse_count or 0) + 1
    db.flush()
    return _serialize(ga)


def find_similar(db: Session, workspace_id: int, question_text: str, limit: int = 5) -> list[dict]:
    """Simple keyword-based similar question matching (P1-73).
    For full semantic matching, integrate with embedding search.
    """
    words = set(question_text.lower().split())
    if not words:
        return []
    candidates = db.query(GoldenAnswer).filter(
        GoldenAnswer.workspace_id == workspace_id,
        GoldenAnswer.status.in_(["approved", "draft"]),
    ).all()

    scored = []
    for ga in candidates:
        ga_words = set(ga.question_text.lower().split())
        overlap = len(words & ga_words)
        if overlap > 0:
            score = overlap / max(len(words), 1)
            scored.append((score, ga))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [_serialize(ga) for _, ga in scored[:limit]]


def _serialize(ga: GoldenAnswer) -> dict:
    return {
        "id": ga.id,
        "workspace_id": ga.workspace_id,
        "question_text": ga.question_text,
        "answer_text": ga.answer_text,
        "category": ga.category,
        "status": ga.status,
        "confidence": ga.confidence,
        "reuse_count": ga.reuse_count,
        "review_cycle_days": ga.review_cycle_days,
        "customer_override_for": ga.customer_override_for,
        "source_answer_id": ga.source_answer_id,
        "last_reviewed_at": ga.last_reviewed_at.isoformat() if ga.last_reviewed_at else None,
        "expires_at": ga.expires_at.isoformat() if ga.expires_at else None,
        "created_at": ga.created_at.isoformat() if ga.created_at else None,
    }
