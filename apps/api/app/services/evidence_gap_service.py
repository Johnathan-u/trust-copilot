"""Evidence gap service — CRUD for EvidenceGap records.

Used by the compliance-coverage dashboard to populate "Recommended Next Evidence"
and allow users to accept/dismiss individual gap suggestions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.evidence_gap import EvidenceGap, GAP_STATUSES


def list_evidence_gaps(
    db: Session,
    workspace_id: int,
    *,
    status: str | None = None,
    questionnaire_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Return evidence gap rows for a workspace, optionally filtered."""
    q = db.query(EvidenceGap).filter(EvidenceGap.workspace_id == workspace_id)
    if status:
        q = q.filter(EvidenceGap.status == status)
    if questionnaire_id:
        q = q.filter(EvidenceGap.questionnaire_id == questionnaire_id)
    q = q.order_by(EvidenceGap.created_at.desc()).offset(offset).limit(limit)
    return [_gap_to_dict(g) for g in q.all()]


def get_evidence_gap(db: Session, gap_id: int, workspace_id: int) -> dict | None:
    """Fetch a single evidence gap by ID (scoped to workspace)."""
    gap = (
        db.query(EvidenceGap)
        .filter(EvidenceGap.id == gap_id, EvidenceGap.workspace_id == workspace_id)
        .first()
    )
    return _gap_to_dict(gap) if gap else None


def update_evidence_gap_status(
    db: Session,
    gap_id: int,
    workspace_id: int,
    new_status: Literal["open", "accepted", "dismissed"],
) -> dict | None:
    """Update the status of a single evidence gap. Returns updated dict or None if not found."""
    if new_status not in GAP_STATUSES:
        raise ValueError(f"Invalid status: {new_status}. Must be one of {GAP_STATUSES}")
    gap = (
        db.query(EvidenceGap)
        .filter(EvidenceGap.id == gap_id, EvidenceGap.workspace_id == workspace_id)
        .first()
    )
    if not gap:
        return None
    gap.status = new_status
    gap.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(gap)
    return _gap_to_dict(gap)


def bulk_update_by_title(
    db: Session,
    workspace_id: int,
    suggested_title: str,
    new_status: Literal["open", "accepted", "dismissed"],
) -> int:
    """Update all open gaps matching a suggested_evidence_doc_title. Returns count updated."""
    if new_status not in GAP_STATUSES:
        raise ValueError(f"Invalid status: {new_status}")
    count = (
        db.query(EvidenceGap)
        .filter(
            EvidenceGap.workspace_id == workspace_id,
            EvidenceGap.suggested_evidence_doc_title == suggested_title,
            EvidenceGap.status == "open",
        )
        .update(
            {"status": new_status, "updated_at": datetime.now(timezone.utc)},
            synchronize_session="fetch",
        )
    )
    db.commit()
    return count


def gap_summary(db: Session, workspace_id: int) -> dict:
    """Aggregate counts by status."""
    rows = (
        db.query(EvidenceGap.status, func.count(EvidenceGap.id))
        .filter(EvidenceGap.workspace_id == workspace_id)
        .group_by(EvidenceGap.status)
        .all()
    )
    counts = {s: 0 for s in GAP_STATUSES}
    for status, cnt in rows:
        counts[status] = cnt
    counts["total"] = sum(counts.values())
    return counts


def _gap_to_dict(gap: EvidenceGap) -> dict:
    return {
        "id": gap.id,
        "workspace_id": gap.workspace_id,
        "questionnaire_id": gap.questionnaire_id,
        "question_id": gap.question_id,
        "answer_id": gap.answer_id,
        "gap_type": gap.gap_type,
        "reason": gap.reason,
        "proposed_policy_addition": gap.proposed_policy_addition,
        "suggested_evidence_doc_title": gap.suggested_evidence_doc_title,
        "confidence": gap.confidence,
        "status": gap.status,
        "created_at": gap.created_at.isoformat() if gap.created_at else None,
        "updated_at": gap.updated_at.isoformat() if gap.updated_at else None,
    }
