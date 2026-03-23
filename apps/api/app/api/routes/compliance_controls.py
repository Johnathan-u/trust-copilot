"""Compliance foundation: workspace controls (new model)."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_can_review
from app.core.database import get_db
from app.core.metrics import (
    compliance_control_created_total,
    compliance_control_status_changed_total,
    compliance_evidence_linked_total,
)
from app.models import (
    Framework,
    FrameworkControl,
    WorkspaceControl,
    ControlEvidenceLink,
    EvidenceItem,
    EvidenceMetadata,
    Workspace,
    WORKSPACE_CONTROL_STATUSES,
)
from app.services.evidence_suggestion import suggest_evidence as suggest_evidence_service
from app.services.tag_service import list_tags_for_documents
from app.core.compliance_rate_limit import check_compliance_write_allowed
from app.services.compliance_webhook_emitter import (
    emit_compliance_event,
    EVENT_EVIDENCE_VERIFIED,
    EVENT_CONTROL_VERIFIED,
)
from app.services.in_app_notification_service import notify_admins

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/compliance/controls", tags=["compliance-controls"])


class ControlCreateBody(BaseModel):
    framework_control_id: int | None = None
    custom_name: str | None = None
    status: str = "not_implemented"
    owner_user_id: int | None = None
    owner_team: str | None = None


class ControlPatchBody(BaseModel):
    custom_name: str | None = None
    status: str | None = None
    owner_user_id: int | None = None
    owner_team: str | None = None


class LinkEvidenceBody(BaseModel):
    evidence_id: int
    confidence_score: float | None = None
    verified: bool = False


class AcceptSuggestedEvidenceBody(BaseModel):
    document_id: int | None = None
    chunk_id: int
    snippet: str | None = None
    confidence: float = 0.9


class SetEvidenceVerifiedBody(BaseModel):
    verified: bool


from app.api.constants import LOW_CONFIDENCE_THRESHOLD


def _workspace_control_dict(
    wc: WorkspaceControl,
    db: Session,
    evidence_count: int | None = None,
    max_confidence: float | None = None,
    has_verified: bool | None = None,
) -> dict:
    framework_name = None
    control_key = None
    category = None
    title = (wc.custom_name or "").strip() or None
    if wc.framework_control_id:
        fc = db.query(FrameworkControl).filter(FrameworkControl.id == wc.framework_control_id).first()
        if fc:
            control_key = fc.control_key
            title = title or fc.title
            category = fc.category
            fw = db.query(Framework).filter(Framework.id == fc.framework_id).first()
            if fw:
                framework_name = fw.name
    if evidence_count is None:
        evidence_count = _count_evidence(db, wc.id)
    return {
        "id": wc.id,
        "workspace_id": wc.workspace_id,
        "framework_control_id": wc.framework_control_id,
        "control_key": control_key,
        "framework": framework_name,
        "category": category,
        "name": title,
        "custom_name": wc.custom_name,
        "status": wc.status,
        "owner_user_id": wc.owner_user_id,
        "owner_team": wc.owner_team,
        "last_reviewed_at": wc.last_reviewed_at.isoformat() if wc.last_reviewed_at else None,
        "verified_at": wc.verified_at.isoformat() if wc.verified_at else None,
        "verified_by_user_id": wc.verified_by_user_id,
        "created_at": wc.created_at.isoformat() if wc.created_at else None,
        "updated_at": wc.updated_at.isoformat() if wc.updated_at else None,
        "evidence_count": evidence_count,
        "max_confidence": round(max_confidence, 4) if max_confidence is not None else None,
        "has_verified": has_verified if has_verified is not None else False,
    }


def _count_evidence(db: Session, control_id: int) -> int:
    return db.query(ControlEvidenceLink).filter(ControlEvidenceLink.control_id == control_id).count()


@router.get("/stats", response_model=dict)
def control_stats(
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Dashboard counts: total, with_evidence, no_evidence, low_confidence, verified. Enforces workspace isolation."""
    ws = session.get("workspace_id")
    if ws is None:
        return {"total": 0, "with_evidence": 0, "no_evidence": 0, "low_confidence": 0, "verified": 0, "control_verified": 0, "stale_evidence": 0}
    from sqlalchemy import func
    wc_ids_subq = db.query(WorkspaceControl.id).filter(WorkspaceControl.workspace_id == ws)
    total = db.query(WorkspaceControl).filter(WorkspaceControl.workspace_id == ws).count()
    with_ev = db.query(ControlEvidenceLink.control_id).filter(
        ControlEvidenceLink.control_id.in_(wc_ids_subq)
    ).distinct().count()
    no_ev = total - with_ev
    low_conf = 0
    verified_count = db.query(ControlEvidenceLink.control_id).filter(
        ControlEvidenceLink.control_id.in_(wc_ids_subq),
        ControlEvidenceLink.verified.is_(True),
    ).distinct().count()
    for row in (
        db.query(ControlEvidenceLink.control_id, func.max(ControlEvidenceLink.confidence_score))
        .filter(ControlEvidenceLink.control_id.in_(wc_ids_subq))
        .group_by(ControlEvidenceLink.control_id)
    ).all():
        mx = row[1]
        if mx is not None and mx < LOW_CONFIDENCE_THRESHOLD:
            low_conf += 1
    control_verified_count = db.query(WorkspaceControl.id).filter(
        WorkspaceControl.workspace_id == ws,
        WorkspaceControl.status == "verified",
    ).count()
    stale_verified_days, stale_unverified_days = _staleness_days(db, ws)
    wc_ids_list = [r[0] for r in wc_ids_subq.all()]
    stale_count = 0
    if wc_ids_list:
        links = db.query(ControlEvidenceLink).filter(ControlEvidenceLink.control_id.in_(wc_ids_list)).all()
        evidence_ids = list({l.evidence_id for l in links})
        expires_by_evidence = {}
        for meta in db.query(EvidenceMetadata).filter(EvidenceMetadata.evidence_id.in_(evidence_ids)).all():
            if meta.expires_at is not None:
                expires_by_evidence[meta.evidence_id] = meta.expires_at
        now = datetime.utcnow()
        for link in links:
            expired = False
            exp = expires_by_evidence.get(link.evidence_id)
            if exp is not None:
                try:
                    expired = exp < now
                except (TypeError, ValueError):
                    pass
            if expired:
                stale_count += 1
            elif link.verified and link.last_verified_at:
                if (now - link.last_verified_at).days > stale_verified_days:
                    stale_count += 1
            elif not link.verified and link.created_at:
                if (now - link.created_at).days > stale_unverified_days:
                    stale_count += 1
    return {
        "total": total,
        "with_evidence": with_ev,
        "no_evidence": no_ev,
        "low_confidence": low_conf,
        "verified": verified_count,
        "control_verified": control_verified_count,
        "stale_evidence": stale_count,
    }


