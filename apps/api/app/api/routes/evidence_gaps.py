"""Evidence gap API routes: list, accept, dismiss, generate."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth_deps import require_session
from app.core.database import get_db
from app.models.evidence_gap import EvidenceGap

logger = logging.getLogger(__name__)

router = APIRouter(tags=["evidence-gaps"])


def _workspace_id_from_session(session: dict) -> int:
    wid = session.get("workspace_id")
    if not wid:
        raise HTTPException(status_code=400, detail="No workspace in session")
    return int(wid)


@router.get("/api/questionnaires/{qnr_id}/evidence-gaps")
def list_evidence_gaps(
    qnr_id: int,
    status: str | None = Query(None, description="Filter by status: open, accepted, dismissed"),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """List evidence gaps for a questionnaire."""
    workspace_id = _workspace_id_from_session(session)
    q = db.query(EvidenceGap).filter(
        EvidenceGap.questionnaire_id == qnr_id,
        EvidenceGap.workspace_id == workspace_id,
    )
    if status:
        q = q.filter(EvidenceGap.status == status)
    gaps = q.order_by(EvidenceGap.created_at.desc()).all()
    return {
        "gaps": [
            {
                "id": g.id,
                "question_id": g.question_id,
                "answer_id": g.answer_id,
                "gap_type": g.gap_type,
                "reason": g.reason,
                "proposed_policy_addition": g.proposed_policy_addition,
                "suggested_evidence_doc_title": g.suggested_evidence_doc_title,
                "confidence": g.confidence,
                "status": g.status,
                "created_at": g.created_at.isoformat() if g.created_at else None,
            }
            for g in gaps
        ],
        "total": len(gaps),
    }


@router.post("/api/evidence-gaps/{gap_id}/accept")
def accept_evidence_gap(
    gap_id: int,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Accept a gap suggestion and create a supplemental evidence document."""
    workspace_id = _workspace_id_from_session(session)
    try:
        from app.services.evidence_gap_service import accept_gap
        result = accept_gap(db, gap_id, workspace_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("accept_evidence_gap failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to accept gap")


@router.post("/api/evidence-gaps/{gap_id}/dismiss")
def dismiss_evidence_gap(
    gap_id: int,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Dismiss a gap suggestion."""
    workspace_id = _workspace_id_from_session(session)
    try:
        from app.services.evidence_gap_service import dismiss_gap
        result = dismiss_gap(db, gap_id, workspace_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("dismiss_evidence_gap failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to dismiss gap")


@router.post("/api/questionnaires/{qnr_id}/generate-gaps")
def generate_gaps(
    qnr_id: int,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Generate evidence gap analysis for all insufficient-evidence answers."""
    workspace_id = _workspace_id_from_session(session)
    try:
        from app.services.evidence_gap_service import generate_gaps_for_questionnaire
        result = generate_gaps_for_questionnaire(db, workspace_id, qnr_id)
        return result
    except Exception as e:
        logger.error("generate_gaps failed for qnr %d: %s", qnr_id, e)
        raise HTTPException(status_code=500, detail="Failed to generate gap analysis")
