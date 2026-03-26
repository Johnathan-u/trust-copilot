"""Evidence diff viewer service (P1-45).

Shows what changed between control state snapshots or evidence versions.
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.control_state import ControlStateSnapshot
from app.models.evidence_item import EvidenceItem
from app.models.control_evidence_link import ControlEvidenceLink

logger = logging.getLogger(__name__)


def diff_control_snapshots(
    db: Session,
    workspace_id: int,
    control_id: int,
    snapshot_a_id: int | None = None,
    snapshot_b_id: int | None = None,
) -> dict:
    """Compare two control state snapshots, defaulting to the two most recent."""
    q = db.query(ControlStateSnapshot).filter(
        ControlStateSnapshot.workspace_id == workspace_id,
        ControlStateSnapshot.control_id == control_id,
    ).order_by(ControlStateSnapshot.created_at.desc())

    if snapshot_a_id and snapshot_b_id:
        a = db.query(ControlStateSnapshot).filter(ControlStateSnapshot.id == snapshot_a_id).first()
        b = db.query(ControlStateSnapshot).filter(ControlStateSnapshot.id == snapshot_b_id).first()
    else:
        recent = q.limit(2).all()
        if len(recent) < 2:
            return {"diff": None, "message": "Need at least 2 snapshots to compare"}
        b, a = recent[0], recent[1]

    if not a or not b:
        return {"diff": None, "message": "Snapshot(s) not found"}

    details_a = json.loads(a.details_json) if a.details_json else {}
    details_b = json.loads(b.details_json) if b.details_json else {}

    return {
        "control_id": control_id,
        "older": {
            "id": a.id,
            "status": a.status,
            "confidence_score": a.confidence_score,
            "evidence_count": a.evidence_count,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "details": details_a,
        },
        "newer": {
            "id": b.id,
            "status": b.status,
            "confidence_score": b.confidence_score,
            "evidence_count": b.evidence_count,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "details": details_b,
        },
        "changes": {
            "status_changed": a.status != b.status,
            "confidence_delta": (b.confidence_score or 0) - (a.confidence_score or 0),
            "evidence_delta": (b.evidence_count or 0) - (a.evidence_count or 0),
        },
    }


def diff_evidence_items(
    db: Session,
    workspace_id: int,
    control_id: int,
) -> dict:
    """Show evidence items linked to a control with freshness classification."""
    links = db.query(ControlEvidenceLink).filter(
        ControlEvidenceLink.control_id == control_id,
    ).all()

    items = []
    now = datetime.now(timezone.utc)
    for link in links:
        ev = db.query(EvidenceItem).filter(
            EvidenceItem.id == link.evidence_id,
            EvidenceItem.workspace_id == workspace_id,
        ).first()
        if not ev:
            continue
        created = ev.created_at
        if created and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (now - created).days if created else None
        freshness = "fresh" if age_days and age_days < 90 else "aging" if age_days and age_days < 180 else "stale"
        items.append({
            "evidence_id": ev.id,
            "title": ev.title,
            "source_type": ev.source_type,
            "age_days": age_days,
            "freshness": freshness,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
        })

    return {
        "control_id": control_id,
        "total_evidence": len(items),
        "fresh": sum(1 for i in items if i["freshness"] == "fresh"),
        "aging": sum(1 for i in items if i["freshness"] == "aging"),
        "stale": sum(1 for i in items if i["freshness"] == "stale"),
        "items": items,
    }
