"""Trust requests API (TC-04)."""

import logging
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.schemas import BulkDeleteBody, MetadataUpdateBody
from app.core.auth_deps import require_can_review
from app.core.audit import audit_log, persist_audit  # noqa: F401
from app.core.database import get_db
from app.models import TrustRequest, TrustRequestNote, User, Workspace, WorkspaceMember
from app.models.trust_request_note import NOTE_TYPE_INTERNAL, NOTE_TYPE_REPLY
from app.services import trust_request_service as trust_svc
from app.services.file_service import ALLOWED_RAW_EXTENSIONS, sanitize_filename
from pathlib import Path
import hashlib
from app.core.config import get_settings
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/trust-requests", tags=["trust-requests"])


def require_current_reviewer(
    session: dict = Depends(require_can_review), db: Session = Depends(get_db)
) -> dict:
    trust_svc.require_current_reviewer(db, session)
    return session


TRUST_REQUEST_STATUSES = {"new", "in_progress", "pending_review", "completed"}


class TrustRequestCreate(BaseModel):
    requester_email: str = Field(max_length=255)
    requester_name: str | None = Field(default=None, max_length=255)
    subject: str | None = Field(default=None, max_length=255)
    message: str = Field(min_length=1, max_length=10000)
    workspace_id: int | None = Field(default=None, gt=0)
    workspace_slug: str | None = Field(default=None, max_length=64)

    @field_validator("requester_email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return trust_svc.validate_mailbox(value)

    @field_validator("requester_name", "subject", "message", "workspace_slug")
    @classmethod
    def validate_text_fields(cls, value: str | None) -> str | None:
        return trust_svc.validate_text(value)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message is required")
        return value.strip()


class TrustRequestUpdate(BaseModel):
    status: str | None = None
    assignee_id: int | None = None


# ---------------------------------------------------------------------------
# Workspace resolver for public trust submissions
# ---------------------------------------------------------------------------


def resolve_workspace_for_trust_request(
    db: Session,
    *,
    workspace_id: int | None = None,
    workspace_slug: str | None = None,
    submitted_host: str | None = None,
    submitted_path: str | None = None,
) -> tuple[int, str]:
    """Resolve the target workspace for a public trust submission.

    Returns (workspace_id, resolution_method).
    Raises HTTPException if resolution fails.

    Resolution order:
      1. Explicit workspace_slug (primary path for /trust/[slug])
      2. Explicit workspace_id (internal/dev compatibility)
      3. In non-production only: default workspace (id=1)
      4. Otherwise fail clearly
    """
    if workspace_slug:
        slug = workspace_slug.strip().lower()
        ws = db.query(Workspace).filter(func.lower(Workspace.slug) == slug).first()
        if ws:
            return ws.id, "slug"
        raise HTTPException(status_code=404, detail=f"No workspace with slug '{slug}'")

    if workspace_id is not None:
        ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return ws.id, "explicit_id"

    from app.core.config import get_settings
    from app.core.session import is_production_env

    if is_production_env({"APP_ENV": get_settings().app_env}):
        raise HTTPException(
            status_code=400,
            detail="Workspace slug is required for public trust submissions",
        )

    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    if ws:
        logger.warning("trust_request using default workspace fallback (dev only)")
        return ws.id, "default_dev"

    raise HTTPException(status_code=500, detail="No workspace available for trust request routing")


def _to_dict(r: TrustRequest, db: Session | None = None) -> dict:
    out = {
        "id": r.id,
        "workspace_id": r.workspace_id,
        "assignee_id": r.assignee_id,
        "requester_email": r.requester_email,
        "requester_name": r.requester_name,
        "subject": r.subject,
        "message": r.message,
        "display_id": r.display_id or build_display_id("trust_request", r.id),
        "frameworks": normalize_labels(
            parse_json_list(r.frameworks_json), allowed=FRAMEWORK_LABELS
        ),
        "subject_areas": normalize_labels(
            parse_json_list(r.subject_areas_json), allowed=SUBJECT_AREA_LABELS
        ),
        "status": r.status,
        "attachment_filename": r.attachment_filename,
        "attachment_storage_key": r.attachment_storage_key,
        "attachment_size": getattr(r, "attachment_size", None),
        "submitted_host": getattr(r, "submitted_host", None),
        "submitted_path": getattr(r, "submitted_path", None),
        "resolution_method": getattr(r, "resolution_method", None),
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "deleted_at": r.deleted_at.isoformat() if r.deleted_at else None,
    }
    if db and r.assignee_id:
        assignee = db.query(User).filter(User.id == r.assignee_id).first()
        if assignee:
            out["assignee_email"] = assignee.email
            out["assignee_display_name"] = getattr(assignee, "display_name", None) or assignee.email
    return out


def _persist_intake(
    body: TrustRequestCreate,
    request: Request,
    db: Session,
    client_key: str | None,
    document: UploadFile | None = None,
    storage: StorageClient | None = None,
):
    host = request.headers.get("host") or ""
    path = request.headers.get("x-trust-path") or ""
    ws_id, method = resolve_workspace_for_trust_request(
        db,
        workspace_id=body.workspace_id,
        workspace_slug=body.workspace_slug,
        submitted_host=host,
        submitted_path=path,
    )
    file_hash = None
    content = None
    filename = None
    if document and document.filename and document.file:
        filename = sanitize_filename(document.filename)
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_RAW_EXTENSIONS:
            raise HTTPException(400, "File type is not supported.")
        content = document.file.read(get_settings().max_upload_bytes + 1)
        document.file.seek(0)
        if len(content) > get_settings().max_upload_bytes:
            raise HTTPException(413, "File is too large.")
        file_hash = hashlib.sha256(content).hexdigest()
    digest = trust_svc.fingerprint(
        {
            **body.model_dump(),
            "attachment_hash": file_hash,
            "attachment_name": document.filename if file_hash else None,
        }
    )
    key, owner, cached = trust_svc.begin_intake(db, ws_id, client_key, digest)
    if cached is not None:
        return cached
    uploaded_key = None
    try:
        req = TrustRequest(
            workspace_id=ws_id,
            requester_email=body.requester_email,
            requester_name=body.requester_name,
            subject=body.subject,
            message=body.message,
            frameworks_json=json.dumps(["Other"]),
            subject_areas_json=json.dumps(["Other"]),
            status="new",
            intake_version=1,
            submitted_host=host[:255] or None,
            submitted_path=path[:255] or None,
            resolution_method=method,
        )
        db.add(req)
        db.flush()
        req.display_id = build_display_id("trust_request", req.id)
        if file_hash is not None:
            # Own the key before the network call: an upload may write then time out.
            uploaded_key = f"trust-requests/{ws_id}/{req.id}/{uuid4().hex}{ext}"
            storage.upload(
                storage.bucket_raw, uploaded_key, content, content_type=document.content_type
            )
            req.attachment_filename, req.attachment_storage_key, req.attachment_size = (
                filename,
                uploaded_key,
                len(content),
            )
        response = _to_dict(req, db)
        trust_svc.finish_intake(db, key, owner, digest, response)
        return response
    except Exception as exc:
        if isinstance(exc, trust_svc.IntakeCommitUncertain):
            # Never delete a possibly committed attachment or a completed retry response.
            # Without a reliable fresh database read, retain both for replay/reconciliation.
            try:
                db.rollback()
            except Exception:
                logger.error("trust intake database cleanup requires reconciliation")
            logger.error(
                "trust intake save outcome requires reconciliation request_id=%s storage_key=%s",
                response["id"],
                uploaded_key,
            )
            raise HTTPException(
                502,
                "The save outcome could not be confirmed. Retry using the same request key if supplied.",
            ) from None
        abort_failed = False
        try:
            trust_svc.abort_intake(db, key, owner)
        except Exception:
            abort_failed = True
            logger.error("trust intake database cleanup requires reconciliation")
        if uploaded_key and storage:
            try:
                storage.delete(storage.bucket_raw, uploaded_key)
            except Exception:
                logger.error(
                    "trust attachment cleanup requires reconciliation storage_key=%s",
                    uploaded_key,
                )
        if isinstance(exc, HTTPException) and not abort_failed:
            raise
        if isinstance(exc, trust_svc.idempotency.IdempotencyClaimLost) and not abort_failed:
            raise HTTPException(409, "This request lost its retry lease. Please retry.") from None
        logger.error("trust intake persistence failed (%s)", type(exc).__name__)
        raise HTTPException(502, "The request could not be saved. Please retry.") from None


@router.post("/")
def create_trust_request(
    body: TrustRequestCreate,
    request: Request,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    """Submit a bounded trust information request."""
    return _persist_intake(body, request, db, idempotency_key)


@router.post("/submit")
def submit_trust_request_with_attachment(
    request: Request,
    requester_email: str = Form(...),
    requester_name: str | None = Form(None),
    subject: str | None = Form(None),
    message: str = Form(...),
    workspace_id: int | None = Form(None),
    workspace_slug: str | None = Form(None),
    document: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    storage: StorageClient = Depends(get_storage),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    """Submit a trust request with one permitted, bounded attachment."""
    try:
        body = TrustRequestCreate(
            requester_email=requester_email,
            requester_name=requester_name,
            subject=subject,
            message=message,
            workspace_id=workspace_id,
            workspace_slug=workspace_slug,
        )
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from None
    return _persist_intake(body, request, db, idempotency_key, document, storage)


# ---------------------------------------------------------------------------
# Attachment download
# ---------------------------------------------------------------------------


@router.get("/{request_id}/attachment")
def download_trust_request_attachment(
    request_id: int,
    session: dict = Depends(require_current_reviewer),
    db: Session = Depends(get_db),
    storage: StorageClient = Depends(get_storage),
):
    """Download the attachment for a trust request. Requires auth."""
    req = (
        db.query(TrustRequest)
        .filter(
            TrustRequest.id == request_id,
            TrustRequest.workspace_id == session.get("workspace_id"),
            TrustRequest.deleted_at.is_(None),
        )
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Trust request not found")
    if not req.attachment_storage_key:
        raise HTTPException(status_code=404, detail="No attachment on this trust request")

    try:
        stream = storage.download_stream(storage.bucket_raw, req.attachment_storage_key)
    except Exception:
        raise HTTPException(status_code=404, detail="Attachment file not found in storage")

    filename = req.attachment_filename or "attachment"
    return StreamingResponse(
        stream,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Authenticated endpoints
# ---------------------------------------------------------------------------


@router.get("/summary")
def get_trust_requests_summary(
    session: dict = Depends(require_current_reviewer),
    db: Session = Depends(get_db),
):
    """Return counts by status and completed_this_month. Same auth as list."""
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(status_code=403, detail="Workspace required.")
    by_status = {}
    for s in TRUST_REQUEST_STATUSES:
        by_status[s] = (
            db.query(TrustRequest)
            .filter(
                TrustRequest.workspace_id == ws,
                TrustRequest.status == s,
                TrustRequest.deleted_at.is_(None),
            )
            .count()
        )
    now = datetime.now(timezone.utc)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    completed_this_month = (
        db.query(TrustRequest)
        .filter(
            TrustRequest.workspace_id == ws,
            TrustRequest.status == "completed",
            TrustRequest.deleted_at.is_(None),
            TrustRequest.created_at >= start_of_month,
        )
        .count()
    )
    return {
        "new": by_status.get("new", 0),
        "in_progress": by_status.get("in_progress", 0),
        "pending_review": by_status.get("pending_review", 0),
        "completed": by_status.get("completed", 0),
        "completed_this_month": completed_this_month,
    }


@router.get("/")
@router.get("")
def list_trust_requests(
    workspace_id: int | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None),
    framework: str | None = Query(None),
    subject_area: str | None = Query(None),
    created_from: str | None = Query(None),
    created_to: str | None = Query(None),
    archived: str | None = Query(None, description="active|include|only"),
    session: dict = Depends(require_current_reviewer),
    db: Session = Depends(get_db),
):
    """List trust requests. Requires auth (internal viewing). Scoped to session workspace only."""
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(
            status_code=403, detail="Workspace required. Use a session with workspace."
        )
    if workspace_id is not None and workspace_id != ws:
        raise HTTPException(
            status_code=403, detail="Cannot list trust requests for another workspace."
        )
    q = db.query(TrustRequest).filter(TrustRequest.workspace_id == ws)
    mode = (archived or "active").strip().lower()
    if mode == "active":
        q = q.filter(TrustRequest.deleted_at.is_(None))
    elif mode == "only":
        q = q.filter(TrustRequest.deleted_at.is_not(None))
    if status:
        if status not in TRUST_REQUEST_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Allowed: {sorted(TRUST_REQUEST_STATUSES)}",
            )
        q = q.filter(TrustRequest.status == status)
    if search and (search_strip := search.strip()[:200]):
        like = f"%{search_strip}%"
        q = q.filter(
            TrustRequest.display_id.ilike(like)
            | TrustRequest.requester_email.ilike(like)
            | TrustRequest.requester_name.ilike(like)
            | TrustRequest.subject.ilike(like)
            | TrustRequest.status.ilike(like)
            | TrustRequest.frameworks_json.ilike(like)
            | TrustRequest.subject_areas_json.ilike(like)
        )
    if framework:
        q = q.filter(TrustRequest.frameworks_json.ilike(f"%{framework.strip()}%"))
    if subject_area:
        q = q.filter(TrustRequest.subject_areas_json.ilike(f"%{subject_area.strip()}%"))
    if created_from:
        try:
            q = q.filter(TrustRequest.created_at >= datetime.fromisoformat(created_from))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid created_from datetime")
    if created_to:
        try:
            q = q.filter(TrustRequest.created_at <= datetime.fromisoformat(created_to))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid created_to datetime")
    rows = q.order_by(TrustRequest.created_at.desc(), TrustRequest.id.desc()).all()
    return [_to_dict(r, db) for r in rows]


@router.get("/{request_id}")
def get_trust_request(
    request_id: int,
    session: dict = Depends(require_current_reviewer),
    db: Session = Depends(get_db),
):
    """Get a single trust request. Requires auth."""
    req = (
        db.query(TrustRequest)
        .filter(
            TrustRequest.id == request_id,
            TrustRequest.workspace_id == session.get("workspace_id"),
            TrustRequest.deleted_at.is_(None),
        )
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Trust request not found")
    return _to_dict(req, db)


@router.patch("/{request_id}")
def update_trust_request(
    request_id: int,
    body: TrustRequestUpdate,
    session: dict = Depends(require_current_reviewer),
    db: Session = Depends(get_db),
):
    """Update trust request status and/or assignee. Requires auth."""
    req = (
        db.query(TrustRequest)
        .filter(
            TrustRequest.id == request_id,
            TrustRequest.workspace_id == session.get("workspace_id"),
            TrustRequest.deleted_at.is_(None),
        )
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Trust request not found")

    old_status = req.status
    old_assignee_id = req.assignee_id

    if body.status is not None:
        if body.status not in TRUST_REQUEST_STATUSES:
            raise HTTPException(
                status_code=400, detail=f"Invalid status. Allowed: {sorted(TRUST_REQUEST_STATUSES)}"
            )
    if body.assignee_id is not None:
        new_assignee = body.assignee_id if body.assignee_id else None
        if new_assignee is not None and req.workspace_id is not None:
            member = (
                db.query(WorkspaceMember)
                .filter(
                    WorkspaceMember.workspace_id == req.workspace_id,
                    WorkspaceMember.user_id == new_assignee,
                    WorkspaceMember.suspended.is_(False),
                )
                .first()
            )
            if not member:
                raise HTTPException(
                    status_code=400,
                    detail="Assignee must be a member of the request's workspace.",
                )
        req.assignee_id = new_assignee
    if body.status is not None:
        if body.status == "completed":
            delivered = (
                db.query(TrustRequestNote.id)
                .filter(
                    TrustRequestNote.trust_request_id == req.id,
                    TrustRequestNote.delivery_status == "accepted",
                    TrustRequestNote.approved_revision == TrustRequestNote.body_revision,
                    TrustRequestNote.approved_at.is_not(None),
                    TrustRequestNote.approved_by.is_not(None),
                    TrustRequestNote.delivery_accepted_at.is_not(None),
                )
                .first()
            )
            if delivered is None:
                db.rollback()
                raise HTTPException(
                    409, "An approved reply must be accepted for delivery before completion."
                )
        req.status = body.status

    db.commit()
    db.refresh(req)

    details = {}
    if old_status != req.status:
        details["old_status"] = old_status
        details["new_status"] = req.status
    if old_assignee_id != req.assignee_id:
        details["old_assignee_id"] = old_assignee_id
        details["new_assignee_id"] = req.assignee_id
    if not details:
        details["status"] = req.status
        details["assignee_id"] = req.assignee_id

    persist_audit(
        db,
        "trust_request.update",
        user_id=session.get("user_id"),
        email=session.get("email"),
        workspace_id=req.workspace_id,
        resource_type="trust_request",
        resource_id=req.id,
        details=details,
    )
    return _to_dict(req, db)


@router.post("/bulk-delete")
def bulk_delete_trust_requests(
    body: BulkDeleteBody,
    workspace_id: int = Query(...),
    session: dict = Depends(require_current_reviewer),
    db: Session = Depends(get_db),
):
    """Bulk soft-delete trust requests."""
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if not body.ids:
        return {"deleted": 0, "errors": []}
    reqs = (
        db.query(TrustRequest)
        .filter(
            TrustRequest.id.in_(body.ids),
            TrustRequest.workspace_id == workspace_id,
            TrustRequest.deleted_at.is_(None),
        )
        .all()
    )
    for req in reqs:
        soft_delete_record(req, session.get("user_id"))
        persist_audit(
            db,
            "trust_request.soft_delete",
            user_id=session.get("user_id"),
            email=session.get("email"),
            workspace_id=req.workspace_id,
            resource_type="trust_request",
            resource_id=req.id,
            details={"display_id": req.display_id},
        )
    db.commit()
    return {"deleted": len(reqs), "errors": []}


@router.delete("/{request_id}")
def delete_trust_request(
    request_id: int,
    workspace_id: int = Query(...),
    session: dict = Depends(require_current_reviewer),
    db: Session = Depends(get_db),
):
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    req = (
        db.query(TrustRequest)
        .filter(
            TrustRequest.id == request_id,
            TrustRequest.workspace_id == workspace_id,
            TrustRequest.deleted_at.is_(None),
        )
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Trust request not found")

    preview = build_delete_preview("trust_request", db, workspace_id, request_id)
    soft_delete_record(req, session.get("user_id"))
    db.commit()
    persist_audit(
        db,
        "trust_request.soft_delete",
        user_id=session.get("user_id"),
        email=session.get("email"),
        workspace_id=req.workspace_id,
        resource_type="trust_request",
        resource_id=req.id,
        details={"display_id": req.display_id, "dependencies": preview.dependencies},
    )
    return {
        "ok": True,
        "id": req.id,
        "display_id": req.display_id or build_display_id("trust_request", req.id),
        "dependencies": preview.dependencies,
    }


@router.get("/{request_id}/delete-preview")
def delete_preview_trust_request(
    request_id: int,
    workspace_id: int = Query(...),
    session: dict = Depends(require_current_reviewer),
    db: Session = Depends(get_db),
):
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    req = (
        db.query(TrustRequest)
        .filter(TrustRequest.id == request_id, TrustRequest.workspace_id == workspace_id)
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Trust request not found")
    preview = build_delete_preview("trust_request", db, workspace_id, request_id)
    return {
        "id": req.id,
        "display_id": req.display_id or preview.display_id,
        "can_delete": preview.can_delete,
        "recommended_action": preview.recommended_action,
        "warnings": preview.warnings,
        "dependencies": preview.dependencies,
        "unmodeled_warning": preview.unmodeled_warning,
    }


@router.post("/{request_id}/restore")
def restore_trust_request(
    request_id: int,
    workspace_id: int = Query(...),
    session: dict = Depends(require_current_reviewer),
    db: Session = Depends(get_db),
):
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    req = (
        db.query(TrustRequest)
        .filter(
            TrustRequest.id == request_id,
            TrustRequest.workspace_id == workspace_id,
            TrustRequest.deleted_at.is_not(None),
        )
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Archived trust request not found")
    restore_record(req)
    db.commit()
    persist_audit(
        db,
        "trust_request.restore",
        user_id=session.get("user_id"),
        email=session.get("email"),
        workspace_id=workspace_id,
        resource_type="trust_request",
        resource_id=req.id,
        details={"display_id": req.display_id},
    )
    return {"ok": True, "id": req.id, "display_id": req.display_id}


@router.patch("/{request_id}/metadata")
def update_trust_request_metadata(
    request_id: int,
    body: MetadataUpdateBody,
    workspace_id: int = Query(...),
    session: dict = Depends(require_current_reviewer),
    db: Session = Depends(get_db),
):
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    req = (
        db.query(TrustRequest)
        .filter(
            TrustRequest.id == request_id,
            TrustRequest.workspace_id == workspace_id,
        )
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Trust request not found")
    update_metadata_json_fields(req, body.frameworks, body.subject_areas)
    db.commit()
    persist_audit(
        db,
        "trust_request.metadata_update",
        user_id=session.get("user_id"),
        email=session.get("email"),
        workspace_id=workspace_id,
        resource_type="trust_request",
        resource_id=req.id,
        details={
            "display_id": req.display_id,
            "frameworks": body.frameworks,
            "subject_areas": body.subject_areas,
        },
    )
    return {"ok": True}


class TrustRequestNoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        trust_svc.validate_text(value)
        if not value.strip():
            raise ValueError("Body is required")
        return value.strip()


class TrustRequestReplyCreate(TrustRequestNoteCreate):
    send_email: bool = False


class ReplyRevision(BaseModel):
    revision: int = Field(ge=1, le=1000000)


class ReplyEdit(TrustRequestNoteCreate):
    revision: int = Field(ge=0, le=999999)


def _note_to_dict(n: TrustRequestNote, db: Session) -> dict:
    out = {
        "id": n.id,
        "trust_request_id": n.trust_request_id,
        "author_id": n.author_id,
        "note_type": getattr(n, "note_type", None) or NOTE_TYPE_INTERNAL,
        "body": n.body,
        "body_revision": n.body_revision,
        "approved_revision": n.approved_revision,
        "approved_by": n.approved_by,
        "approved_at": n.approved_at.isoformat() if n.approved_at else None,
        "delivery_status": n.delivery_status,
        "delivery_attempts": n.delivery_attempts,
        "delivery_started_at": n.delivery_started_at.isoformat() if n.delivery_started_at else None,
        "delivery_accepted_at": n.delivery_accepted_at.isoformat()
        if n.delivery_accepted_at
        else None,
        "delivery_error": n.delivery_error,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }
    if n.author_id:
        author = db.query(User).filter(User.id == n.author_id).first()
        if author:
            out["author_email"] = author.email
            out["author_display_name"] = getattr(author, "display_name", None) or author.email
    return out


@router.get("/{request_id}/notes")
def list_trust_request_notes(
    request_id: int,
    session: dict = Depends(require_current_reviewer),
    db: Session = Depends(get_db),
):
    """List notes and replies for a trust request. Requires auth."""
    req = (
        db.query(TrustRequest)
        .filter(
            TrustRequest.id == request_id,
            TrustRequest.workspace_id == session.get("workspace_id"),
            TrustRequest.deleted_at.is_(None),
        )
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Trust request not found")
    notes = (
        db.query(TrustRequestNote)
        .filter(TrustRequestNote.trust_request_id == request_id)
        .order_by(TrustRequestNote.created_at.asc())
        .all()
    )
    return [_note_to_dict(n, db) for n in notes]


@router.post("/{request_id}/notes")
def create_trust_request_note(
    request_id: int,
    body: TrustRequestNoteCreate,
    session: dict = Depends(require_current_reviewer),
    db: Session = Depends(get_db),
):
    """Add an internal note to a trust request. Requires auth."""
    req = (
        db.query(TrustRequest)
        .filter(
            TrustRequest.id == request_id,
            TrustRequest.workspace_id == session.get("workspace_id"),
            TrustRequest.deleted_at.is_(None),
        )
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Trust request not found")
    body_text = (body.body or "").strip()
    if not body_text:
        raise HTTPException(status_code=400, detail="Body is required")
    note = TrustRequestNote(
        trust_request_id=request_id,
        author_id=session.get("user_id"),
        note_type=NOTE_TYPE_INTERNAL,
        body=body_text,
        body_revision=1,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    persist_audit(
        db,
        "trust_request.note_added",
        user_id=session.get("user_id"),
        email=session.get("email"),
        workspace_id=req.workspace_id,
        resource_type="trust_request_note",
        resource_id=note.id,
        details={
            "trust_request_id": request_id,
            "author_id": note.author_id,
            "note_type": NOTE_TYPE_INTERNAL,
        },
    )
    return _note_to_dict(note, db)


@router.post("/{request_id}/replies")
def create_trust_request_reply(
    request_id: int,
    body: TrustRequestReplyCreate,
    session: dict = Depends(require_current_reviewer),
    db: Session = Depends(get_db),
):
    """Create a reply draft for explicit review before delivery."""
    req = (
        db.query(TrustRequest)
        .filter(
            TrustRequest.id == request_id,
            TrustRequest.workspace_id == session.get("workspace_id"),
            TrustRequest.deleted_at.is_(None),
        )
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Trust request not found")
    if body.send_email:
        raise HTTPException(409, "Create and approve the reply before sending it.")
    note = TrustRequestNote(
        trust_request_id=request_id,
        author_id=session.get("user_id"),
        note_type=NOTE_TYPE_REPLY,
        body=body.body,
        body_revision=1,
        delivery_status="draft",
        delivery_attempts=0,
    )
    db.add(note)
    db.flush()
    trust_svc.add_audit(db, "trust_request.reply_added", req, note, session)
    db.commit()
    db.refresh(note)
    return _note_to_dict(note, db)


@router.patch("/{request_id}/replies/{note_id}")
def edit_trust_reply(
    request_id: int,
    note_id: int,
    body: ReplyEdit,
    session: dict = Depends(require_current_reviewer),
    db: Session = Depends(get_db),
):
    """Edit an unsent reply and invalidate approval of its previous revision."""
    note = trust_svc.edit_reply(
        db, session.get("workspace_id"), request_id, note_id, body.revision, body.body, session
    )
    return _note_to_dict(note, db)


@router.post("/{request_id}/replies/{note_id}/approve")
def approve_trust_reply(
    request_id: int,
    note_id: int,
    body: ReplyRevision,
    session: dict = Depends(require_current_reviewer),
    db: Session = Depends(get_db),
):
    """Approve the exact reply revision as a signed-in workspace member."""
    note = trust_svc.approve_reply(
        db, session.get("workspace_id"), request_id, note_id, body.revision, session
    )
    return _note_to_dict(note, db)


@router.post("/{request_id}/replies/{note_id}/send")
def send_trust_reply(
    request_id: int,
    note_id: int,
    body: ReplyRevision,
    session: dict = Depends(require_current_reviewer),
    db: Session = Depends(get_db),
):
    """Send an approved reply once and report provider acceptance or uncertainty."""
    note = trust_svc.send_reply(
        db, session.get("workspace_id"), request_id, note_id, body.revision, session
    )
    return _note_to_dict(note, db)


@router.post("/{request_id}/suggest-reply")
def suggest_reply(
    request_id: int,
    session: dict = Depends(require_current_reviewer),
    db: Session = Depends(get_db),
):
    """Generate a suggested reply draft for this trust request (AI). Requires auth."""
    if request_id < 1:
        raise HTTPException(status_code=400, detail="request_id must be a positive integer")
    req = (
        db.query(TrustRequest)
        .filter(
            TrustRequest.id == request_id,
            TrustRequest.workspace_id == session.get("workspace_id"),
            TrustRequest.deleted_at.is_(None),
        )
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Trust request not found")
    from app.services.trust_request_draft import suggest_reply_draft

    try:
        draft = suggest_reply_draft(req.requester_email, req.subject, req.message)
    except Exception as e:
        logging.getLogger(__name__).exception("suggest_reply: %s", e)
        raise HTTPException(
            status_code=503,
            detail="AI suggestion failed. Check OPENAI_API_KEY and try again.",
        ) from e

    if not (draft and draft.strip()):
        raise HTTPException(
            status_code=503,
            detail="Could not generate a suggestion. Set OPENAI_API_KEY in the API environment and try again.",
        )
    text = draft.strip()
    return {"draft": text, "reply": text}
