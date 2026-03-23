"""Phase E: Slack ingest API — approved channels, ingest trigger, evidence review, control suggestions."""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import persist_audit
from app.core.auth_deps import require_can_admin, require_can_review
from app.core.database import get_db
from app.models import (
    ControlEvidenceLink,
    EvidenceItem,
    SlackControlSuggestion,
    SlackIngestChannel,
    SlackIntegration,
)
from app.services.slack_ingest_service import fetch_and_ingest_channel, suggest_controls_for_evidence

router = APIRouter(prefix="/slack/ingest", tags=["slack-ingest"])


# ---- Schemas ----

class ApproveChannelRequest(BaseModel):
    channel_id: str
    channel_name: str | None = None


class ReviewSuggestionRequest(BaseModel):
    action: str  # "approve" or "dismiss"


# ---- Approved channels (admin only) ----

@router.get("/channels")
async def list_ingest_channels(
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """List approved ingest channels for this workspace."""
    ws = session["workspace_id"]
    rows = db.query(SlackIngestChannel).filter(SlackIngestChannel.workspace_id == ws).order_by(SlackIngestChannel.created_at).all()
    return {
        "channels": [
            {
                "id": r.id,
                "channel_id": r.channel_id,
                "channel_name": r.channel_name,
                "enabled": bool(r.enabled),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.post("/channels")
async def approve_channel(
    req: ApproveChannelRequest,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Approve a Slack channel for evidence ingestion. Requires active Slack connection."""
    ws = session["workspace_id"]
    ch_id = (req.channel_id or "").strip()
    if not ch_id:
        raise HTTPException(status_code=400, detail="channel_id is required")

    si = db.query(SlackIntegration).filter(SlackIntegration.workspace_id == ws).first()
    if not si:
        raise HTTPException(status_code=400, detail="Slack must be connected before approving ingest channels")

    existing = db.query(SlackIngestChannel).filter(
        SlackIngestChannel.workspace_id == ws, SlackIngestChannel.channel_id == ch_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Channel already approved")

    ich = SlackIngestChannel(
        workspace_id=ws,
        slack_integration_id=si.id,
        channel_id=ch_id,
        channel_name=(req.channel_name or "").strip() or None,
        enabled=True,
    )
    db.add(ich)
    db.commit()
    db.refresh(ich)

    persist_audit(db, "slack.ingest_channel_approved", user_id=session.get("user_id"), workspace_id=ws,
                  resource_type="slack_ingest_channel", resource_id=ich.id,
                  details={"channel_id": ch_id, "channel_name": req.channel_name})

    return {"id": ich.id, "channel_id": ich.channel_id, "channel_name": ich.channel_name, "enabled": True}


@router.delete("/channels/{channel_record_id}")
async def revoke_channel(
    channel_record_id: int,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Revoke ingest approval for a channel."""
    ws = session["workspace_id"]
    ich = db.query(SlackIngestChannel).filter(
        SlackIngestChannel.id == channel_record_id, SlackIngestChannel.workspace_id == ws
    ).first()
    if not ich:
        raise HTTPException(status_code=404, detail="Channel not found")
    ch_id = ich.channel_id
    db.delete(ich)
    db.commit()
    persist_audit(db, "slack.ingest_channel_revoked", user_id=session.get("user_id"), workspace_id=ws,
                  details={"channel_id": ch_id})
    return {"ok": True}


# ---- Ingest trigger (admin only) ----

@router.post("/run/{channel_record_id}")
async def run_ingest(
    channel_record_id: int,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Fetch and ingest recent messages from an approved channel."""
    ws = session["workspace_id"]
    from app.services.quota_service import check_quota
    allowed, current, quota_limit = check_quota(db, ws, "slack_ingests")
    if not allowed:
        raise HTTPException(status_code=429, detail=f"Slack ingest quota exceeded ({current}/{quota_limit} per hour)")
    ich = db.query(SlackIngestChannel).filter(
        SlackIngestChannel.id == channel_record_id, SlackIngestChannel.workspace_id == ws, SlackIngestChannel.enabled == True,
    ).first()
    if not ich:
        raise HTTPException(status_code=404, detail="Approved channel not found or disabled")

    result = fetch_and_ingest_channel(
        db, ws, ich.channel_id,
        admin_user_id=session.get("user_id"),
        limit=limit,
    )
    from app.services.quota_service import record_usage
    record_usage(db, ws, "slack_ingests")
    db.commit()
    return result


# ---- Slack evidence list (reviewer+) ----

@router.get("/evidence")
async def list_slack_evidence(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_review),
):
    """List evidence items ingested from Slack for this workspace."""
    ws = session["workspace_id"]
    q = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == ws, EvidenceItem.source_type == "slack")
    total = q.count()
    rows = q.order_by(EvidenceItem.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "evidence": [
            {
                "id": e.id,
                "title": e.title,
                "source_metadata": json.loads(e.source_metadata) if e.source_metadata else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in rows
        ],
    }


# ---- Control suggestions (reviewer+) ----

@router.post("/evidence/{evidence_id}/suggest-controls")
async def generate_suggestions(
    evidence_id: int,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Generate control suggestions for a Slack evidence item. Does not auto-link."""
    ws = session["workspace_id"]
    ev = db.query(EvidenceItem).filter(
        EvidenceItem.id == evidence_id, EvidenceItem.workspace_id == ws, EvidenceItem.source_type == "slack"
    ).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Slack evidence not found")
    suggestions = suggest_controls_for_evidence(db, ws, evidence_id)
    return {"suggestions": suggestions}


@router.get("/suggestions")
async def list_suggestions(
    status_filter: str = Query("pending", alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_review),
):
    """List control suggestions for Slack evidence in this workspace."""
    ws = session["workspace_id"]
    q = db.query(SlackControlSuggestion).filter(SlackControlSuggestion.workspace_id == ws)
    if status_filter:
        q = q.filter(SlackControlSuggestion.status == status_filter)
    total = q.count()
    rows = q.order_by(SlackControlSuggestion.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "suggestions": [
            {
                "id": s.id,
                "evidence_id": s.evidence_id,
                "control_id": s.control_id,
                "confidence": s.confidence,
                "status": s.status,
                "reviewed_at": s.reviewed_at.isoformat() if s.reviewed_at else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in rows
        ],
    }


@router.patch("/suggestions/{suggestion_id}")
async def review_suggestion(
    suggestion_id: int,
    req: ReviewSuggestionRequest,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Approve or dismiss a control suggestion. Approve creates a ControlEvidenceLink."""
    ws = session["workspace_id"]
    sug = db.query(SlackControlSuggestion).filter(
        SlackControlSuggestion.id == suggestion_id, SlackControlSuggestion.workspace_id == ws
    ).first()
    if not sug:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if sug.status != "pending":
        raise HTTPException(status_code=400, detail="Suggestion already reviewed")

    action = (req.action or "").strip().lower()
    if action not in ("approve", "dismiss"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'dismiss'")

    sug.status = "approved" if action == "approve" else "dismissed"
    sug.reviewed_by_user_id = session.get("user_id")
    sug.reviewed_at = datetime.utcnow()

    if action == "approve":
        existing_link = db.query(ControlEvidenceLink).filter(
            ControlEvidenceLink.evidence_id == sug.evidence_id,
            ControlEvidenceLink.control_id == sug.control_id,
        ).first()
        if not existing_link:
            db.add(ControlEvidenceLink(
                control_id=sug.control_id,
                evidence_id=sug.evidence_id,
                confidence_score=sug.confidence,
                verified=False,
            ))

    db.commit()
    persist_audit(db, f"slack.suggestion_{action}d", user_id=session.get("user_id"), workspace_id=ws,
                  resource_type="slack_control_suggestion", resource_id=sug.id,
                  details={"evidence_id": sug.evidence_id, "control_id": sug.control_id})
    return {"id": sug.id, "status": sug.status}
