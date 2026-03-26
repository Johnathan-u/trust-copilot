"""Alerting engine service (P1-37).

Workspace-level alerts for drift, connector failures, stale evidence,
and evidence freshness degradation. Supports email notification generation.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.control_state import ControlStateSnapshot
from app.models.evidence_item import EvidenceItem
from app.models.evidence_metadata import EvidenceMetadata
from app.models.source_registry import SourceRegistry
from app.models.workspace_control import WorkspaceControl

logger = logging.getLogger(__name__)


def check_drift_alerts(db: Session, workspace_id: int) -> list[dict]:
    """Detect controls that have drifted from their verified/implemented state."""
    alerts = []
    snapshots = db.query(ControlStateSnapshot).filter(
        ControlStateSnapshot.workspace_id == workspace_id,
    ).order_by(ControlStateSnapshot.created_at.desc()).all()

    seen_controls: set[int] = set()
    for snap in snapshots:
        if snap.control_id in seen_controls:
            continue
        seen_controls.add(snap.control_id)
        wc = db.query(WorkspaceControl).filter(WorkspaceControl.id == snap.control_id).first()
        if wc and wc.status != snap.status:
            alerts.append({
                "type": "drift",
                "severity": "high",
                "control_id": wc.id,
                "message": f"Control drifted: snapshot was '{snap.status}', current is '{wc.status}'",
                "detected_at": datetime.now(timezone.utc).isoformat(),
            })
    return alerts


def check_connector_failure_alerts(db: Session, workspace_id: int) -> list[dict]:
    """Detect connectors that have failed their last sync."""
    alerts = []
    sources = db.query(SourceRegistry).filter(
        SourceRegistry.workspace_id == workspace_id,
        SourceRegistry.enabled == True,
    ).all()
    for src in sources:
        if src.last_sync_status == "error":
            alerts.append({
                "type": "connector_failure",
                "severity": "high",
                "source_type": src.source_type,
                "message": f"Connector '{src.display_name}' failed: {(src.last_error or 'unknown')[:200]}",
                "detected_at": datetime.now(timezone.utc).isoformat(),
            })
        elif src.last_sync_at:
            last = src.last_sync_at
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - last > timedelta(hours=48):
                alerts.append({
                    "type": "connector_stale",
                    "severity": "medium",
                    "source_type": src.source_type,
                    "message": f"Connector '{src.display_name}' has not synced in over 48 hours",
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                })
    return alerts


def check_stale_evidence_alerts(db: Session, workspace_id: int, staleness_days: int = 90) -> list[dict]:
    """Detect evidence items whose metadata indicates staleness."""
    alerts = []
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=staleness_days)
    items = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == workspace_id).all()
    for item in items:
        meta = db.query(EvidenceMetadata).filter(EvidenceMetadata.evidence_id == item.id).first()
        ref = None
        if meta and meta.freshness_date:
            ref = meta.freshness_date
        elif meta and meta.last_verified_at:
            ref = meta.last_verified_at
        else:
            ref = item.created_at
        if ref and ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        if ref and ref < threshold:
            age = (now - ref).days
            alerts.append({
                "type": "stale_evidence",
                "severity": "medium",
                "evidence_id": item.id,
                "title": item.title,
                "age_days": age,
                "message": f"Evidence '{item.title}' is {age} days old (threshold: {staleness_days})",
                "detected_at": now.isoformat(),
            })
    return alerts


def run_all_checks(db: Session, workspace_id: int) -> dict:
    """Run all alert checks and return aggregated results."""
    drift = check_drift_alerts(db, workspace_id)
    connector = check_connector_failure_alerts(db, workspace_id)
    stale = check_stale_evidence_alerts(db, workspace_id)
    all_alerts = drift + connector + stale
    return {
        "total_alerts": len(all_alerts),
        "by_type": {
            "drift": len(drift),
            "connector_failure": len([a for a in connector if a["type"] == "connector_failure"]),
            "connector_stale": len([a for a in connector if a["type"] == "connector_stale"]),
            "stale_evidence": len(stale),
        },
        "alerts": all_alerts,
    }


def generate_email_digest(db: Session, workspace_id: int) -> dict:
    """Generate an email-ready alert digest."""
    results = run_all_checks(db, workspace_id)
    high = [a for a in results["alerts"] if a.get("severity") == "high"]
    medium = [a for a in results["alerts"] if a.get("severity") == "medium"]
    return {
        "subject": f"Trust Copilot Alert Digest: {len(results['alerts'])} alerts",
        "high_severity": high,
        "medium_severity": medium,
        "total": results["total_alerts"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
