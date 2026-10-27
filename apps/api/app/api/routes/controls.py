"""Controls and frameworks API (TC-R-B2). Evidence linking (TC-R-B3)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_edit, require_can_review
from app.core.database import get_db
from app.models import Control, ControlEvidence, Document, ExportRecord, TrustArticle
from app.models.control import CONTROL_STATUSES
from app.services.control_contract import (
    attach_legacy_evidence,
    canonical_payload,
    delete_legacy_control,
    detach_legacy_evidence,
    new_request_id,
    upsert_legacy_control,
)

router = APIRouter(prefix="/controls", tags=["controls"])


class ControlCreate(BaseModel):
    framework: str
    control_id: str
    name: str | None = None
    status: str = "in_review"
    owner_user_id: int | None = None
    owner_team: str | None = None


class ControlUpdate(BaseModel):
    framework: str | None = None
    control_id: str | None = None
    name: str | None = None
    status: str | None = None
    owner_user_id: int | None = None
    owner_team: str | None = None


class EvidenceAttach(BaseModel):
    document_id: int | None = None
    trust_article_id: int | None = None
    export_record_id: int | None = None


def _raise_contract(result) -> None:
    if result.http_status < 400:
        return
    error = result.error or {"detail": "Control not found"}
    if set(error) == {"detail"}:
        raise HTTPException(status_code=result.http_status, detail=error["detail"])
    raise HTTPException(status_code=result.http_status, detail=error)


def _control_dict(c: Control, db: Session) -> dict:
    from app.services.control_contract import workspace_for_legacy

    paired = workspace_for_legacy(db, c)
    return {
        "id": c.id,
        "workspace_id": c.workspace_id,
        "framework": c.framework,
        "control_id": c.control_id,
        "name": c.name,
        "status": c.status,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        "canonical": canonical_payload(db, c, paired),
    }


def _evidence_target_kind(row: ControlEvidence) -> str:
    if row.document_id is not None:
        return "document"
    if row.trust_article_id is not None:
        return "trust_article"
    if row.export_record_id is not None:
        return "export"
    return "unknown"


def _evidence_dict(row: ControlEvidence, label: str) -> dict:
    return {
        "id": row.id,
        "control_id": row.control_id,
        "document_id": row.document_id,
        "trust_article_id": row.trust_article_id,
        "export_record_id": row.export_record_id,
        "label": label,
        "canonical": {
            "contract_version": "control-evidence/v1",
            "target_kind": _evidence_target_kind(row),
            "workspace_scoped": True,
            "exactly_one_target": True,
            "evidence_item_id": row.evidence_item_id,
        },
    }


@router.get("/")
@router.get("")
def list_controls(
    framework: str | None = Query(None),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """List controls for workspace. Optional filter by framework."""
    ws = session.get("workspace_id")
    if ws is None:
        return []
    q = (
        db.query(Control)
        .filter(Control.workspace_id == ws)
        .order_by(Control.framework, Control.control_id)
    )
    if framework:
        q = q.filter(Control.framework == framework)
    return [_control_dict(c, db) for c in q.all()]


@router.post("/")
def create_control(
    body: ControlCreate,
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    """Create a control. Requires edit permission. Repeating the same identity reuses the row."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    if body.status not in CONTROL_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {CONTROL_STATUSES}")
    result = upsert_legacy_control(
        db,
        workspace_id=ws,
        framework=body.framework,
        control_key=body.control_id,
        name=body.name.strip() if body.name else None,
        legacy_status=body.status,
        owner_user_id=body.owner_user_id,
        owner_team=body.owner_team,
        request_id=new_request_id(),
    )
    _raise_contract(result)
    return _control_dict(result.ids["legacy"], db)