@router.get("", response_model=list)
def list_controls(
    framework: str | None = Query(None, description="Filter by framework name"),
    status: str | None = Query(None, description="Filter by status"),
    category: str | None = Query(None, description="Filter by control category"),
    gap_state: str | None = Query(None, description="Filter by gap: no_evidence, low_confidence, verified, any"),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """List workspace controls with optional filters. Enforces workspace isolation."""
    ws = session.get("workspace_id")
    if ws is None:
        return []
    q = (
        db.query(WorkspaceControl)
        .filter(WorkspaceControl.workspace_id == ws)
        .order_by(WorkspaceControl.id)
    )
    if status is not None:
        if status not in WORKSPACE_CONTROL_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {WORKSPACE_CONTROL_STATUSES}")
        q = q.filter(WorkspaceControl.status == status)
    if framework is not None or category is not None:
        q = (
            q.outerjoin(FrameworkControl, WorkspaceControl.framework_control_id == FrameworkControl.id)
            .outerjoin(Framework, FrameworkControl.framework_id == Framework.id)
        )
        if framework is not None:
            q = q.filter(Framework.name == framework)
        if category is not None:
            q = q.filter(FrameworkControl.category == category)
    rows = q.all()
    control_ids = [r.id for r in rows]
    from sqlalchemy import func
    count_map = {}
    max_conf_map = {}
    has_verified_map = {}
    if control_ids:
        for cid, cnt in (
            db.query(ControlEvidenceLink.control_id, func.count(ControlEvidenceLink.id))
            .filter(ControlEvidenceLink.control_id.in_(control_ids))
            .group_by(ControlEvidenceLink.control_id)
        ).all():
            count_map[cid] = cnt
        for row in (
            db.query(ControlEvidenceLink.control_id, func.max(ControlEvidenceLink.confidence_score))
            .filter(ControlEvidenceLink.control_id.in_(control_ids))
            .group_by(ControlEvidenceLink.control_id)
        ).all():
            max_conf_map[row[0]] = row[1]
        verified_ids = [
            r[0] for r in
            db.query(ControlEvidenceLink.control_id).filter(
                ControlEvidenceLink.control_id.in_(control_ids),
                ControlEvidenceLink.verified.is_(True),
            ).distinct().all()
        ]
        has_verified_map = {cid: True for cid in verified_ids}
    out = []
    for r in rows:
        ev_count = count_map.get(r.id, 0)
        max_conf = max_conf_map.get(r.id)
        has_ver = has_verified_map.get(r.id, False)
        if gap_state and gap_state != "any":
            if gap_state == "no_evidence" and ev_count != 0:
                continue
            if gap_state == "low_confidence" and (ev_count == 0 or (max_conf is not None and max_conf >= LOW_CONFIDENCE_THRESHOLD)):
                continue
            if gap_state == "verified" and not has_ver:
                continue
        out.append(_workspace_control_dict(r, db, ev_count, max_conf, has_ver))
    return out


def _ensure_workspace_control(db: Session, control_id: int, workspace_id: int) -> WorkspaceControl | None:
    wc = db.query(WorkspaceControl).filter(WorkspaceControl.id == control_id, WorkspaceControl.workspace_id == workspace_id).first()
    return wc


@router.post("", response_model=dict)
def create_control(
    body: ControlCreateBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Create a workspace control. Requires admin."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    if body.status not in WORKSPACE_CONTROL_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {WORKSPACE_CONTROL_STATUSES}")
    wc = WorkspaceControl(
        workspace_id=ws,
        framework_control_id=body.framework_control_id,
        custom_name=body.custom_name.strip() if body.custom_name else None,
        status=body.status,
        owner_user_id=body.owner_user_id,
        owner_team=body.owner_team.strip() if body.owner_team else None,
    )
    db.add(wc)
    db.commit()
    db.refresh(wc)
    compliance_control_created_total.inc()
    logger.info("control_created", extra={"control_id": wc.id, "workspace_id": ws})
    return _workspace_control_dict(wc, db, 0)


@router.get("/{control_id}", response_model=dict)
def get_control(
    control_id: int,
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Get a workspace control by id. Enforces workspace isolation."""
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(status_code=403, detail="No workspace")
    wc = _ensure_workspace_control(db, control_id, ws)
    if not wc:
        raise HTTPException(status_code=404, detail="Control not found")
    from sqlalchemy import func
    max_conf = None
    has_ver = False
    row = (
        db.query(func.max(ControlEvidenceLink.confidence_score))
        .filter(ControlEvidenceLink.control_id == control_id)
        .first()
    )
    if row and row[0] is not None:
        max_conf = row[0]
    if db.query(ControlEvidenceLink).filter(
        ControlEvidenceLink.control_id == control_id,
        ControlEvidenceLink.verified.is_(True),
    ).first():
        has_ver = True
    return _workspace_control_dict(wc, db, max_confidence=max_conf, has_verified=has_ver)


@router.patch("/{control_id}", response_model=dict)
def patch_control(
    control_id: int,
    body: ControlPatchBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Update a workspace control. Requires admin."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    wc = _ensure_workspace_control(db, control_id, ws)
    if not wc:
        raise HTTPException(status_code=404, detail="Control not found")
    if body.status is not None:
        if body.status not in WORKSPACE_CONTROL_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {WORKSPACE_CONTROL_STATUSES}")
        if wc.status != body.status:
            compliance_control_status_changed_total.inc()
            logger.info("control_status_changed", extra={"control_id": control_id, "workspace_id": ws, "status": body.status})
        wc.status = body.status
    if body.custom_name is not None:
        wc.custom_name = body.custom_name.strip() or None
    if body.owner_user_id is not None:
        wc.owner_user_id = body.owner_user_id
    if body.owner_team is not None:
        wc.owner_team = body.owner_team.strip() or None
    db.commit()
    db.refresh(wc)
    return _workspace_control_dict(wc, db)


@router.post("/{control_id}/verify", response_model=dict)
def verify_control(
    control_id: int,
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Mark control as verified. Requires at least one linked evidence. Records who verified and when. Requires review permission."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    if not check_compliance_write_allowed(ws):
        raise HTTPException(status_code=429, detail="Too many compliance writes; try again later.")
    wc = _ensure_workspace_control(db, control_id, ws)
    if not wc:
        raise HTTPException(status_code=404, detail="Control not found")
    evidence_count = _count_evidence(db, control_id)
    if evidence_count < 1:
        raise HTTPException(status_code=400, detail="At least one linked evidence item is required to verify the control")
    now = datetime.utcnow()
    wc.status = "verified"
    wc.verified_at = now
    wc.verified_by_user_id = session.get("user_id")
    db.commit()
    db.refresh(wc)
    compliance_control_status_changed_total.inc()
    try:
        emit_compliance_event(
            db,
            ws,
            EVENT_CONTROL_VERIFIED,
            {
                "resource_type": "control",
                "resource_id": control_id,
                "verified_by_user_id": session.get("user_id"),
            },
            user_id=session.get("user_id"),
            email=session.get("email"),
        )
    except Exception:
        pass
    logger.info(
        "control_verified",
        extra={"control_id": control_id, "workspace_id": ws, "user_id": session.get("user_id")},
    )
    try:
        notify_admins(db, ws, "Control verified", f"Control #{control_id} has been verified.", category="success", link=f"/dashboard/controls")
    except Exception:
        pass
    return _workspace_control_dict(wc, db)


from app.api.helpers import evidence_dict as _evidence_dict


# Default staleness thresholds (days) when workspace has no config
STALE_VERIFIED_DAYS_DEFAULT = 365
STALE_UNVERIFIED_DAYS_DEFAULT = 90


def _link_dict(
    link: ControlEvidenceLink,
    stale_verified_days: int = STALE_VERIFIED_DAYS_DEFAULT,
    stale_unverified_days: int = STALE_UNVERIFIED_DAYS_DEFAULT,
    expires_at=None,
) -> dict:
    now = datetime.utcnow()
    expired = False
    if expires_at is not None:
        try:
            if hasattr(expires_at, "replace") and getattr(expires_at, "tzinfo", None):
                expires_at = expires_at.replace(tzinfo=None)
            expired = expires_at < now
        except (TypeError, ValueError):
            pass
    stale = expired
    if not stale:
        if link.verified and link.last_verified_at:
            stale = (now - link.last_verified_at).days > stale_verified_days
        elif not link.verified and link.created_at:
            stale = (now - link.created_at).days > stale_unverified_days
    return {
        "id": link.id,
        "control_id": link.control_id,
        "evidence_id": link.evidence_id,
        "confidence_score": link.confidence_score,
        "verified": link.verified,
        "last_verified_at": link.last_verified_at.isoformat() if link.last_verified_at else None,
        "created_at": link.created_at.isoformat() if link.created_at else None,
        "stale": stale,
        "expired": expired,
    }


@router.post("/{control_id}/evidence/accept-suggested", response_model=dict)
def accept_suggested_evidence(
    control_id: int,
    body: AcceptSuggestedEvidenceBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Create evidence from a suggested chunk and link it to the control. Requires admin."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    wc = _ensure_workspace_control(db, control_id, ws)
    if not wc:
        raise HTTPException(status_code=404, detail="Control not found")
    from app.models import Chunk, Document
    ch = db.query(Chunk).filter(
        Chunk.id == body.chunk_id,
        Chunk.workspace_id == ws,
    ).first()
    if not ch:
        raise HTTPException(status_code=404, detail="Chunk not found")
    doc_id = body.document_id or ch.document_id
    title = (body.snippet or ch.text or "")[:255].strip() or f"Chunk {body.chunk_id}"
    ev = EvidenceItem(
        workspace_id=ws,
        document_id=doc_id,
        source_type="document",
        title=title,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    score = max(0, min(1, body.confidence))
    link = ControlEvidenceLink(
        control_id=control_id,
        evidence_id=ev.id,
        confidence_score=score,
        verified=False,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    compliance_evidence_linked_total.inc()
    logger.info("evidence_linked", extra={"control_id": control_id, "evidence_id": ev.id, "workspace_id": ws})
    ev_tags = []
    if ev.document_id:
        from app.services.tag_service import list_tags_for_document
        ev_tags = list_tags_for_document(db, ev.document_id, ws)
    return {**_link_dict(link), "evidence": _evidence_dict(ev, tags=ev_tags)}


@router.post("/{control_id}/suggest-evidence", response_model=list)
def suggest_evidence(
    control_id: int,
    limit: int = Query(10, ge=1, le=50),
    min_confidence: float = Query(0.0, ge=0, le=1),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Suggest top relevant documents/chunks for this control (AI-assisted). Enforces workspace isolation."""
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(status_code=403, detail="No workspace")
    wc = _ensure_workspace_control(db, control_id, ws)
    if not wc:
        raise HTTPException(status_code=404, detail="Control not found")
    return suggest_evidence_service(db, control_id, ws, limit=limit, min_confidence=min_confidence)


def _staleness_days(db: Session, workspace_id: int) -> tuple[int, int]:
    w = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not w:
        return STALE_VERIFIED_DAYS_DEFAULT, STALE_UNVERIFIED_DAYS_DEFAULT
    v = w.evidence_stale_verified_days if w.evidence_stale_verified_days is not None else STALE_VERIFIED_DAYS_DEFAULT
    u = w.evidence_stale_unverified_days if w.evidence_stale_unverified_days is not None else STALE_UNVERIFIED_DAYS_DEFAULT
    return v, u


@router.get("/{control_id}/evidence", response_model=list)
def list_control_evidence(
    control_id: int,
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """List evidence linked to a workspace control. Enforces workspace isolation."""
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(status_code=403, detail="No workspace")
    wc = _ensure_workspace_control(db, control_id, ws)
    if not wc:
        raise HTTPException(status_code=404, detail="Control not found")
    links = db.query(ControlEvidenceLink).filter(ControlEvidenceLink.control_id == control_id).all()
    stale_verified_days, stale_unverified_days = _staleness_days(db, ws)
    evidence_ids = [link.evidence_id for link in links]
    expires_by_evidence = {}
    if evidence_ids:
        for meta in db.query(EvidenceMetadata).filter(EvidenceMetadata.evidence_id.in_(evidence_ids)).all():
            if meta.expires_at is not None:
                expires_by_evidence[meta.evidence_id] = meta.expires_at
    evidences = {ev.id: ev for ev in db.query(EvidenceItem).filter(EvidenceItem.id.in_(evidence_ids), EvidenceItem.workspace_id == ws).all()} if evidence_ids else {}
    doc_ids = [ev.document_id for ev in evidences.values() if ev.document_id]
    tags_by_doc = list_tags_for_documents(db, doc_ids, ws) if doc_ids else {}
    out = []
    for link in links:
        ev = evidences.get(link.evidence_id)
        if ev:
            ev_tags = tags_by_doc.get(ev.document_id, []) if ev.document_id else []
            out.append({
                **_link_dict(
                    link,
                    stale_verified_days=stale_verified_days,
                    stale_unverified_days=stale_unverified_days,
                    expires_at=expires_by_evidence.get(link.evidence_id),
                ),
                "evidence": _evidence_dict(ev, tags=ev_tags),
            })
    return out


@router.patch("/{control_id}/evidence/{link_id}", response_model=dict)
def set_evidence_verified(
    control_id: int,
    link_id: int,
    body: SetEvidenceVerifiedBody,
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Mark a control–evidence link as verified or unverified. Sets last_verified_at when verified. Requires review permission."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    if not check_compliance_write_allowed(ws):
        raise HTTPException(status_code=429, detail="Too many compliance writes; try again later.")
    wc = _ensure_workspace_control(db, control_id, ws)
    if not wc:
        raise HTTPException(status_code=404, detail="Control not found")
    link = db.query(ControlEvidenceLink).filter(
        ControlEvidenceLink.id == link_id,
        ControlEvidenceLink.control_id == control_id,
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    link.verified = body.verified
    link.last_verified_at = datetime.utcnow() if body.verified else None
    db.commit()
    db.refresh(link)
    try:
        emit_compliance_event(
            db,
            ws,
            EVENT_EVIDENCE_VERIFIED,
            {
                "resource_type": "evidence_link",
                "resource_id": link_id,
                "control_id": control_id,
                "evidence_id": link.evidence_id,
                "verified": body.verified,
            },
            user_id=session.get("user_id"),
            email=session.get("email"),
        )
    except Exception:
        pass
    if body.verified:
        try:
            notify_admins(db, ws, "Evidence verified", f"Evidence link #{link_id} for control #{control_id} verified.", category="success", link="/dashboard/controls")
        except Exception:
            pass
    ev = db.query(EvidenceItem).filter(EvidenceItem.id == link.evidence_id).first()
    ev_tags = []
    if ev and ev.workspace_id == ws and ev.document_id:
        from app.services.tag_service import list_tags_for_document
        ev_tags = list_tags_for_document(db, ev.document_id, ws)
    out = {**_link_dict(link), "evidence": _evidence_dict(ev, tags=ev_tags) if ev and ev.workspace_id == ws else {}}
    return out


@router.post("/{control_id}/evidence", response_model=dict)
def link_evidence(
    control_id: int,
    body: LinkEvidenceBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Link an evidence item to a workspace control. Requires admin."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    wc = _ensure_workspace_control(db, control_id, ws)
    if not wc:
        raise HTTPException(status_code=404, detail="Control not found")
    ev = db.query(EvidenceItem).filter(
        EvidenceItem.id == body.evidence_id,
        EvidenceItem.workspace_id == ws,
    ).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")
    existing = db.query(ControlEvidenceLink).filter(
        ControlEvidenceLink.control_id == control_id,
        ControlEvidenceLink.evidence_id == body.evidence_id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Evidence already linked to this control")
    score = body.confidence_score
    if score is not None and (score < 0 or score > 1):
        raise HTTPException(status_code=400, detail="confidence_score must be between 0 and 1")
    link = ControlEvidenceLink(
        control_id=control_id,
        evidence_id=body.evidence_id,
        confidence_score=score,
        verified=body.verified,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    compliance_evidence_linked_total.inc()
    logger.info(
        "evidence_linked",
        extra={"control_id": control_id, "evidence_id": body.evidence_id, "workspace_id": ws},
    )
    return _link_dict(link)


@router.delete("/{control_id}/evidence/{link_id}")
def unlink_evidence(
    control_id: int,
    link_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Remove an evidence link from a control. Requires admin."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    wc = _ensure_workspace_control(db, control_id, ws)
    if not wc:
        raise HTTPException(status_code=404, detail="Control not found")
    link = db.query(ControlEvidenceLink).filter(
        ControlEvidenceLink.id == link_id,
        ControlEvidenceLink.control_id == control_id,
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    db.delete(link)
    db.commit()
    return {"ok": True}

