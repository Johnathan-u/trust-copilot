"""Control timeline view service (P1-40).

Provides a unified timeline of state changes, drift events,
evidence links, and user actions for each control.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.control_evidence_link import ControlEvidenceLink
from app.models.control_state import ControlStateSnapshot
from app.models.evidence_item import EvidenceItem
from app.models.workspace_control import WorkspaceControl

logger = logging.getLogger(__name__)


def get_control_timeline(
    db: Session,
    workspace_id: int,
    control_id: int,
    limit: int = 50,
) -> dict:
    """Build a comprehensive timeline for a control combining multiple event sources."""
    control = db.query(WorkspaceControl).filter(
        WorkspaceControl.id == control_id,
        WorkspaceControl.workspace_id == workspace_id,
    ).first()
    if not control:
        return {"error": "Control not found"}

    events: list[dict] = []

    snapshots = db.query(ControlStateSnapshot).filter(
        ControlStateSnapshot.workspace_id == workspace_id,
        ControlStateSnapshot.control_id == control_id,
    ).order_by(ControlStateSnapshot.created_at.desc()).limit(limit).all()

    for s in snapshots:
        event = {
            "type": "state_change",
            "timestamp": s.created_at.isoformat() if s.created_at else None,
            "status": s.status,
            "previous_status": s.previous_status,
            "confidence_score": s.confidence_score,
            "evidence_count": s.evidence_count,
            "evaluated_by": s.evaluated_by,
            "drift_detected": s.previous_status is not None and s.previous_status != s.status,
        }
        events.append(event)

    evidence_links = db.query(ControlEvidenceLink).filter(
        ControlEvidenceLink.control_id == control_id,
    ).all()

    for link in evidence_links:
        evidence = db.query(EvidenceItem).filter(EvidenceItem.id == link.evidence_id).first()
        if evidence:
            events.append({
                "type": "evidence_linked",
                "timestamp": evidence.created_at.isoformat() if evidence.created_at else None,
                "evidence_id": evidence.id,
                "evidence_title": getattr(evidence, "title", None) or getattr(evidence, "source_name", None),
            })

    if control.verified_at:
        events.append({
            "type": "verified",
            "timestamp": control.verified_at.isoformat(),
            "verified_by_user_id": control.verified_by_user_id,
        })

    if control.last_reviewed_at:
        events.append({
            "type": "reviewed",
            "timestamp": control.last_reviewed_at.isoformat(),
        })

    events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)

    drift_events = [e for e in events if e.get("drift_detected")]

    return {
        "control_id": control_id,
        "current_status": control.status,
        "total_events": len(events),
        "drift_events": len(drift_events),
        "events": events[:limit],
    }
