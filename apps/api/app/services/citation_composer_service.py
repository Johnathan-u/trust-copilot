"""Citation composer service (P1-48).

Generates clean citations referencing approved evidence, control states,
and linked artifacts. Goes beyond raw document chunks to compose provable citations.
"""

import json
import logging

from sqlalchemy.orm import Session

from app.models.control_evidence_link import ControlEvidenceLink
from app.models.evidence_item import EvidenceItem
from app.models.framework_control import FrameworkControl
from app.models.workspace_control import WorkspaceControl

logger = logging.getLogger(__name__)


def compose_citations(db: Session, workspace_id: int, control_id: int) -> dict:
    """Build a citation bundle for a workspace control, referencing approved evidence and control state."""
    wc = db.query(WorkspaceControl).filter(
        WorkspaceControl.id == control_id,
        WorkspaceControl.workspace_id == workspace_id,
    ).first()
    if not wc:
        return {"error": "Control not found"}

    fc = db.query(FrameworkControl).filter(FrameworkControl.id == wc.framework_control_id).first() if wc.framework_control_id else None

    links = db.query(ControlEvidenceLink).filter(ControlEvidenceLink.control_id == control_id).all()
    evidence_citations = []
    for link in links:
        ev = db.query(EvidenceItem).filter(EvidenceItem.id == link.evidence_id).first()
        if not ev:
            continue
        citation = {
            "evidence_id": ev.id,
            "title": ev.title,
            "source_type": ev.source_type,
            "approval_status": getattr(ev, "approval_status", "pending"),
            "confidence_score": link.confidence_score,
            "verified": link.verified,
            "last_verified_at": link.last_verified_at.isoformat() if link.last_verified_at else None,
        }
        evidence_citations.append(citation)

    approved_citations = [c for c in evidence_citations if c["approval_status"] == "approved"]
    pending_citations = [c for c in evidence_citations if c["approval_status"] != "approved"]

    control_state = {
        "control_id": wc.id,
        "name": wc.custom_name or (fc.control_key if fc else f"Control-{wc.id}"),
        "description": fc.description if fc else None,
        "status": wc.status,
        "last_reviewed_at": wc.last_reviewed_at.isoformat() if wc.last_reviewed_at else None,
        "verified_at": wc.verified_at.isoformat() if wc.verified_at else None,
    }

    return {
        "control": control_state,
        "approved_evidence": approved_citations,
        "pending_evidence": pending_citations,
        "total_evidence": len(evidence_citations),
        "citation_strength": _calculate_strength(approved_citations, wc),
    }


def compose_answer_citations(db: Session, workspace_id: int, answer_text: str, control_ids: list[int]) -> dict:
    """Compose citations for an answer, pulling from multiple controls."""
    all_citations = []
    controls = []
    for cid in control_ids:
        result = compose_citations(db, workspace_id, cid)
        if "error" not in result:
            controls.append(result["control"])
            all_citations.extend(result["approved_evidence"])

    return {
        "answer_preview": answer_text[:200] if answer_text else "",
        "controls_referenced": len(controls),
        "controls": controls,
        "evidence_citations": all_citations,
        "citation_count": len(all_citations),
    }


def _calculate_strength(approved_evidence: list[dict], wc: WorkspaceControl) -> str:
    if not approved_evidence:
        return "none"
    avg_confidence = sum(c.get("confidence_score") or 0 for c in approved_evidence) / len(approved_evidence)
    verified_count = sum(1 for c in approved_evidence if c.get("verified"))
    if wc.status == "verified" and verified_count > 0 and avg_confidence >= 0.7:
        return "strong"
    elif len(approved_evidence) >= 2 and avg_confidence >= 0.5:
        return "moderate"
    elif len(approved_evidence) >= 1:
        return "weak"
    return "none"
