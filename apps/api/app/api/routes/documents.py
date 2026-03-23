"""Document API (DOC-01, DOC-09)."""

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.schemas import BulkDeleteBody, MetadataUpdateBody
from app.core.auth_deps import require_can_edit, require_can_review
from app.core.audit import audit_log, persist_audit
from app.core.database import get_db
from app.models import Document, Job, JobStatus
from app.services.file_service import FileService
from app.services.registry_metadata import (
    FRAMEWORK_LABELS,
    SUBJECT_AREA_LABELS,
    build_display_id,
    normalize_labels,
    parse_json_list,
)
from app.services.registry_lifecycle import (
    build_delete_preview,
    restore_record,
    soft_delete_record,
    update_metadata_json_fields,
)
from app.services.storage import StorageClient, get_storage
from app.services.tag_service import list_tags_for_documents

router = APIRouter(prefix="/documents", tags=["documents"])


def get_file_service(storage: StorageClient = Depends(get_storage)) -> FileService:
    return FileService(storage)


@router.post("/upload")
def upload_document(
    workspace_id: int = Form(...),
    file: UploadFile = ...,
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
    file_svc: FileService = Depends(get_file_service),
):
    """Upload document and create domain record."""
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    key, filename = file_svc.upload_raw(workspace_id, file)
    doc = Document(
        workspace_id=workspace_id,
        storage_key=key,
        filename=filename,
        content_type=file.content_type,
        frameworks_json=json.dumps(["Other"]),
        subject_areas_json=json.dumps(["Other"]),
        status="uploaded",
    )
    db.add(doc)
    db.flush()
    doc.display_id = build_display_id("document", doc.id)
    db.commit()
    db.refresh(doc)
    job = Job(
        workspace_id=workspace_id,
        kind="index_document",
        status=JobStatus.QUEUED.value,
        payload=json.dumps({"document_id": doc.id}),
    )
    db.add(job)
    db.commit()
    audit_log("document.upload", email=session.get("email"), workspace_id=workspace_id, resource_type="document", resource_id=doc.id, details={"filename": doc.filename})
    return {
        "id": doc.id,
        "display_id": doc.display_id,
        "filename": doc.filename,
        "status": doc.status,
        "storage_key": doc.storage_key,
        "job_id": job.id,
        "frameworks": ["Other"],
        "subject_areas": ["Other"],
    }


_SEARCH_QUERY_MAX_LEN = 200


