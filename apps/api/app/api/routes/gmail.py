"""Phase F: Gmail integration API — connect, labels, ingest, evidence, suggestions."""

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
    GmailControlSuggestion,
    GmailIngestLabel,
    GmailIntegration,
)
from app.services.gmail_service import decrypt_token, encrypt_token, get_gmail_provider
from app.services.gmail_ingest_service import fetch_and_ingest_label

router = APIRouter(prefix="/gmail", tags=["gmail"])


# ---- Schemas ----

class ConnectRequest(BaseModel):
    access_token: str
    refresh_token: str | None = None


class AddLabelRequest(BaseModel):
    label_id: str
    label_name: str | None = None


class ReviewSuggestionRequest(BaseModel):
    action: str


# ---- Connection ----

@router.get("/status")
async def gmail_status(
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    ws = session["workspace_id"]
    gi = db.query(GmailIntegration).filter(GmailIntegration.workspace_id == ws).first()
    if not gi:
        return {"connected": False}
    return {
        "connected": True,
        "enabled": bool(gi.enabled),
        "email_address": gi.email_address,
        "updated_at": gi.updated_at.isoformat() if gi.updated_at else None,
    }


@router.post("/connect")
async def gmail_connect(
    req: ConnectRequest,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    ws = session["workspace_id"]
    token = (req.access_token or "").strip()
    if not token or len(token) < 10:
        raise HTTPException(status_code=400, detail="Invalid access token")

    provider = get_gmail_provider()
    profile = provider.get_profile(token)
    email = profile.get("email") or profile.get("emailAddress")

    existing = db.query(GmailIntegration).filter(GmailIntegration.workspace_id == ws).first()
    if existing:
        existing.access_token_encrypted = encrypt_token(token)
        existing.refresh_token_encrypted = encrypt_token(req.refresh_token) if req.refresh_token else None
        existing.email_address = email
        existing.enabled = True
        db.commit()
    else:
        gi = GmailIntegration(
            workspace_id=ws,
            access_token_encrypted=encrypt_token(token),
            refresh_token_encrypted=encrypt_token(req.refresh_token) if req.refresh_token else None,
            email_address=email,
            enabled=True,
        )
        db.add(gi)
        db.commit()

    persist_audit(db, "gmail.connected", user_id=session.get("user_id"), workspace_id=ws,
                  details={"email": email})
    return {"connected": True, "email_address": email}


@router.delete("/disconnect")
async def gmail_disconnect(
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    ws = session["workspace_id"]
    gi = db.query(GmailIntegration).filter(GmailIntegration.workspace_id == ws).first()
    if not gi:
        raise HTTPException(status_code=404, detail="Gmail not connected")
    db.delete(gi)
    db.commit()
    persist_audit(db, "gmail.disconnected", user_id=session.get("user_id"), workspace_id=ws)
    return {"ok": True}


# ---- Labels ----

@router.get("/labels")
async def list_available_labels(
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    ws = session["workspace_id"]
    gi = db.query(GmailIntegration).filter(GmailIntegration.workspace_id == ws).first()
    if not gi:
        raise HTTPException(status_code=404, detail="Gmail not connected")
    token = decrypt_token(gi.access_token_encrypted)
    provider = get_gmail_provider()
    labels = provider.list_labels(token)
    return {"labels": labels}


@router.get("/ingest/labels")
async def list_ingest_labels(
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    ws = session["workspace_id"]
    rows = db.query(GmailIngestLabel).filter(GmailIngestLabel.workspace_id == ws).order_by(GmailIngestLabel.created_at).all()
    return {
        "labels": [
            {"id": r.id, "label_id": r.label_id, "label_name": r.label_name, "enabled": bool(r.enabled), "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows
        ],
    }


@router.post("/ingest/labels")
async def add_ingest_label(
    req: AddLabelRequest,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    ws = session["workspace_id"]
    gi = db.query(GmailIntegration).filter(GmailIntegration.workspace_id == ws).first()
    if not gi:
        raise HTTPException(status_code=400, detail="Gmail must be connected first")
    lid = (req.label_id or "").strip()
    if not lid:
        raise HTTPException(status_code=400, detail="label_id required")
    existing = db.query(GmailIngestLabel).filter(GmailIngestLabel.workspace_id == ws, GmailIngestLabel.label_id == lid).first()
    if existing:
        raise HTTPException(status_code=400, detail="Label already approved")
    lbl = GmailIngestLabel(
        workspace_id=ws, gmail_integration_id=gi.id,
        label_id=lid, label_name=(req.label_name or "").strip() or None, enabled=True,
    )
    db.add(lbl)
    db.commit()
    db.refresh(lbl)
    persist_audit(db, "gmail.label_approved", user_id=session.get("user_id"), workspace_id=ws,
                  details={"label_id": lid, "label_name": req.label_name})
    return {"id": lbl.id, "label_id": lbl.label_id, "label_name": lbl.label_name, "enabled": True}


@router.delete("/ingest/labels/{label_record_id}")
async def remove_ingest_label(
    label_record_id: int,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    ws = session["workspace_id"]
    lbl = db.query(GmailIngestLabel).filter(GmailIngestLabel.id == label_record_id, GmailIngestLabel.workspace_id == ws).first()
    if not lbl:
        raise HTTPException(status_code=404, detail="Label not found")
    lid = lbl.label_id
    db.delete(lbl)
    db.commit()
    persist_audit(db, "gmail.label_revoked", user_id=session.get("user_id"), workspace_id=ws, details={"label_id": lid})
    return {"ok": True}


# ---- Ingest ----

@router.post("/ingest/run/{label_record_id}")
async def run_ingest(
    label_record_id: int,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    ws = session["workspace_id"]
    from app.services.quota_service import check_quota
    allowed, current, quota_limit = check_quota(db, ws, "gmail_ingests")
    if not allowed:
        raise HTTPException(status_code=429, detail=f"Gmail ingest quota exceeded ({current}/{quota_limit} per hour)")
    lbl = db.query(GmailIngestLabel).filter(GmailIngestLabel.id == label_record_id, GmailIngestLabel.workspace_id == ws, GmailIngestLabel.enabled == True).first()
    if not lbl:
        raise HTTPException(status_code=404, detail="Approved label not found")
    result = fetch_and_ingest_label(db, ws, lbl.label_id, admin_user_id=session.get("user_id"), limit=limit)
    from app.services.quota_service import record_usage
    record_usage(db, ws, "gmail_ingests")
    db.commit()
    return result


# ---- Evidence ----

@router.get("/ingest/evidence")
async def list_gmail_evidence(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_review),
):
    ws = session["workspace_id"]
    q = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == ws, EvidenceItem.source_type == "gmail")
    total = q.count()
    rows = q.order_by(EvidenceItem.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "evidence": [
            {"id": e.id, "title": e.title, "source_metadata": json.loads(e.source_metadata) if e.source_metadata else None, "created_at": e.created_at.isoformat() if e.created_at else None}
            for e in rows
        ],
    }


# ---- Suggestions ----

@router.post("/ingest/evidence/{evidence_id}/suggest-controls")
async def suggest_controls(
    evidence_id: int,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    ws = session["workspace_id"]
    ev = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_id, EvidenceItem.workspace_id == ws, EvidenceItem.source_type == "gmail").first()
    if not ev:
        raise HTTPException(status_code=404, detail="Gmail evidence not found")
    from app.services.slack_ingest_service import suggest_controls_for_evidence
    suggestions = suggest_controls_for_evidence(db, ws, evidence_id)
    return {"suggestions": suggestions}


@router.get("/ingest/suggestions")
async def list_suggestions(
    status_filter: str = Query("pending", alias="status"),
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_review),
):
    ws = session["workspace_id"]
    q = db.query(GmailControlSuggestion).filter(GmailControlSuggestion.workspace_id == ws)
    if status_filter:
        q = q.filter(GmailControlSuggestion.status == status_filter)
    total = q.count()
    rows = q.order_by(GmailControlSuggestion.created_at.desc()).limit(100).all()
    return {
        "total": total,
        "suggestions": [
            {"id": s.id, "evidence_id": s.evidence_id, "control_id": s.control_id, "confidence": s.confidence, "status": s.status, "created_at": s.created_at.isoformat() if s.created_at else None}
            for s in rows
        ],
    }


@router.patch("/ingest/suggestions/{suggestion_id}")
async def review_suggestion(
    suggestion_id: int,
    req: ReviewSuggestionRequest,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    ws = session["workspace_id"]
    sug = db.query(GmailControlSuggestion).filter(GmailControlSuggestion.id == suggestion_id, GmailControlSuggestion.workspace_id == ws).first()
    if not sug:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if sug.status != "pending":
        raise HTTPException(status_code=400, detail="Already reviewed")
    action = (req.action or "").strip().lower()
    if action not in ("approve", "dismiss"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'dismiss'")
    sug.status = "approved" if action == "approve" else "dismissed"
    sug.reviewed_by_user_id = session.get("user_id")
    sug.reviewed_at = datetime.utcnow()
    if action == "approve":
        existing_link = db.query(ControlEvidenceLink).filter(ControlEvidenceLink.evidence_id == sug.evidence_id, ControlEvidenceLink.control_id == sug.control_id).first()
        if not existing_link:
            db.add(ControlEvidenceLink(control_id=sug.control_id, evidence_id=sug.evidence_id, confidence_score=sug.confidence, verified=False))
    db.commit()
    persist_audit(db, f"gmail.suggestion_{action}d", user_id=session.get("user_id"), workspace_id=ws,
                  resource_type="gmail_control_suggestion", resource_id=sug.id,
                  details={"evidence_id": sug.evidence_id, "control_id": sug.control_id})
    return {"id": sug.id, "status": sug.status}
