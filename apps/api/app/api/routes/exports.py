"""Exports API (EXP-07). Thin routes; job enqueue logic in export_service."""

import logging
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from sqlalchemy import func

from app.core.auth_deps import require_can_export, require_can_review
from app.core.config import get_settings
from app.core.database import get_db
from app.core.idempotency import get as idempotency_get, set as idempotency_set, try_claim as idempotency_try_claim
from app.models import ExportRecord, Question, Questionnaire
from app.services.export_service import enqueue_export_job, enqueue_generate_answers_job
from app.services.storage import get_storage, StorageClient

router = APIRouter(prefix="/exports", tags=["exports"])
_log = logging.getLogger(__name__)


class GenerateAnswersBody(BaseModel):
    """Optional overrides for answer generation (AI-02, AI-05, AI-06)."""
    model: str | None = None
    response_style: str | None = None


@router.post("/generate/{questionnaire_id}")
def trigger_generate(
    request: Request,
    questionnaire_id: int,
    workspace_id: int = Query(...),
    body: GenerateAnswersBody | None = Body(None),
    session: dict = Depends(require_can_export),
    db: Session = Depends(get_db),
):
    """Enqueue generate_answers job. Optional body: model, response_style (AI-06). Supports Idempotency-Key header."""
    idem_key = (request.headers.get("Idempotency-Key") or "").strip()
    if idem_key:
        cached = idempotency_get(db, idem_key)
        if cached:
            return JSONResponse(content=cached[1], status_code=cached[0])
        if not idempotency_try_claim(db, idem_key):
            cached2 = idempotency_get(db, idem_key)
            if cached2:
                return JSONResponse(content=cached2[1], status_code=cached2[0])
            raise HTTPException(status_code=409, detail="Request in progress; retry with same Idempotency-Key")
    if session.get("workspace_id") != workspace_id:
        if idem_key:
            idempotency_set(db, idem_key, 403, {"detail": "Access denied"})
        raise HTTPException(status_code=403, detail="Access denied")
    n_questions = (
        db.query(func.count(Question.id))
        .join(Questionnaire, Questionnaire.id == Question.questionnaire_id)
        .filter(
            Question.questionnaire_id == questionnaire_id,
            Questionnaire.workspace_id == workspace_id,
        )
        .scalar()
        or 0
    )
    _log.info(
        "GENERATE_ANSWERS: request received questionnaire_id=%s workspace_id=%s questions=%s",
        questionnaire_id,
        workspace_id,
        n_questions,
    )
    if n_questions > 0 and not (get_settings().openai_api_key or "").strip():
        detail = (
            "OpenAI API key is not configured. Set OPENAI_API_KEY in your environment (.env) "
            "for the API and worker services, then restart."
        )
        if idem_key:
            idempotency_set(db, idem_key, 503, {"detail": detail})
        raise HTTPException(status_code=503, detail=detail)
    from app.services.quota_service import check_quota
    allowed, current, limit = check_quota(db, workspace_id, "ai_jobs")
    if not allowed:
        raise HTTPException(status_code=429, detail=f"AI job quota exceeded ({current}/{limit} per hour)")
    try:
        job = enqueue_generate_answers_job(
            db,
            workspace_id,
            questionnaire_id,
            model_override=body.model if body else None,
            response_style_override=body.response_style if body else None,
        )
    except ValueError as e:
        msg = str(e)
        if idem_key:
            sc = 404 if "not found" in msg.lower() else 400
            idempotency_set(db, idem_key, sc, {"detail": msg})
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail="Questionnaire not found")
        raise HTTPException(status_code=400, detail=msg)
    from app.core.audit import audit_log
    audit_log("export.generate", email=session.get("email"), workspace_id=workspace_id, resource_type="questionnaire", resource_id=questionnaire_id, details={"job_id": job.id})
    _log.info("GENERATE_ANSWERS: job created job_id=%s questionnaire_id=%s questions=%s", job.id, questionnaire_id, n_questions)
    result = {"job_id": job.id, "status": "queued"}
    if idem_key:
        idempotency_set(db, idem_key, 200, result)
    return result


