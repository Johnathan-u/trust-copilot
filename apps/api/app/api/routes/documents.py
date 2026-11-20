"""Document API (DOC-01, DOC-09)."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.schemas import BulkDeleteBody, MetadataUpdateBody
from app.core.api_errors import ApiError, FieldError, api_error_response, current_request_id
from app.core.auth_deps import require_can_edit, require_can_review
from app.core.audit import audit_log, persist_audit
from app.core.config import get_settings
from app.core.database import get_db
from app.core.idempotency import (
    IdempotencyKeyError,
    claim as idempotency_claim,
    get as idempotency_get,
    release as idempotency_release,
    scoped_key as idempotency_scoped_key,
    set as idempotency_set,
)
from app.models import Document, EvidenceItem, EvidenceVersion, Job
from app.models.job import JobStatus
from app.services.file_service import FileService, sanitize_filename, validate_storage_key
from app.services.freshness_policy_service import get_effective_policy
from app.services.job_effects import enqueue_job, job_idempotency_key
from app.services.storage_reconcile import discard_if_unreferenced
from app.services.upload_enqueue import UPLOAD_IDEMPOTENCY_RESOURCE
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
from app.services.retrieval_cache import invalidate_after_document_visibility_change
from app.services.storage import StorageClient, get_storage
from app.services.tag_service import list_tags_for_documents

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)
_UPLOAD_SCOPE = "documents.upload"


def get_file_service(storage: StorageClient = Depends(get_storage)) -> FileService:
    return FileService(storage)


def _upload_idempotency_key(request: Request, workspace_id: int):
    """Stored key, "" when the header is absent, or a 400 when the header is invalid."""
    raw = request.headers.get("Idempotency-Key")
    try:
        return idempotency_scoped_key(workspace_id, _UPLOAD_SCOPE, UPLOAD_IDEMPOTENCY_RESOURCE, raw)
    except IdempotencyKeyError as exc:
        message = str(exc)
        error = ApiError(
            code="invalid_idempotency_key",
            message=message,
            request_id=current_request_id(request),
            retryable=False,
            field_errors=[FieldError(field="Idempotency-Key", code="invalid", message=message)],
        )
        return api_error_response(error, 400)


def _release_upload_claim(db: Session, idem_key: str, idem_owner: str | None) -> None:
    if not idem_key:
        return
    try:
        idempotency_release(db, idem_key, owner=idem_owner)
    except Exception:
        logger.warning("document upload: failed to release idempotency claim", exc_info=True)


@router.post("/upload")
def upload_document(
    request: Request,
    workspace_id: int = Form(...),
    file: UploadFile = ...,
    frameworks: str = Form(""),
    subject_areas: str = Form(""),
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
    file_svc: FileService = Depends(get_file_service),
):
    """Upload document and create domain record.

    The document, its index job, and the optional Idempotency-Key response commit once.
    A retryable enqueue conflict rolls that transaction back and deletes the stored object
    when no row references it, so the client's retry does not create a second row. A failed
    delete is logged. The orphan sweep removes the object after the grace period.
    """
    # Authorize before the idempotency store or object storage: a 403 is never cached or stored.
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    idem_key = _upload_idempotency_key(request, workspace_id)
    if isinstance(idem_key, JSONResponse):
        return idem_key
    idem_owner: str | None = None
    if idem_key:
        cached = idempotency_get(db, idem_key)
        if cached:
            return JSONResponse(content=cached[1], status_code=cached[0])
        # TC-10-003b: keep the owner token so a late set cannot overwrite a reclaimed claim.
        idem_owner = idempotency_claim(db, idem_key)
        if idem_owner is None:
            cached2 = idempotency_get(db, idem_key)
            if cached2:
                return JSONResponse(content=cached2[1], status_code=cached2[0])
            raise HTTPException(
                status_code=409, detail="Request in progress; retry with same Idempotency-Key"
            )
    stored_key: str | None = None
    try:
        stored_key, filename = file_svc.upload_raw(workspace_id, file)
        fw_list = [f.strip() for f in frameworks.split(",") if f.strip()] or ["Other"]
        sa_list = [s.strip() for s in subject_areas.split(",") if s.strip()] or ["Other"]
        doc = Document(
            workspace_id=workspace_id,
            storage_key=stored_key,
            filename=filename,
            content_type=file.content_type,
            frameworks_json=json.dumps(fw_list),
            subject_areas_json=json.dumps(sa_list),
            status="uploaded",
        )
        db.add(doc)
        db.flush()
        doc.display_id = build_display_id("document", doc.id)
        # TC-10-003: input_version pins the job to this upload's object; a stale job is superseded.
        # commit=False keeps the row and the job in this transaction (TC-10-003c).
        job, _created = enqueue_job(
            db,
            workspace_id=workspace_id,
            kind="index_document",
            payload={"document_id": doc.id},
            idempotency_key=job_idempotency_key(
                "index_document", workspace_id, doc.id, doc.storage_key
            ),
            input_version=doc.storage_key,
            commit=False,
        )
        result = {
            "id": doc.id,
            "display_id": doc.display_id,
            "filename": doc.filename,
            "status": doc.status,
            "storage_key": doc.storage_key,
            "job_id": job.id,
            "frameworks": fw_list,
            "subject_areas": sa_list,
        }
        if idem_key:
            idempotency_set(db, idem_key, 200, result, owner=idem_owner, commit=False)
        db.commit()
    except Exception:
        db.rollback()
        discard_if_unreferenced(db, file_svc._storage, file_svc._storage.bucket_raw, stored_key)
        _release_upload_claim(db, idem_key, idem_owner)
        raise
    audit_log(
        "document.upload",
        email=session.get("email"),
        workspace_id=workspace_id,
        resource_type="document",
        resource_id=result["id"],
        details={"filename": result["filename"]},
    )
    return result


_SEARCH_QUERY_MAX_LEN = 200
_PAGE_SIZE_DEFAULT = 25
_SORTS = {
    "created_at": Document.created_at,
    "filename": Document.filename,
    "status": Document.status,
    "id": Document.id,
}
_ORDERS = {"asc", "desc"}
_INDEX_JOB_STATUSES = frozenset(status.value for status in JobStatus)
_PREVIEW_MEDIA = {
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
}


def _list_paging(
    page: int | None, page_size: int | None, sort: str | None, order: str | None
) -> dict | None:
    """Return the page contract, or None when the caller asked for the legacy array."""
    if page is None and page_size is None and sort is None and order is None:
        return None
    if sort is not None and sort not in _SORTS:
        raise HTTPException(status_code=400, detail="Invalid sort")
    if order is not None and order not in _ORDERS:
        raise HTTPException(status_code=400, detail="Invalid order")
    return {
        "page": page or 1,
        "page_size": page_size or _PAGE_SIZE_DEFAULT,
        "sort": sort or "created_at",
        "order": order or "desc",
    }


def _list_ordering(sort_name: str, order_name: str):
    column = _SORTS[sort_name]
    primary = column.asc() if order_name == "asc" else column.desc()
    if sort_name == "id":
        return (primary,)
    tie = Document.id.asc() if order_name == "asc" else Document.id.desc()
    return (primary, tie)


def _payload_document_id(payload: str | None) -> int | None:
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("document_id")
    if type(value) is not int or not 0 < value <= 2147483647:
        return None
    return value


def _latest_index_jobs(db: Session, workspace_id: int, document_ids: list[int]) -> dict:
    """Newest valid index_document job per document. Stored payload text is not returned."""
    if not document_ids:
        return {}
    wanted = set(document_ids)
    rows = (
        db.query(Job.id, Job.status, Job.payload)
        .filter(Job.workspace_id == workspace_id, Job.kind == "index_document")
        .order_by(Job.id.desc())
        .all()
    )
    found: dict[int, tuple[int, str | None]] = {}
    for job_id, status, payload in rows:
        if len(found) == len(wanted):
            break
        document_id = _payload_document_id(payload)
        if document_id is None or document_id not in wanted or document_id in found:
            continue
        safe_status = status if status in _INDEX_JOB_STATUSES else None
        found[document_id] = (job_id, safe_status)
    return found


def _document_versions(db: Session, workspace_id: int, document_ids: list[int]) -> dict:
    if not document_ids:
        return {}
    rows = (
        db.query(EvidenceItem.document_id, func.max(EvidenceVersion.version_number))
        .join(EvidenceVersion, EvidenceVersion.evidence_id == EvidenceItem.id)
        .filter(
            EvidenceItem.workspace_id == workspace_id,
            EvidenceItem.document_id.in_(document_ids),
        )
        .group_by(EvidenceItem.document_id)
        .all()
    )
    versions = {}
    for document_id, number in rows:
        if document_id is None or number is None:
            continue
        versions[document_id] = str(int(number))
    return versions


def _freshness_label(created_at: datetime | None, policy: dict) -> str | None:
    """Same thresholds as the document freshness policy: fresh, warning, then stale."""
    if created_at is None:
        return None
    ref = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - ref).days
    max_age = int(policy["max_age_days"])
    warn_at = max_age - int(policy["warn_before_days"])
    if age_days >= max_age:
        return "stale"
    if age_days >= warn_at:
        return "warning"
    return "fresh"


def _source_preview_url(document: Document, workspace_id: int) -> str | None:
    key = document.storage_key or ""
    if not key or ".." in key or key.startswith("/") or "\0" in key or len(key) > 600:
        return None
    return f"/api/documents/{document.id}/content?workspace_id={workspace_id}"


def _preview_headers(filename: str | None) -> tuple[str, str]:
    safe = sanitize_filename(filename)
    ext = Path(safe).suffix.lower()
    media = _PREVIEW_MEDIA.get(ext, "application/octet-stream")
    disposition = "inline" if ext == ".pdf" else "attachment"
    return media, f'{disposition}; filename="{safe}"'


def stream_stored_document(document: Document, storage: StorageClient) -> StreamingResponse:
    """Stream one stored file the caller has already authorized.

    The storage key is not part of the response. Stored content types are not
    reflected; the media type comes from the filename extension.
    """
    if not document.storage_key:
        raise HTTPException(status_code=404, detail="Document not found")
    validate_storage_key(document.storage_key)
    try:
        stream = storage.download_stream(storage.bucket_raw, document.storage_key)
    except HTTPException:
        raise
    except Exception:
        logger.warning("document content unavailable document_id=%s", document.id)
        raise HTTPException(status_code=404, detail="Document file not found")
    media_type, disposition = _preview_headers(document.filename)
    return StreamingResponse(
        stream,
        media_type=media_type,
        headers={
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/")
@router.get("")
def list_documents(
    workspace_id: int,
    q: str | None = Query(None, description="Legacy filename search"),
    search: str | None = Query(
        None, description="Search by id, filename, framework, subject, status"
    ),
    framework: str | None = Query(None, description="Filter by framework chip label"),
    subject_area: str | None = Query(None, description="Filter by subject area chip label"),
    status: str | None = Query(None, description="Filter by status"),
    created_from: str | None = Query(None, description="Created-at lower bound ISO"),
    created_to: str | None = Query(None, description="Created-at upper bound ISO"),
    archived: str | None = Query(None, description="active|include|only"),
    tag_category: str | None = Query(None, description="Legacy tag category filter"),
    tag_key: str | None = Query(None, description="Legacy tag key filter"),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=100),
    sort: str | None = Query(None, description="created_at, filename, status, or id"),
    order: str | None = Query(None, description="asc or desc"),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """List documents for workspace.

    With no page, page_size, sort, or order, the body stays a JSON array of every
    match, newest first. Those parameters return one page, the total, and the
    configured upload limit. Accepts a trailing slash.
    """
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

        query = query.join(DocumentTag, DocumentTag.document_id == Document.id).join(
            Tag, DocumentTag.tag_id == Tag.id
        )
        if tag_category:
            query = query.filter(Tag.category == tag_category)
        if tag_key:
            query = query.filter(Tag.key == tag_key)
        query = query.distinct()

    paging = _list_paging(page, page_size, sort, order)
    sort_name = paging["sort"] if paging else "created_at"
    order_name = paging["order"] if paging else "desc"
    ordered = query.order_by(*_list_ordering(sort_name, order_name))
    if paging:
        total = query.count()
        offset = (paging["page"] - 1) * paging["page_size"]
        docs = ordered.offset(offset).limit(paging["page_size"]).all()
    else:
        total = None
        docs = ordered.all()
    doc_ids = [d.id for d in docs]
    tags_map = list_tags_for_documents(db, doc_ids, workspace_id) if doc_ids else {}
    jobs = _latest_index_jobs(db, workspace_id, doc_ids)
    versions = _document_versions(db, workspace_id, doc_ids)
    policy = get_effective_policy(db, workspace_id, "document")
    items = []
    for d in docs:
        job = jobs.get(d.id)
        items.append(
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
                        [
                            t["label"]
                            for t in tags_map.get(d.id, [])
                            if t.get("category") == "framework"
                        ]
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
                "source_eligibility": "ineligible" if d.deleted_at is not None else "eligible",
                "freshness": _freshness_label(d.created_at, policy),
                "version": versions.get(d.id),
                "index_job_id": job[0] if job else None,
                "index_job_status": job[1] if job else None,
                "source_preview_url": _source_preview_url(d, workspace_id),
            }
        )
    if not paging:
        return items
    return {
        "items": items,
        "total": total,
        "page": paging["page"],
        "page_size": paging["page_size"],
        "sort": sort_name,
        "order": order_name,
        "max_upload_bytes": get_settings().max_upload_bytes,
    }


@router.get("/{document_id}/content")
def document_content(
    document_id: int,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
    storage: StorageClient = Depends(get_storage),
):
    """Stream the stored file for a reviewer in this workspace.

    The media type comes from the filename extension. Stored content types are
    not reflected. The storage key is not part of the URL or the error text.
    A share token is not accepted on this route.
    """
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    doc = (
        db.query(Document)
        .filter(Document.id == document_id, Document.workspace_id == workspace_id)
        .first()
    )
    if not doc or not doc.storage_key:
        raise HTTPException(status_code=404, detail="Document not found")
    return stream_stored_document(doc, storage)


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
    if docs:
        invalidate_after_document_visibility_change(db, workspace_id)
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
    invalidate_after_document_visibility_change(db, workspace_id)
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
        .filter(
            Document.id == document_id,
            Document.workspace_id == workspace_id,
            Document.deleted_at.is_not(None),
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Archived document not found")
    restore_record(doc)
    db.commit()
    invalidate_after_document_visibility_change(db, workspace_id)
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
        details={
            "display_id": doc.display_id,
            "frameworks": body.frameworks,
            "subject_areas": body.subject_areas,
        },
    )
    return {"ok": True}
