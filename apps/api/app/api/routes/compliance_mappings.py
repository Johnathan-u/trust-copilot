"""Compliance foundation: cross-framework control mappings; Phase 2 confirm/override; Phase 3 mapping-suggest."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_can_review
from app.core.database import get_db
from app.models import ControlMapping, FrameworkControl, Framework, WorkspaceControl, ControlMappingOverride
from app.services.question_normalizer import normalize_question, question_cache_hash
from app.services.compliance_hooks import question_to_controls
from app.core.compliance_rate_limit import check_compliance_write_allowed
from app.services.compliance_webhook_emitter import (
    emit_compliance_event,
    EVENT_MAPPING_CONFIRMED,
    EVENT_MAPPING_OVERRIDDEN,
)
from app.services.in_app_notification_service import notify_admins

router = APIRouter(prefix="/compliance/control-mappings", tags=["compliance-mappings"])


class ConfirmMappingBody(BaseModel):
    question: str
    control_ids: list[int]


class OverrideMappingBody(BaseModel):
    question: str
    control_ids: list[int]


def _framework_id_by_name(db: Session, name: str) -> list[int]:
    return [r[0] for r in db.query(Framework.id).filter(Framework.name == name).all()]


def _fc_ids_for_framework(db: Session, framework_name: str) -> list[int]:
    fw_ids = _framework_id_by_name(db, framework_name)
    if not fw_ids:
        return []
    return [
        r[0]
        for r in db.query(FrameworkControl.id).filter(FrameworkControl.framework_id.in_(fw_ids)).all()
    ]


@router.get("", response_model=list)
def list_control_mappings(
    source_framework: str | None = Query(None, description="Filter by source framework name"),
    target_framework: str | None = Query(None, description="Filter by target framework name"),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """List cross-framework control mappings. Optional filters by framework name."""
    q = db.query(ControlMapping).order_by(ControlMapping.id)
    if source_framework is not None:
        src_fc_ids = _fc_ids_for_framework(db, source_framework)
        if not src_fc_ids:
            return []
        q = q.filter(ControlMapping.source_control_id.in_(src_fc_ids))
    if target_framework is not None:
        tgt_fc_ids = _fc_ids_for_framework(db, target_framework)
        if not tgt_fc_ids:
            return []
        q = q.filter(ControlMapping.target_control_id.in_(tgt_fc_ids))
    rows = q.all()
    out = []
    for r in rows:
        src_fc = db.query(FrameworkControl).filter(FrameworkControl.id == r.source_control_id).first()
        src_fw = db.query(Framework).filter(Framework.id == src_fc.framework_id).first() if src_fc else None
        tgt_fc = db.query(FrameworkControl).filter(FrameworkControl.id == r.target_control_id).first()
        tgt_fw = db.query(Framework).filter(Framework.id == tgt_fc.framework_id).first() if tgt_fc else None
        out.append({
            "id": r.id,
            "source_control_id": r.source_control_id,
            "target_control_id": r.target_control_id,
            "source_key": src_fc.control_key if src_fc else None,
            "source_framework": src_fw.name if src_fw else None,
            "target_key": tgt_fc.control_key if tgt_fc else None,
            "target_framework": tgt_fw.name if tgt_fw else None,
        })
    return out


def _upsert_mapping_override(db: Session, workspace_id: int, question: str, control_ids: list[int]) -> dict:
    norm = normalize_question(question or "")
    q_hash = question_cache_hash(norm) if norm else ""
    if not q_hash:
        raise HTTPException(status_code=400, detail="question is required")
    ids = [int(x) for x in control_ids if x is not None]
    if ids:
        valid = db.query(WorkspaceControl.id).filter(
            WorkspaceControl.workspace_id == workspace_id,
            WorkspaceControl.id.in_(ids),
        ).all()
        valid_ids = {r[0] for r in valid}
        if set(ids) != valid_ids:
            raise HTTPException(status_code=400, detail="All control_ids must belong to this workspace")
    existing = (
        db.query(ControlMappingOverride)
        .filter(
            ControlMappingOverride.workspace_id == workspace_id,
            ControlMappingOverride.question_hash == q_hash,
        )
        .first()
    )
    if existing:
        existing.override_control_ids = ids
        db.commit()
        db.refresh(existing)
        return {"question_hash": q_hash, "control_ids": ids, "updated": True}
    row = ControlMappingOverride(workspace_id=workspace_id, question_hash=q_hash, override_control_ids=ids)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"question_hash": q_hash, "control_ids": ids, "updated": False}


@router.post("/confirm", response_model=dict)
def confirm_mapping(
    body: ConfirmMappingBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Store current question -> control_ids mapping as confirmed (for reuse). Requires admin."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    if not check_compliance_write_allowed(ws):
        raise HTTPException(status_code=429, detail="Too many compliance writes; try again later.")
    result = _upsert_mapping_override(db, ws, body.question, body.control_ids)
    try:
        emit_compliance_event(
            db,
            ws,
            EVENT_MAPPING_CONFIRMED,
            {
                "resource_type": "mapping",
                "resource_id": result.get("question_hash"),
                "question": body.question[:500] if body.question else None,
                "question_hash": result.get("question_hash"),
                "control_ids": result.get("control_ids", []),
            },
            user_id=session.get("user_id"),
            email=session.get("email"),
        )
    except Exception:
        pass
    try:
        notify_admins(db, ws, "Mapping confirmed", f"Question-to-control mapping confirmed.", category="info", link="/dashboard/mapping-review")
    except Exception:
        pass
    return result


@router.post("/override", response_model=dict)
def override_mapping(
    body: OverrideMappingBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Store manual override of question -> control_ids. Requires admin."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    if not check_compliance_write_allowed(ws):
        raise HTTPException(status_code=429, detail="Too many compliance writes; try again later.")
    result = _upsert_mapping_override(db, ws, body.question, body.control_ids)
    try:
        emit_compliance_event(
            db,
            ws,
            EVENT_MAPPING_OVERRIDDEN,
            {
                "resource_type": "mapping",
                "resource_id": result.get("question_hash"),
                "question": body.question[:500] if body.question else None,
                "question_hash": result.get("question_hash"),
                "control_ids": result.get("control_ids", []),
            },
            user_id=session.get("user_id"),
            email=session.get("email"),
        )
    except Exception:
        pass
    try:
        notify_admins(db, ws, "Mapping overridden", f"Question-to-control mapping manually overridden.", category="warning", link="/dashboard/mapping-review")
    except Exception:
        pass
    return result


@router.get("/suggest", response_model=dict)
def mapping_suggest(
    question: str = Query(..., min_length=1),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Return likely control_ids for a question (reuses override if saved). Lightweight explainability in reason."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    norm = normalize_question(question or "")
    q_hash = question_cache_hash(norm) if norm else ""
    override = (
        db.query(ControlMappingOverride)
        .filter(
            ControlMappingOverride.workspace_id == ws,
            ControlMappingOverride.question_hash == q_hash,
        )
        .first()
    )
    if override and isinstance(override.override_control_ids, list):
        ids = [int(x) for x in override.override_control_ids if x is not None]
        return {
            "control_ids": ids,
            "confidence": 1.0,
            "has_override": True,
            "reason": "Saved mapping (confirmed or overridden).",
        }
    ids, match_confidence = question_to_controls(question or "", ws, db)
    return {
        "control_ids": ids,
        "confidence": match_confidence,
        "has_override": False,
        "reason": "Matched by keywords/category to framework controls." if ids else "No matching controls found.",
    }
