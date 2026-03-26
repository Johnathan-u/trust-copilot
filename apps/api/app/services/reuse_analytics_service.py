"""Reuse analytics service (P1-78)."""

import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.golden_answer import GoldenAnswer

logger = logging.getLogger(__name__)


def get_reuse_analytics(db: Session, workspace_id: int) -> dict:
    """Aggregate reuse metrics for golden answers."""
    total = db.query(func.count(GoldenAnswer.id)).filter(
        GoldenAnswer.workspace_id == workspace_id,
    ).scalar() or 0

    total_reuses = db.query(func.coalesce(func.sum(GoldenAnswer.reuse_count), 0)).filter(
        GoldenAnswer.workspace_id == workspace_id,
    ).scalar() or 0

    reused_at_least_once = db.query(func.count(GoldenAnswer.id)).filter(
        GoldenAnswer.workspace_id == workspace_id,
        GoldenAnswer.reuse_count > 0,
    ).scalar() or 0

    by_category = db.query(
        GoldenAnswer.category,
        func.count(GoldenAnswer.id),
        func.coalesce(func.sum(GoldenAnswer.reuse_count), 0),
    ).filter(
        GoldenAnswer.workspace_id == workspace_id,
    ).group_by(GoldenAnswer.category).all()

    top_reused = db.query(GoldenAnswer).filter(
        GoldenAnswer.workspace_id == workspace_id,
        GoldenAnswer.reuse_count > 0,
    ).order_by(GoldenAnswer.reuse_count.desc()).limit(10).all()

    return {
        "total_golden_answers": total,
        "total_reuses": int(total_reuses),
        "reused_at_least_once": reused_at_least_once,
        "reuse_rate": round(reused_at_least_once / total * 100, 1) if total else 0,
        "avg_reuses_per_answer": round(total_reuses / total, 2) if total else 0,
        "by_category": [
            {"category": cat or "uncategorized", "count": cnt, "reuses": int(reuses)}
            for cat, cnt, reuses in by_category
        ],
        "top_reused": [
            {"id": ga.id, "question": ga.question_text[:100], "reuse_count": ga.reuse_count}
            for ga in top_reused
        ],
    }
