"""Export and generate-answers job enqueue logic. Keeps routes thin."""

import hashlib
import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.job_errors import (
    EXPORT_DOCX_FAILED,
    EXPORT_MAPPING_STALE,
    EXPORT_STORAGE_FAILED,
    EXPORT_XLSX_FAILED,
)
from app.core.logging_config import request_id_ctx
from app.models import Job, Questionnaire
from app.services.answer_generation import (
    is_allowed_model,
    is_allowed_response_style,
    resolve_model,
    resolve_response_style,
)
from app.services.file_service import sanitize_filename
from app.services.job_effects import enqueue_job, job_idempotency_key

_logger = logging.getLogger(__name__)

# TC-13-005. Fixed, non-leaky copy. Never include exception text, paths, or object keys.
EXPORT_XLSX_FAILED_MESSAGE = (
    "The XLSX export could not be written. No substitute file was produced."
)
EXPORT_DOCX_FAILED_MESSAGE = (
    "The DOCX export could not be written. No substitute file was produced."
)
EXPORT_STORAGE_FAILED_MESSAGE = "The export could not be stored. No substitute file was produced."
EXPORT_MAPPING_STALE_MESSAGE = (
    "The workbook no longer matches the stored cell mapping. No answers were written."
)
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_EXPORT_MEDIA = {"xlsx": XLSX_MEDIA_TYPE, "docx": DOCX_MEDIA_TYPE}
_FIXED_EXPORT_ERRORS = {
    EXPORT_XLSX_FAILED: EXPORT_XLSX_FAILED_MESSAGE,
    EXPORT_DOCX_FAILED: EXPORT_DOCX_FAILED_MESSAGE,
    EXPORT_STORAGE_FAILED: EXPORT_STORAGE_FAILED_MESSAGE,
    EXPORT_MAPPING_STALE: EXPORT_MAPPING_STALE_MESSAGE,
}


def enqueue_export_job(
    db: Session,
    workspace_id: int,
    questionnaire_id: int,
    format: str = "xlsx",
) -> Job:
    """Create and enqueue an export job. Caller must have verified workspace access and questionnaire exists."""
    if format not in ("xlsx", "docx"):
        raise ValueError("format must be xlsx or docx")
    qnr = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id == questionnaire_id,
            Questionnaire.workspace_id == workspace_id,
        )
        .first()
    )
    if not qnr:
        raise ValueError("Questionnaire not found")
    # TC-10-003: an identical export that is still QUEUED is reused instead of duplicated.
    job, _created = enqueue_job(
        db,
        workspace_id=workspace_id,
        kind="export",
        payload={
            "questionnaire_id": questionnaire_id,
            "workspace_id": workspace_id,
            "format": format,
        },
        idempotency_key=job_idempotency_key("export", workspace_id, questionnaire_id, format),
    )
    _logger.info(
        "EXPORT: job created job_id=%s kind=export questionnaire_id=%s workspace_id=%s",
        job.id,
        questionnaire_id,
        workspace_id,
    )
    return job


def enqueue_generate_answers_job(
    db: Session,
    workspace_id: int,
    questionnaire_id: int,
    model_override: str | None = None,
    response_style_override: str | None = None,
) -> Job:
    """Create and enqueue a generate_answers job. Validates model/response_style if provided."""
    if model_override is not None and not is_allowed_model(model_override):
        raise ValueError("Unsupported model")
    if response_style_override is not None and not is_allowed_response_style(
        response_style_override
    ):
        raise ValueError("Unsupported response style")
    qnr = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id == questionnaire_id,
            Questionnaire.workspace_id == workspace_id,
        )
        .first()
    )
    if not qnr:
        raise ValueError("Questionnaire not found")
    payload = {"questionnaire_id": questionnaire_id, "workspace_id": workspace_id}
    if model_override is not None:
        payload["model"] = resolve_model(model_override)
    if response_style_override is not None:
        payload["response_style"] = resolve_response_style(response_style_override)
    rid = request_id_ctx.get()
    if rid:
        # TC-11-001: lets a failed job's ApiError carry the originating request_id.
        payload["request_id"] = str(rid)
    # TC-10-003: an identical generation that is still QUEUED is reused instead of duplicated.
    job, _created = enqueue_job(
        db,
        workspace_id=workspace_id,
        kind="generate_answers",
        payload=payload,
        idempotency_key=job_idempotency_key(
            "generate_answers",
            workspace_id,
            questionnaire_id,
            payload.get("model"),
            payload.get("response_style"),
        ),
    )
    _logger.info(
        "GENERATE_ANSWERS: job persisted job_id=%s questionnaire_id=%s workspace_id=%s",
        job.id,
        questionnaire_id,
        workspace_id,
    )
    return job


