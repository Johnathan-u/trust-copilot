"""Evidence-level approval workflows (P1-47).

Separate from answer approval -- evidence must be approved before broad use
in questionnaires or Trust Center.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.evidence_item import EvidenceItem

logger = logging.getLogger(__name__)


def approve_evidence(db: Session, evidence_id: int, approver_user_id: int) -> dict | None:
    ev = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_id).first()
    if not ev:
        return None
    ev.approval_status = "approved"
    ev.approved_by_user_id = approver_user_id
    ev.approved_at = datetime.now(timezone.utc)
    ev.rejection_reason = None
    db.flush()
    return _serialize(ev)


def reject_evidence(db: Session, evidence_id: int, approver_user_id: int, reason: str | None = None) -> dict | None:
    ev = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_id).first()
    if not ev:
        return None
    ev.approval_status = "rejected"
    ev.approved_by_user_id = approver_user_id
    ev.approved_at = datetime.now(timezone.utc)
    ev.rejection_reason = reason
    db.flush()
    return _serialize(ev)


def reset_to_pending(db: Session, evidence_id: int) -> dict | None:
    ev = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_id).first()
    if not ev:
        return None
    ev.approval_status = "pending"
    ev.approved_by_user_id = None
    ev.approved_at = None
    ev.rejection_reason = None
    db.flush()
    return _serialize(ev)


def get_pending(db: Session, workspace_id: int) -> list[dict]:
    items = db.query(EvidenceItem).filter(
        EvidenceItem.workspace_id == workspace_id,
        EvidenceItem.approval_status == "pending",
    ).order_by(EvidenceItem.created_at.asc()).all()
    return [_serialize(ev) for ev in items]


def get_approved(db: Session, workspace_id: int) -> list[dict]:
    items = db.query(EvidenceItem).filter(
        EvidenceItem.workspace_id == workspace_id,
        EvidenceItem.approval_status == "approved",
    ).order_by(EvidenceItem.approved_at.desc()).all()
    return [_serialize(ev) for ev in items]


def bulk_approve(db: Session, evidence_ids: list[int], approver_user_id: int) -> dict:
    approved = []
    skipped = []
    for eid in evidence_ids:
        result = approve_evidence(db, eid, approver_user_id)
        if result:
            approved.append(eid)
        else:
            skipped.append(eid)
    return {"approved": approved, "skipped": skipped}


def _serialize(ev: EvidenceItem) -> dict:
    return {
        "id": ev.id,
        "workspace_id": ev.workspace_id,
        "title": ev.title,
        "source_type": ev.source_type,
        "approval_status": ev.approval_status,
        "approved_by_user_id": ev.approved_by_user_id,
        "approved_at": ev.approved_at.isoformat() if ev.approved_at else None,
        "rejection_reason": ev.rejection_reason,
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
    }
