"""Shared rule for evidence that can support a verified control link."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Document, EvidenceItem, EvidenceMetadata


def evidence_qualifies(db: Session, ev: EvidenceItem, workspace_id: int, now: datetime) -> bool:
    """Approved, same-workspace, not expired, and not tied to a deleted document.

    A missing expiry or freshness date is not treated as expired. Evidence items
    have no deleted column; a linked document with deleted_at does.
    """
    if ev.workspace_id != workspace_id or ev.approval_status != "approved":
        return False
    if ev.document_id is not None:
        doc = db.query(Document).filter(Document.id == ev.document_id).first()
        if doc is None or doc.workspace_id != workspace_id or doc.deleted_at is not None:
            return False
    metas = db.query(EvidenceMetadata).filter(EvidenceMetadata.evidence_id == ev.id).all()
    for meta in metas:
        if meta.expires_at is not None and meta.expires_at <= now:
            return False
    return True