class ExportBody(BaseModel):
    """Optional format override for export (xlsx or docx)."""
    format: str | None = None


@router.post("/export/{questionnaire_id}")
def trigger_export(
    request: Request,
    questionnaire_id: int,
    workspace_id: int = Query(...),
    body: ExportBody | None = Body(None),
    session: dict = Depends(require_can_export),
    db: Session = Depends(get_db),
):
    """Enqueue export job (EXP-07). Optional body: format (xlsx or docx). Supports Idempotency-Key header."""
    idem_key = (request.headers.get("Idempotency-Key") or "").strip()
    if idem_key:
        cached = idempotency_get(db, idem_key)
        if cached:
            return JSONResponse(content=cached[1], status_code=cached[0])
        if not idempotency_try_claim(db, idem_key):
            cached2 = idempotency_get(db, idem_key)
            if cached2:
                return JSONResponse(content=cached2[1], status_code=cached2[0])
            raise HTTPException(status_code=409, detail="Request in progress; retry with same Idempotency-Key")
    if session.get("workspace_id") != workspace_id:
        if idem_key:
            idempotency_set(db, idem_key, 403, {"detail": "Access denied"})
        raise HTTPException(status_code=403, detail="Access denied")
    from app.services.quota_service import check_quota
    allowed, current, limit = check_quota(db, workspace_id, "exports")
    if not allowed:
        raise HTTPException(status_code=429, detail=f"Export quota exceeded ({current}/{limit} per hour)")
    fmt = (body.format or "xlsx").lower() if body else "xlsx"
    try:
        job = enqueue_export_job(db, workspace_id, questionnaire_id, format=fmt)
    except ValueError as e:
        msg = str(e)
        if idem_key:
            sc = 404 if "not found" in msg.lower() else 400
            idempotency_set(db, idem_key, sc, {"detail": msg})
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail="Questionnaire not found")
        raise HTTPException(status_code=400, detail=msg)
    from app.core.audit import audit_log
    audit_log("export.trigger", email=session.get("email"), workspace_id=workspace_id, resource_type="questionnaire", resource_id=questionnaire_id, details={"job_id": job.id})
    result = {"job_id": job.id, "status": "queued"}
    if idem_key:
        idempotency_set(db, idem_key, 200, result)
    return result


@router.get("/records")
def list_export_records(
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """List export records for workspace."""
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    recs = db.query(ExportRecord).filter(ExportRecord.workspace_id == workspace_id).order_by(ExportRecord.created_at.desc()).limit(50).all()
    return [
        {
            "id": r.id,
            "questionnaire_id": r.questionnaire_id,
            "filename": r.filename,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in recs
    ]


@router.get("/records/{record_id}/download")
def get_download_url(
    record_id: int,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_export),
    db: Session = Depends(get_db),
    storage: StorageClient = Depends(get_storage),
):
    """Stream export file so the browser can download it (same-origin; presigned URLs are not reachable from the client)."""
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    rec = db.query(ExportRecord).filter(
        ExportRecord.id == record_id,
        ExportRecord.workspace_id == workspace_id,
    ).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Export not found")
    from app.core.audit import audit_log
    audit_log("export.download", email=session.get("email"), workspace_id=workspace_id, resource_type="export_record", resource_id=record_id, details={"filename": rec.filename})
    from app.services.file_service import validate_storage_key
    validate_storage_key(rec.storage_key)
    if not storage.exists(storage.bucket_exports, rec.storage_key):
        raise HTTPException(status_code=404, detail="Export file not found")
    stream = storage.download_stream(storage.bucket_exports, rec.storage_key)
    safe_filename = rec.filename or "export.xlsx"
    disposition = f'attachment; filename*=UTF-8\'\'{quote(safe_filename)}'
    ext = (safe_filename.rsplit(".", 1)[-1].lower() if "." in safe_filename else "") or "xlsx"
    media_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if ext == "docx"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return StreamingResponse(
        stream,
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )