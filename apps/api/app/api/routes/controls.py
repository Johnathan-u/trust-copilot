"""Controls and frameworks API (TC-R-B2). Evidence linking (TC-R-B3)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_can_review
from app.core.database import get_db
from app.models import Control, ControlEvidence, Document, ExportRecord, TrustArticle
from app.models.control import CONTROL_STATUSES

router = APIRouter(prefix="/controls", tags=["controls"])


class ControlCreate(BaseModel):
    framework: str
    control_id: str
    name: str | None = None
    status: str = "in_review"


class ControlUpdate(BaseModel):
    framework: str | None = None
    control_id: str | None = None
    name: str | None = None
    status: str | None = None


class EvidenceAttach(BaseModel):
    document_id: int | None = None
    trust_article_id: int | None = None
    export_record_id: int | None = None


def _control_dict(c: Control) -> dict:
    return {
        "id": c.id,
        "workspace_id": c.workspace_id,
        "framework": c.framework,
        "control_id": c.control_id,
        "name": c.name,
        "status": c.status,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
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
    q = db.query(Control).filter(Control.workspace_id == ws).order_by(Control.framework, Control.control_id)
    if framework:
        q = q.filter(Control.framework == framework)
    return [_control_dict(c) for c in q.all()]


@router.post("/")
def create_control(
    body: ControlCreate,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Create a control. Requires admin."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    if body.status not in CONTROL_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {CONTROL_STATUSES}")
    c = Control(
        workspace_id=ws,
        framework=body.framework.strip(),
        control_id=body.control_id.strip(),
        name=body.name.strip() if body.name else None,
        status=body.status,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _control_dict(c)


@router.patch("/{control_id}")
def update_control(
    control_id: int,
    body: ControlUpdate,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Update a control. Requires admin."""
    c = db.query(Control).filter(Control.id == control_id).first()
    if not c or c.workspace_id != session.get("workspace_id"):
        raise HTTPException(status_code=404, detail="Control not found")
    if body.framework is not None:
        c.framework = body.framework.strip()
    if body.control_id is not None:
        c.control_id = body.control_id.strip()
    if body.name is not None:
        c.name = body.name.strip() or None
    if body.status is not None:
        if body.status not in CONTROL_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {CONTROL_STATUSES}")
        c.status = body.status
    db.commit()
    db.refresh(c)
    return _control_dict(c)


@router.delete("/{control_id}")
def delete_control(
    control_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Delete a control. Requires admin."""
    c = db.query(Control).filter(Control.id == control_id).first()
    if not c or c.workspace_id != session.get("workspace_id"):
        raise HTTPException(status_code=404, detail="Control not found")
    db.delete(c)
    db.commit()
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
        item = {"id": r.id, "control_id": r.control_id, "document_id": r.document_id, "trust_article_id": r.trust_article_id, "export_record_id": r.export_record_id}
        if r.document_id:
            doc = db.query(Document).filter(Document.id == r.document_id).first()
            item["label"] = doc.filename if doc else f"Document {r.document_id}"
        elif r.trust_article_id:
            art = db.query(TrustArticle).filter(TrustArticle.id == r.trust_article_id).first()
            item["label"] = art.title if art else f"Article {r.trust_article_id}"
        elif r.export_record_id:
            rec = db.query(ExportRecord).filter(ExportRecord.id == r.export_record_id).first()
            item["label"] = rec.filename if rec else f"Export {r.export_record_id}"
        else:
            item["label"] = "Unknown"
        out.append(item)
    return out


@router.post("/{control_id}/evidence")
def attach_evidence(
    control_id: int,
    body: EvidenceAttach,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Attach one piece of evidence (document, article, or export) to a control. Requires admin."""
    ws = session.get("workspace_id")
    c = db.query(Control).filter(Control.id == control_id).first()
    if not c or c.workspace_id != ws:
        raise HTTPException(status_code=404, detail="Control not found")
    if sum(1 for x in [body.document_id, body.trust_article_id, body.export_record_id] if x is not None) != 1:
        raise HTTPException(status_code=400, detail="Provide exactly one of document_id, trust_article_id, export_record_id")
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
    ev = ControlEvidence(
        control_id=control_id,
        document_id=body.document_id,
        trust_article_id=body.trust_article_id,
        export_record_id=body.export_record_id,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return {"id": ev.id, "control_id": ev.control_id, "document_id": ev.document_id, "trust_article_id": ev.trust_article_id, "export_record_id": ev.export_record_id}


@router.delete("/{control_id}/evidence/{evidence_id}")
def detach_evidence(
    control_id: int,
    evidence_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Remove an evidence link from a control. Requires admin."""
    ev = db.query(ControlEvidence).filter(ControlEvidence.id == evidence_id, ControlEvidence.control_id == control_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence link not found")
    c = db.query(Control).filter(Control.id == control_id).first()
    if not c or c.workspace_id != session.get("workspace_id"):
        raise HTTPException(status_code=404, detail="Control not found")
    db.delete(ev)
    db.commit()
    return {"ok": True}
