"""Control-check rule engine (P1-31) + pass/fail evaluator (P1-35) + drift detection (P1-36)."""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.control_evidence_link import ControlEvidenceLink
from app.models.control_state import ControlStateSnapshot
from app.models.evidence_item import EvidenceItem
from app.models.workspace_control import WorkspaceControl

logger = logging.getLogger(__name__)

PASS_THRESHOLD = 1
CONFIDENCE_HIGH = 80
CONFIDENCE_MEDIUM = 50


def evaluate_control(db: Session, workspace_id: int, control_id: int) -> dict:
    """Evaluate a single control: count evidence, compute confidence, determine pass/fail."""
    control = db.query(WorkspaceControl).filter(
        WorkspaceControl.id == control_id,
        WorkspaceControl.workspace_id == workspace_id,
    ).first()
    if not control:
        return {"error": "Control not found"}

    evidence_links = db.query(ControlEvidenceLink).filter(
        ControlEvidenceLink.control_id == control_id,
    ).all()
    evidence_count = len(evidence_links)

    fresh_count = 0
    for link in evidence_links:
        evidence = db.query(EvidenceItem).filter(EvidenceItem.id == link.evidence_id).first()
        if evidence and evidence.created_at:
            created = evidence.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - created).days
            if age_days < 180:
                fresh_count += 1

    if evidence_count == 0:
        status = "not_assessed"
        confidence = 0
    elif fresh_count >= PASS_THRESHOLD:
        status = "passing"
        confidence = min(100, 50 + fresh_count * 15)
    elif evidence_count >= PASS_THRESHOLD:
        status = "stale"
        confidence = 30
    else:
        status = "failing"
        confidence = 10

    previous_snapshot = db.query(ControlStateSnapshot).filter(
        ControlStateSnapshot.control_id == control_id,
        ControlStateSnapshot.workspace_id == workspace_id,
    ).order_by(ControlStateSnapshot.created_at.desc()).first()

    previous_status = previous_snapshot.status if previous_snapshot else None
    drift = previous_status is not None and previous_status != status

    snapshot = ControlStateSnapshot(
        workspace_id=workspace_id,
        control_id=control_id,
        status=status,
        previous_status=previous_status,
        evaluated_by="system",
        evidence_count=evidence_count,
        confidence_score=confidence,
        details_json=json.dumps({
            "fresh_evidence": fresh_count,
            "total_evidence": evidence_count,
            "drift_detected": drift,
        }),
    )
    db.add(snapshot)
    db.flush()

    return {
        "control_id": control_id,
        "status": status,
        "previous_status": previous_status,
        "confidence": confidence,
        "evidence_count": evidence_count,
        "fresh_evidence": fresh_count,
        "drift_detected": drift,
        "evaluated_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
    }


def evaluate_all_controls(db: Session, workspace_id: int) -> dict:
    """Evaluate all controls for a workspace."""
    controls = db.query(WorkspaceControl).filter(
        WorkspaceControl.workspace_id == workspace_id,
    ).all()

    results = []
    for ctrl in controls:
        result = evaluate_control(db, workspace_id, ctrl.id)
        results.append(result)

    passing = sum(1 for r in results if r.get("status") == "passing")
    failing = sum(1 for r in results if r.get("status") == "failing")
    stale = sum(1 for r in results if r.get("status") == "stale")
    not_assessed = sum(1 for r in results if r.get("status") == "not_assessed")
    drifts = sum(1 for r in results if r.get("drift_detected"))

    return {
        "total_controls": len(results),
        "passing": passing,
        "failing": failing,
        "stale": stale,
        "not_assessed": not_assessed,
        "drift_count": drifts,
        "results": results,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_control_timeline(db: Session, workspace_id: int, control_id: int, limit: int = 20) -> list[dict]:
    """Get the state timeline for a control."""
    snapshots = db.query(ControlStateSnapshot).filter(
        ControlStateSnapshot.workspace_id == workspace_id,
        ControlStateSnapshot.control_id == control_id,
    ).order_by(ControlStateSnapshot.created_at.desc()).limit(limit).all()

    return [
        {
            "id": s.id,
            "status": s.status,
            "previous_status": s.previous_status,
            "confidence_score": s.confidence_score,
            "evidence_count": s.evidence_count,
            "evaluated_by": s.evaluated_by,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in snapshots
    ]


def get_drift_report(db: Session, workspace_id: int) -> list[dict]:
    """Get all recent drift events."""
    recent = db.query(ControlStateSnapshot).filter(
        ControlStateSnapshot.workspace_id == workspace_id,
        ControlStateSnapshot.previous_status.isnot(None),
    ).order_by(ControlStateSnapshot.created_at.desc()).limit(50).all()

    drifts = []
    for s in recent:
        if s.previous_status != s.status:
            drifts.append({
                "control_id": s.control_id,
                "from_status": s.previous_status,
                "to_status": s.status,
                "detected_at": s.created_at.isoformat() if s.created_at else None,
            })
    return drifts