@router.patch("/{control_id}")
def update_control(
    control_id: int,
    body: ControlUpdate,
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    """Update a control. Requires edit permission. A workspace mismatch is 404."""
    ws = session.get("workspace_id")
    c = db.query(Control).filter(Control.id == control_id).first()
    if not c or c.workspace_id != ws:
        raise HTTPException(status_code=404, detail="Control not found")
    status = c.status
    if body.status is not None:
        if body.status not in CONTROL_STATUSES:
            raise HTTPException(
                status_code=400, detail=f"Invalid status. Allowed: {CONTROL_STATUSES}"
            )
        status = body.status
    name = c.name
    if "name" in body.model_fields_set:
        name = body.name.strip() if body.name else None
    owner_user_id = c.owner_user_id
    if "owner_user_id" in body.model_fields_set:
        owner_user_id = body.owner_user_id
    owner_team = c.owner_team
    if "owner_team" in body.model_fields_set:
        owner_team = body.owner_team
    result = upsert_legacy_control(
        db,
        workspace_id=ws,
        framework=body.framework if body.framework is not None else c.framework,
        control_key=body.control_id if body.control_id is not None else c.control_id,
        name=name,
        legacy_status=status,
        owner_user_id=owner_user_id,
        owner_team=owner_team,
        request_id=new_request_id(),
        legacy_id=c.id,
    )
    _raise_contract(result)
    return _control_dict(result.ids["legacy"], db)


@router.delete("/{control_id}")
def delete_control(
    control_id: int,
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    """Delete a control. Requires edit permission. A workspace mismatch is 404."""
    c = db.query(Control).filter(Control.id == control_id).first()
    if not c or c.workspace_id != session.get("workspace_id"):
        raise HTTPException(status_code=404, detail="Control not found")
    delete_legacy_control(db, c)
    return {"ok": True}


@router.get("/{control_id}/evidence")
def list_control_evidence(
    control_id: int,
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """List evidence linked to a control."""
    c = db.query(Control).filter(Control.id == control_id).first()
    if not c or c.workspace_id != session.get("workspace_id"):
        raise HTTPException(status_code=404, detail="Control not found")
    rows = db.query(ControlEvidence).filter(ControlEvidence.control_id == control_id).all()
    out = []
    for r in rows:
        if r.document_id:
            doc = db.query(Document).filter(Document.id == r.document_id).first()
            label = doc.filename if doc else f"Document {r.document_id}"
        elif r.trust_article_id:
            art = db.query(TrustArticle).filter(TrustArticle.id == r.trust_article_id).first()
            label = art.title if art else f"Article {r.trust_article_id}"
        elif r.export_record_id:
            rec = db.query(ExportRecord).filter(ExportRecord.id == r.export_record_id).first()
            label = rec.filename if rec else f"Export {r.export_record_id}"
        else:
            label = "Unknown"
        out.append(_evidence_dict(r, label))
    return out


@router.post("/{control_id}/evidence")
def attach_evidence(
    control_id: int,
    body: EvidenceAttach,
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    """Attach one piece of evidence (document, article, or export) to a control. Requires admin."""
    ws = session.get("workspace_id")
    c = db.query(Control).filter(Control.id == control_id).first()
    if not c or c.workspace_id != ws:
        raise HTTPException(status_code=404, detail="Control not found")
    if (
        sum(
            1
            for x in [body.document_id, body.trust_article_id, body.export_record_id]
            if x is not None
        )
        != 1
    ):
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of document_id, trust_article_id, export_record_id",
        )
    if body.document_id:
        doc = db.query(Document).filter(Document.id == body.document_id).first()
        if not doc or doc.workspace_id != ws:
            raise HTTPException(status_code=404, detail="Document not found in this workspace")
    if body.trust_article_id:
        art = db.query(TrustArticle).filter(TrustArticle.id == body.trust_article_id).first()
        if not art or art.workspace_id != ws:
            raise HTTPException(status_code=404, detail="Trust article not found in this workspace")
    if body.export_record_id:
        rec = db.query(ExportRecord).filter(ExportRecord.id == body.export_record_id).first()
        if not rec or rec.workspace_id != ws:
            raise HTTPException(status_code=404, detail="Export record not found in this workspace")
    result = attach_legacy_evidence(
        db,
        c,
        document_id=body.document_id,
        trust_article_id=body.trust_article_id,
        export_record_id=body.export_record_id,
    )
    _raise_contract(result)
    ev = result.ids["evidence"]
    return _evidence_dict(ev, "linked")


@router.delete("/{control_id}/evidence/{evidence_id}")
def detach_evidence(
    control_id: int,
    evidence_id: int,
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    """Remove an evidence link from a control. Requires admin."""
    ev = (
        db.query(ControlEvidence)
        .filter(ControlEvidence.id == evidence_id, ControlEvidence.control_id == control_id)
        .first()
    )
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence link not found")
    c = db.query(Control).filter(Control.id == control_id).first()
    if not c or c.workspace_id != session.get("workspace_id"):
        raise HTTPException(status_code=404, detail="Control not found")
    detach_legacy_evidence(db, c, ev)
    return {"ok": True}