def requested_format(value: object) -> str:
    """Export format the client asked for. Anything else stays XLSX (no silent DOCX)."""
    if isinstance(value, str) and value.lower() == "docx":
        return "docx"
    return "xlsx"


def export_filename(source: str | None, fmt: str, *, pack: bool = False) -> str:
    """Filename whose extension is the format actually produced."""
    fmt = "docx" if fmt == "docx" else "xlsx"
    stem = Path(sanitize_filename(source or f"export.{fmt}")).stem or "export"
    stem = stem[:180]
    if fmt == "docx" and pack:
        return f"{stem}_answers.docx"
    return f"{stem}.{fmt}"


def media_type_for_format(fmt: str) -> str:
    return _EXPORT_MEDIA["docx" if fmt == "docx" else "xlsx"]


def media_type_for_filename(filename: str) -> str | None:
    ext = Path(filename or "").suffix.lower()
    if ext == ".xlsx":
        return XLSX_MEDIA_TYPE
    if ext == ".docx":
        return DOCX_MEDIA_TYPE
    return None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _mapping_version(question: dict) -> int:
    raw = question.get("mapping_version")
    if isinstance(raw, bool) or not isinstance(raw, int):
        return 0
    return raw


def _sheet_name(question: dict) -> str | None:
    sheet = question.get("sheet")
    if isinstance(sheet, str) and sheet:
        return sheet
    raw = question.get("source_location")
    if isinstance(raw, str) and raw:
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if isinstance(loaded, dict) and isinstance(loaded.get("sheet"), str) and loaded["sheet"]:
            return loaded["sheet"]
    return None


def export_mapping_is_stale(questions: list[dict], workbook: bytes) -> bool:
    """True when a stored cell mapping must not be used to write answers.

    A file hash that does not match these bytes is stale. A ruleset of 1 or
    newer is also stale when its question cell text, sheet or answer cell no
    longer matches. Legacy rows (version 0 and no file hash) are not stale:
    they still use the column offset. This never returns cell text or hashes.
    """
    from app.services.cell_mapping import content_hash, parse_cell_ref
    from app.services.question_normalizer import normalize_question

    digest = sha256_hex(workbook)
    explicit: list[dict] = []
    for question in questions:
        stored = _valid_sha256(question.get("original_file_hash"))
        if stored is not None and stored != digest:
            return True
        if _mapping_version(question) >= 1:
            explicit.append(question)
    if not explicit:
        return False
    from io import BytesIO

    from openpyxl import load_workbook

    try:
        book = load_workbook(BytesIO(workbook), data_only=False)
    except Exception:
        return False
    try:
        for question in explicit:
            sheet_name = _sheet_name(question)
            if not sheet_name or sheet_name not in book.sheetnames:
                return True
            question_at = parse_cell_ref(question.get("question_cell"))
            expected = _valid_sha256(question.get("content_hash"))
            if question_at is None or expected is None:
                return True
            row, column = question_at
            value = book[sheet_name].cell(row=row, column=column).value
            current = content_hash(normalize_question("" if value is None else str(value)))
            if current != expected:
                return True
            answer_ref = question.get("answer_cell")
            if answer_ref and parse_cell_ref(answer_ref) is None:
                return True
    finally:
        book.close()
    return False


