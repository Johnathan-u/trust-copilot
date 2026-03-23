"""Phase 4: Compliance exports - controls list, gaps, control-evidence summary (CSV/JSON)."""

import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.auth_deps import require_can_export
from app.core.database import get_db
from app.models import (
    WorkspaceControl,
    FrameworkControl,
    Framework,
    ControlEvidenceLink,
)

from app.api.constants import LOW_CONFIDENCE_THRESHOLD

router = APIRouter(prefix="/compliance/export", tags=["compliance-export"])


def _control_row(wc: WorkspaceControl, db: Session) -> dict:
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
    evidence_count = db.query(ControlEvidenceLink).filter(ControlEvidenceLink.control_id == wc.id).count()
    max_conf_row = (
        db.query(func.max(ControlEvidenceLink.confidence_score))
        .filter(ControlEvidenceLink.control_id == wc.id)
        .first()
    )
    max_conf = max_conf_row[0] if max_conf_row else None
    has_verified = (
        db.query(ControlEvidenceLink)
        .filter(ControlEvidenceLink.control_id == wc.id, ControlEvidenceLink.verified.is_(True))
        .first()
        is not None
    )
    return {
        "id": wc.id,
        "control_key": control_key,
        "name": title,
        "framework": framework_name,
        "category": category,
        "status": wc.status,
        "evidence_count": evidence_count,
        "max_confidence": round(max_conf, 4) if max_conf is not None else None,
        "has_verified": has_verified,
        "verified_at": wc.verified_at.isoformat() if wc.verified_at else None,
        "verified_by_user_id": wc.verified_by_user_id,
        "created_at": wc.created_at.isoformat() if wc.created_at else None,
    }


@router.get("/controls")
def export_controls(
    format: str = Query("json", description="csv or json"),
    session: dict = Depends(require_can_export),
    db: Session = Depends(get_db),
):
    """Export controls list as JSON or CSV. Requires export permission."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    rows = db.query(WorkspaceControl).filter(WorkspaceControl.workspace_id == ws).all()
    data = [_control_row(wc, db) for wc in rows]
    if (format or "").lower() == "csv":
        if not data:
            return Response(content="id,control_key,name,framework,category,status,evidence_count,max_confidence,has_verified,verified_at,verified_by_user_id,created_at\n", media_type="text/csv")
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=list(data[0].keys()), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)
        return Response(content=out.getvalue(), media_type="text/csv")
    return Response(content=json.dumps(data, default=str), media_type="application/json")


def _gaps_data(db: Session, ws: int, low_confidence_threshold: float) -> list:
    out = []
    for wc in db.query(WorkspaceControl).filter(WorkspaceControl.workspace_id == ws).all():
        link_stats = (
            db.query(func.count(ControlEvidenceLink.id), func.max(ControlEvidenceLink.confidence_score))
            .filter(ControlEvidenceLink.control_id == wc.id)
            .first()
        )
        evidence_count = link_stats[0] or 0
        max_conf = link_stats[1] or 0.0
        if evidence_count == 0:
            gap_reason = "no_evidence"
        elif max_conf < low_confidence_threshold:
            gap_reason = "low_confidence"
        else:
            continue
        framework_name = None
        control_key = None
        title = wc.custom_name or None
        if wc.framework_control_id:
            fc = db.query(FrameworkControl).filter(FrameworkControl.id == wc.framework_control_id).first()
            if fc:
                control_key = fc.control_key
                title = title or fc.title
                fw = db.query(Framework).filter(Framework.id == fc.framework_id).first()
                if fw:
                    framework_name = fw.name
        out.append({
            "control_id": wc.id,
            "control_key": control_key,
            "name": title,
            "framework": framework_name,
            "evidence_count": evidence_count,
            "max_confidence": round(max_conf, 4),
            "gap_reason": gap_reason,
        })
    return out


@router.get("/gaps")
def export_gaps(
    format: str = Query("json", description="csv or json"),
    low_confidence_threshold: float = Query(LOW_CONFIDENCE_THRESHOLD, ge=0, le=1),
    session: dict = Depends(require_can_export),
    db: Session = Depends(get_db),
):
    """Export compliance gaps as JSON or CSV. Requires export permission."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    data = _gaps_data(db, ws, low_confidence_threshold)
    if (format or "").lower() == "csv":
        if not data:
            return Response(content="control_id,control_key,name,framework,evidence_count,max_confidence,gap_reason\n", media_type="text/csv")
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=list(data[0].keys()), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)
        return Response(content=out.getvalue(), media_type="text/csv")
    return Response(content=json.dumps(data, default=str), media_type="application/json")


@router.get("/control-evidence-summary")
def export_control_evidence_summary(
    format: str = Query("json", description="csv or json"),
    session: dict = Depends(require_can_export),
    db: Session = Depends(get_db),
):
    """Export control–evidence summary (one row per control with evidence counts and verified count). Requires export permission."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    data = []
    for wc in db.query(WorkspaceControl).filter(WorkspaceControl.workspace_id == ws).all():
        links = db.query(ControlEvidenceLink).filter(ControlEvidenceLink.control_id == wc.id).all()
        evidence_count = len(links)
        verified_count = sum(1 for l in links if l.verified)
        framework_name = None
        control_key = None
        title = (wc.custom_name or "").strip() or None
        if wc.framework_control_id:
            fc = db.query(FrameworkControl).filter(FrameworkControl.id == wc.framework_control_id).first()
            if fc:
                control_key = fc.control_key
                title = title or fc.title
                fw = db.query(Framework).filter(Framework.id == fc.framework_id).first()
                if fw:
                    framework_name = fw.name
        data.append({
            "control_id": wc.id,
            "control_key": control_key,
            "name": title,
            "framework": framework_name,
            "status": wc.status,
            "evidence_count": evidence_count,
            "verified_evidence_count": verified_count,
            "verified_at": wc.verified_at.isoformat() if wc.verified_at else None,
            "verified_by_user_id": wc.verified_by_user_id,
        })
    if (format or "").lower() == "csv":
        if not data:
            return Response(content="control_id,control_key,name,framework,status,evidence_count,verified_evidence_count,verified_at,verified_by_user_id\n", media_type="text/csv")
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=list(data[0].keys()), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)
        return Response(content=out.getvalue(), media_type="text/csv")
    return Response(content=json.dumps(data, default=str), media_type="application/json")