@router.get("/")
@router.get("")
def list_documents(
    workspace_id: int,
    q: str | None = Query(None, description="Legacy filename search"),
    search: str | None = Query(None, description="Search by id, filename, framework, subject, status"),
    framework: str | None = Query(None, description="Filter by framework chip label"),
    subject_area: str | None = Query(None, description="Filter by subject area chip label"),
    status: str | None = Query(None, description="Filter by status"),
    created_from: str | None = Query(None, description="Created-at lower bound ISO"),
    created_to: str | None = Query(None, description="Created-at upper bound ISO"),
    archived: str | None = Query(None, description="active|include|only"),
    tag_category: str | None = Query(None, description="Legacy tag category filter"),
    tag_key: str | None = Query(None, description="Legacy tag key filter"),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """List documents for workspace. Optional q filters by filename substring. Accepts with or without trailing slash."""
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    query = db.query(Document).filter(Document.workspace_id == workspace_id)
    mode = (archived or "active").strip().lower()
    if mode == "active":
        query = query.filter(Document.deleted_at.is_(None))
    elif mode == "only":
        query = query.filter(Document.deleted_at.is_not(None))
    search_q = (search or q or "").strip()[:_SEARCH_QUERY_MAX_LEN]
    if search_q:
        like = f"%{search_q}%"
        query = query.filter(
            (Document.display_id.ilike(like))
            | (Document.filename.ilike(like))
            | (Document.status.ilike(like))
            | (Document.frameworks_json.ilike(like))
            | (Document.subject_areas_json.ilike(like))
        )
    if framework:
        query = query.filter(Document.frameworks_json.ilike(f"%{framework.strip()}%"))
    if subject_area:
        query = query.filter(Document.subject_areas_json.ilike(f"%{subject_area.strip()}%"))
    if status:
        query = query.filter(Document.status == status)
    if created_from:
        try:
            query = query.filter(Document.created_at >= datetime.fromisoformat(created_from))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid created_from datetime")
    if created_to:
        try:
            query = query.filter(Document.created_at <= datetime.fromisoformat(created_to))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid created_to datetime")
    if tag_category or tag_key:
        from app.models.tag import DocumentTag, Tag
        query = query.join(DocumentTag, DocumentTag.document_id == Document.id).join(Tag, DocumentTag.tag_id == Tag.id)
        if tag_category:
            query = query.filter(Tag.category == tag_category)
        if tag_key:
            query = query.filter(Tag.key == tag_key)
        query = query.distinct()

    docs = query.order_by(Document.created_at.desc(), Document.id.desc()).all()
    doc_ids = [d.id for d in docs]
    tags_map = list_tags_for_documents(db, doc_ids, workspace_id) if doc_ids else {}
    return [
        {
            "id": d.id,
            "display_id": d.display_id or build_display_id("document", d.id),
            "filename": d.filename,
            "status": d.status,
            "index_error": getattr(d, "index_error", None),
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "deleted_at": d.deleted_at.isoformat() if d.deleted_at else None,
            "file_type": Path(d.filename or "").suffix.lstrip(".").lower() or None,
            "frameworks": normalize_labels(
                (
                    [t["label"] for t in tags_map.get(d.id, []) if t.get("category") == "framework"]
                    + parse_json_list(d.frameworks_json)
                ),
                allowed=FRAMEWORK_LABELS,
            ),
            "subject_areas": normalize_labels(
                (
                    [t["label"] for t in tags_map.get(d.id, []) if t.get("category") == "topic"]
                    + parse_json_list(d.subject_areas_json)
                ),
                allowed=SUBJECT_AREA_LABELS,
            ),
            "tags": tags_map.get(d.id, []),
        }
        for d in docs
    ]


@router.post("/bulk-delete")
def bulk_delete_documents(
    body: BulkDeleteBody,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    """Bulk soft-delete documents. Only active (non-archived) records in workspace are processed."""
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if not body.ids:
        return {"deleted": 0, "errors": []}
    docs = (
        db.query(Document)
        .filter(
            Document.id.in_(body.ids),
            Document.workspace_id == workspace_id,
            Document.deleted_at.is_(None),
        )
        .all()
    )
    for doc in docs:
        soft_delete_record(doc, session.get("user_id"))
        persist_audit(
            db,
            "document.soft_delete",
            user_id=session.get("user_id"),
            email=session.get("email"),
            workspace_id=workspace_id,
            resource_type="document",
            resource_id=doc.id,
            details={"display_id": doc.display_id},
        )
    db.commit()
    return {"deleted": len(docs), "errors": []}


@router.delete("/{document_id}")
def delete_document(
    document_id: int,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    doc = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.workspace_id == workspace_id,
            Document.deleted_at.is_(None),
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    preview = build_delete_preview("document", db, workspace_id, document_id)
    soft_delete_record(doc, session.get("user_id"))
    db.commit()
    persist_audit(
        db,
        "document.soft_delete",
        user_id=session.get("user_id"),
        email=session.get("email"),
        workspace_id=workspace_id,
        resource_type="document",
        resource_id=document_id,
        details={"display_id": doc.display_id, "dependencies": preview.dependencies},
    )
    return {
        "ok": True,
        "id": doc.id,
        "display_id": doc.display_id or build_display_id("document", doc.id),
        "dependencies": preview.dependencies,
    }


@router.get("/{document_id}/delete-preview")
def delete_preview_document(
    document_id: int,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    doc = (
        db.query(Document)
        .filter(Document.id == document_id, Document.workspace_id == workspace_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    preview = build_delete_preview("document", db, workspace_id, document_id)
    persist_audit(
        db,
        "document.delete_preview",
        user_id=session.get("user_id"),
        email=session.get("email"),
        workspace_id=workspace_id,
        resource_type="document",
        resource_id=document_id,
        details={"display_id": doc.display_id, "dependencies": preview.dependencies},
    )
    return {
        "id": document_id,
        "display_id": doc.display_id or preview.display_id,
        "can_delete": preview.can_delete,
        "recommended_action": preview.recommended_action,
        "warnings": preview.warnings,
        "dependencies": preview.dependencies,
        "unmodeled_warning": preview.unmodeled_warning,
    }


@router.post("/{document_id}/restore")
def restore_document(
    document_id: int,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    doc = (
        db.query(Document)
        .filter(Document.id == document_id, Document.workspace_id == workspace_id, Document.deleted_at.is_not(None))
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Archived document not found")
    restore_record(doc)
    db.commit()
    persist_audit(
        db,
        "document.restore",
        user_id=session.get("user_id"),
        email=session.get("email"),
        workspace_id=workspace_id,
        resource_type="document",
        resource_id=document_id,
        details={"display_id": doc.display_id},
    )
    return {"ok": True, "id": doc.id, "display_id": doc.display_id}


@router.patch("/{document_id}/metadata")
def update_document_metadata(
    document_id: int,
    body: MetadataUpdateBody,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    doc = (
        db.query(Document)
        .filter(Document.id == document_id, Document.workspace_id == workspace_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    update_metadata_json_fields(
        doc,
        body.frameworks,
        body.subject_areas,
    )
    db.commit()
    persist_audit(
        db,
        "document.metadata_update",
        user_id=session.get("user_id"),
        email=session.get("email"),
        workspace_id=workspace_id,
        resource_type="document",
        resource_id=document_id,
        details={"display_id": doc.display_id, "frameworks": body.frameworks, "subject_areas": body.subject_areas},
    )
    return {"ok": True}