def public_export_failure(code: str | None) -> tuple[str, str]:
    """Fixed code and message for a failed export. Stored exception text is ignored."""
    if code in _FIXED_EXPORT_ERRORS:
        return code, _FIXED_EXPORT_ERRORS[code]
    return EXPORT_XLSX_FAILED, EXPORT_XLSX_FAILED_MESSAGE


def _valid_sha256(value: object) -> str | None:
    if not isinstance(value, str) or len(value) != 64:
        return None
    if any(char not in "0123456789abcdef" for char in value):
        return None
    return value


def recorded_export_file(result: str | None) -> dict | None:
    """sha256, content type and filename stored with a successful export, or None."""
    if not result:
        return None
    try:
        data = json.loads(result)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    digest = _valid_sha256(data.get("sha256"))
    content_type = data.get("content_type")
    if digest is None or content_type not in (XLSX_MEDIA_TYPE, DOCX_MEDIA_TYPE):
        return None
    filename = data.get("filename")
    return {
        "sha256": digest,
        "content_type": content_type,
        "filename": filename if isinstance(filename, str) and filename else None,
    }


def export_result_json(
    *,
    export_record_id: int,
    storage_key: str,
    sha256: str | None = None,
    content_type: str | None = None,
    filename: str | None = None,
    outcome: str | None = None,
) -> str:
    """Job result for an export. Extra keys are not an artifact grant; the jobs API drops them."""
    body: dict = {"export_record_id": export_record_id, "storage_key": storage_key}
    digest = _valid_sha256(sha256)
    if digest is not None:
        body["sha256"] = digest
    if content_type in (XLSX_MEDIA_TYPE, DOCX_MEDIA_TYPE):
        body["content_type"] = content_type
    if isinstance(filename, str) and filename:
        body["filename"] = filename
    if outcome in ("already_applied", "reconciled", "superseded"):
        body["outcome"] = outcome
    return json.dumps(body)


def persist_failed_export_record(job, payload: dict | None) -> None:
    """Commit a failed export row that survives the worker's rollback of the attempt.

    The row has no file. ``storage_key`` is a sentinel, not an uploaded object.
    The error code and message stay on the job; this row only records the failure
    and the format the client asked for.
    """
    from app.core.database import SessionLocal
    from app.models import ExportRecord, Questionnaire

    if getattr(job, "kind", None) != "export":
        return
    workspace_id = getattr(job, "workspace_id", None)
    job_id = getattr(job, "id", None)
    if not isinstance(workspace_id, int) or isinstance(workspace_id, bool):
        return
    if not isinstance(job_id, int) or isinstance(job_id, bool):
        return
    data = payload if isinstance(payload, dict) else {}
    fmt = requested_format(data.get("format"))
    questionnaire_id = data.get("questionnaire_id")
    db = SessionLocal()
    try:
        questionnaire = None
        if isinstance(questionnaire_id, int) and not isinstance(questionnaire_id, bool):
            questionnaire = (
                db.query(Questionnaire)
                .filter(
                    Questionnaire.id == questionnaire_id,
                    Questionnaire.workspace_id == workspace_id,
                )
                .first()
            )
        filename = export_filename(
            questionnaire.filename if questionnaire is not None else None, fmt
        )
        key = f"exports/{workspace_id}/job-{job_id}.failed"
        existing = (
            db.query(ExportRecord)
            .filter(
                ExportRecord.job_id == job_id,
                ExportRecord.workspace_id == workspace_id,
            )
            .first()
        )
        if existing is not None and (existing.status or "completed") == "completed":
            return
        if existing is not None:
            existing.status = "failed"
            existing.filename = filename
            existing.storage_key = key
            db.commit()
            return
        db.add(
            ExportRecord(
                workspace_id=workspace_id,
                questionnaire_id=questionnaire.id if questionnaire is not None else None,
                storage_key=key,
                filename=filename,
                status="failed",
                job_id=job_id,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
