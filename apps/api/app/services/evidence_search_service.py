"""Evidence search and retrieval APIs (P1-52).

Search evidence by control, approval status, source type, timestamp range.
Turns evidence into reusable infrastructure.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.control_evidence_link import ControlEvidenceLink
from app.models.evidence_item import EvidenceItem
from app.models.evidence_metadata import EvidenceMetadata

logger = logging.getLogger(__name__)


def search(
    db: Session,
    workspace_id: int,
    control_id: int | None = None,
    approval_status: str | None = None,
    source_type: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    title_query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    q = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == workspace_id)

    if control_id is not None:
        evidence_ids = [
            link.evidence_id
            for link in db.query(ControlEvidenceLink.evidence_id).filter(
                ControlEvidenceLink.control_id == control_id
            ).all()
        ]
        q = q.filter(EvidenceItem.id.in_(evidence_ids)) if evidence_ids else q.filter(EvidenceItem.id == -1)

    if approval_status:
        q = q.filter(EvidenceItem.approval_status == approval_status)

    if source_type:
        q = q.filter(EvidenceItem.source_type == source_type)

    if created_after:
        q = q.filter(EvidenceItem.created_at >= created_after)

    if created_before:
        q = q.filter(EvidenceItem.created_at <= created_before)

    if title_query:
        q = q.filter(EvidenceItem.title.ilike(f"%{title_query}%"))

    total = q.count()
    items = q.order_by(EvidenceItem.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [_serialize(ev) for ev in items],
    }


def get_by_control(db: Session, workspace_id: int, control_id: int) -> list[dict]:
    links = db.query(ControlEvidenceLink).filter(ControlEvidenceLink.control_id == control_id).all()
    results = []
    for link in links:
        ev = db.query(EvidenceItem).filter(
            EvidenceItem.id == link.evidence_id,
            EvidenceItem.workspace_id == workspace_id,
        ).first()
        if ev:
            d = _serialize(ev)
            d["confidence_score"] = link.confidence_score
            d["verified"] = link.verified
            results.append(d)
    return results


def get_stats(db: Session, workspace_id: int) -> dict:
    total = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == workspace_id).count()
    by_source = {}
    by_approval = {}
    items = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == workspace_id).all()
    for ev in items:
        by_source[ev.source_type] = by_source.get(ev.source_type, 0) + 1
        status = getattr(ev, "approval_status", "pending") or "pending"
        by_approval[status] = by_approval.get(status, 0) + 1
    return {"total": total, "by_source_type": by_source, "by_approval_status": by_approval}


def _serialize(ev: EvidenceItem) -> dict:
    return {
        "id": ev.id,
        "workspace_id": ev.workspace_id,
        "title": ev.title,
        "source_type": ev.source_type,
        "approval_status": getattr(ev, "approval_status", "pending"),
        "document_id": ev.document_id,
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
    }
