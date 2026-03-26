"""Evidence cards per control service (P1-41)."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.control_evidence_link import ControlEvidenceLink
from app.models.evidence_item import EvidenceItem
from app.models.workspace_control import WorkspaceControl


def get_evidence_card(db: Session, workspace_id: int, control_id: int) -> dict:
    """Generate an evidence card for a given control."""
    control = db.query(WorkspaceControl).filter(
        WorkspaceControl.id == control_id,
        WorkspaceControl.workspace_id == workspace_id,
    ).first()
    if not control:
        return {"error": "Control not found"}

    links = db.query(ControlEvidenceLink).filter(
        ControlEvidenceLink.control_id == control_id,
    ).all()

    evidence_items = []
    now = datetime.now(timezone.utc)
    for link in links:
        item = db.query(EvidenceItem).filter(EvidenceItem.id == link.evidence_id).first()
        if not item:
            continue
        created = item.created_at
        if created and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (now - created).days if created else None
        freshness = "fresh" if age_days and age_days < 90 else "aging" if age_days and age_days < 180 else "stale"

        evidence_items.append({
            "id": item.id,
            "title": item.title,
            "source_type": item.source_type,
            "freshness": freshness,
            "age_days": age_days,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        })

    return {
        "control_id": control_id,
        "control_name": control.control_id if hasattr(control, 'control_id') else str(control_id),
        "status": control.status,
        "evidence_count": len(evidence_items),
        "evidence": evidence_items,
        "coverage": "full" if len(evidence_items) >= 2 else "partial" if evidence_items else "none",
    }


def get_all_evidence_cards(db: Session, workspace_id: int) -> list[dict]:
    """Get evidence cards for all controls in a workspace."""
    controls = db.query(WorkspaceControl).filter(
        WorkspaceControl.workspace_id == workspace_id,
    ).all()
    return [get_evidence_card(db, workspace_id, c.id) for c in controls]
