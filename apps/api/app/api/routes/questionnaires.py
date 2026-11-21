"""Questionnaire API (QNR-01, QNR-02, QNR-13, AI-05)."""

import json
import os  # noqa: F401
import re  # noqa: F401
import logging
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.routes.answers import answer_revision_token
from app.api.schemas import BulkDeleteBody, MetadataUpdateBody
from app.core.api_errors import (
    ApiError,
    FieldError,
    api_error_response,
    current_request_id,
    outcome_payload,
)
from app.core.idempotency import (
    IdempotencyKeyError,
    claim as idempotency_claim,
    get as idempotency_get,
    release as idempotency_release,
    scoped_key as idempotency_scoped_key,
    set as idempotency_set,
)
from app.core.audit import audit_log
from app.core.config import get_settings
from app.core.auth_deps import require_can_edit, require_can_review, require_session
from app.core.database import get_db
from app.core.workspace_refs import require_refs
from app.models import (
    Answer,
    Document,
    ExportRecord,  # noqa: F401
    Framework,
    FrameworkControl,
    Job,
    JobKind,
    JobStatus,
    Question,
    Questionnaire,
    WorkspaceControl,
)
from app.models.ai_mapping import QuestionMappingPreference
from app.services.answer_revisions import open_drafts_by_answer, revision_payload
from app.services.answer_support import support_is_stale
from app.services.compliance_hooks import (
    get_mapping_timing_snapshot,
    match_keywords_for_mapping_row,
    mapping_timing_enabled,
    reset_mapping_timing,
)
from app.services.mapping_llm_rerank import get_rerank_perf_snapshot, reset_rerank_perf_stats
from app.services.file_service import FileService
from app.services.job_effects import enqueue_job, job_idempotency_key
from app.services.storage_reconcile import discard_if_unreferenced
from app.services.upload_enqueue import UPLOAD_IDEMPOTENCY_RESOURCE
from app.services.questionnaire_mapping_evidence import (
    batch_supporting_evidence_for_workspace_controls,
    suggest_documents_for_mapping_review,
)
from app.services.questionnaire_answer_evidence import validate_answer_evidence_document_ids
from app.services.registry_metadata import (
    FRAMEWORK_LABELS,
    SUBJECT_AREA_LABELS,
    build_display_id,
    normalize_labels,
    parse_json_list,
    to_json,  # noqa: F401
)
from app.services.registry_lifecycle import (
    build_delete_preview,
    restore_record,
    soft_delete_record,
    update_metadata_json_fields,
)
from app.services.storage import get_storage, StorageClient
from app.services.xlsx_writer import UnsupportedWorkbookStructure, reject_unsupported_workbook
from app.services.mapping_llm_classify import (
    classify_and_persist as classify_question_signal,
    _preload_existing_signals,
    _classify_one_thread_safe,
    _PARALLEL_WORKERS,
)
from app.services.workspace_usage import record_mapping_calls

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/questionnaires", tags=["questionnaires"])
_UPLOAD_SCOPE = "questionnaires.upload"


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
        _log.warning("questionnaire upload: failed to release idempotency claim", exc_info=True)


def _answer_evidence_payload(db: Session, workspace_id: int, qnr: Questionnaire) -> dict:
    """IDs + filenames for answer-evidence scoping (AI may only use these documents when drafting answers)."""
    raw_ids: list = []
    if getattr(qnr, "answer_evidence_document_ids_json", None):
        try:
            raw_ids = json.loads(qnr.answer_evidence_document_ids_json)
        except Exception:
            raw_ids = []
    if not isinstance(raw_ids, list):
        raw_ids = []
    validated = validate_answer_evidence_document_ids(db, workspace_id, qnr.id, raw_ids)
    docs_out: list[dict] = []
    for did in validated:
        d = db.query(Document).filter(Document.id == did).first()
        if d:
            docs_out.append({"id": d.id, "filename": d.filename})
    return {
        "answer_evidence_document_ids": validated,
        "answer_evidence_documents": docs_out,
    }


def get_file_service(storage: StorageClient = Depends(get_storage)) -> FileService:
    return FileService(storage)


_WORKBOOK_UPLOAD_SUFFIXES = frozenset({".xlsx", ".xlsm", ".xls"})


def _reject_unsupported_workbook_upload(filename: str | None, content: bytes) -> None:
    """Raise when a spreadsheet upload is a macro, encrypted, or legacy workbook.

    The exception text is the export preflight message. Other suffixes are left
    to the extension allowlist and are not inspected here.
    """
    if Path(filename or "").suffix.lower() not in _WORKBOOK_UPLOAD_SUFFIXES:
        return
    reject_unsupported_workbook(content)


@router.post("/upload")
def upload_questionnaire(
    request: Request,
    workspace_id: int = Form(...),
    file: UploadFile = ...,
    frameworks: str = Form(""),
    subject_areas: str = Form(""),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
    file_svc: FileService = Depends(get_file_service),
):
    """Upload questionnaire file. Enqueues a parse job.

    A macro, encrypted, or legacy workbook is refused before the object, the
    questionnaire, and the parse job exist. The detail is the export preflight
    sentence. The questionnaire, its parse job, and the optional Idempotency-Key
    response commit once.
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

        def _refuse_unsupported_workbook(content: bytes) -> None:
            try:
                _reject_unsupported_workbook_upload(getattr(file, "filename", None), content)
            except UnsupportedWorkbookStructure as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from None

        stored_key, filename = file_svc.upload_raw(
            workspace_id, file, before_store=_refuse_unsupported_workbook
        )
        fw_list = [f.strip() for f in frameworks.split(",") if f.strip()] or ["Other"]
        sa_list = [s.strip() for s in subject_areas.split(",") if s.strip()] or ["Other"]
        qnr = Questionnaire(
            workspace_id=workspace_id,
            storage_key=stored_key,
            filename=filename,
            frameworks_json=json.dumps(fw_list),
            subject_areas_json=json.dumps(sa_list),
            status="uploaded",
        )
        db.add(qnr)
        db.flush()
        qnr.display_id = build_display_id("questionnaire", qnr.id)
        # TC-10-003: input_version pins the job to this upload's object; a stale job is superseded.
        # commit=False keeps the row and the job in this transaction (TC-10-003c).
        job, _created = enqueue_job(
            db,
            workspace_id=workspace_id,
            kind="parse_questionnaire",
            payload={"questionnaire_id": qnr.id, "storage_key": stored_key},
            idempotency_key=job_idempotency_key(
                "parse_questionnaire", workspace_id, qnr.id, stored_key
            ),
            input_version=stored_key,
            commit=False,
        )
        result = {
            "id": qnr.id,
            "display_id": qnr.display_id,
            "filename": qnr.filename,
            "status": qnr.status,
            "storage_key": qnr.storage_key,
            "job_id": job.id,
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
        "questionnaire.upload",
        email=session.get("email"),
        workspace_id=workspace_id,
        resource_type="questionnaire",
        resource_id=result["id"],
        details={"filename": result["filename"]},
    )
    return result


_SEARCH_QUERY_MAX_LEN = 200
_PAGE_SIZE_DEFAULT = 25
_PAGE_SIZE_MAX = 100
_PAGE_MAX = 1_000_000
_ID_MAX = 2_147_483_647
_PROGRESS_LIMIT = 9_007_199_254_740_991
_SORT_COLUMNS = {
    "created_at": Questionnaire.created_at,
    "filename": Questionnaire.filename,
    "status": Questionnaire.status,
    "id": Questionnaire.id,
}
_JOB_KINDS = (JobKind.PARSE_QUESTIONNAIRE.value, JobKind.GENERATE_ANSWERS.value)
_JOB_STATUSES = {status.value for status in JobStatus}


def _same_workspace(session: dict, workspace_id: int) -> None:
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")


def _progress_pair(raw: str | None) -> dict | None:
    """The history pair, or None when the stored result did not record one."""
    if not isinstance(raw, str) or not raw.lstrip().startswith("{"):
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    generated, total = data.get("generated"), data.get("total")
    if type(generated) is int and type(total) is int and 0 <= generated <= total <= _PROGRESS_LIMIT:
        return {"generated": generated, "total": total}
    return None


def _payload_questionnaire_id(raw: str | None) -> int | None:
    if not isinstance(raw, str) or not raw.lstrip().startswith("{"):
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    questionnaire_id = data.get("questionnaire_id")
    if type(questionnaire_id) is not int or not 0 < questionnaire_id <= _ID_MAX:
        return None
    return questionnaire_id


def _paging(page: int | None, page_size: int | None, sort: str | None, order: str | None):
    """None keeps the unpaged array. Any paging parameter selects one page."""
    if page is None and page_size is None and sort is None and order is None:
        return None
    page = 1 if page is None else page
    page_size = _PAGE_SIZE_DEFAULT if page_size is None else page_size
    sort = "created_at" if sort is None else sort
    order = "desc" if order is None else order
    if type(page) is not int or not 1 <= page <= _PAGE_MAX:
        raise HTTPException(status_code=400, detail="Invalid page")
    if type(page_size) is not int or not 1 <= page_size <= _PAGE_SIZE_MAX:
        raise HTTPException(status_code=400, detail="Invalid page_size")
    if sort not in _SORT_COLUMNS:
        raise HTTPException(status_code=400, detail="Invalid sort")
    if order not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="Invalid order")
    return page, page_size, sort, order


def _active_questionnaire(db: Session, workspace_id: int, qnr_id: int) -> Questionnaire:
    qnr = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id == qnr_id,
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_(None),
        )
        .first()
    )
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    return qnr


def _confirmation_url(qnr_id: int, ambiguous: bool) -> str | None:
    if not ambiguous:
        return None
    return f"/dashboard/questionnaires/{qnr_id}/confirm-mapping"


def _job_metadata(db: Session, workspace_id: int, ids: list[int]) -> dict[int, dict]:
    """Newest parse job, and the newest generated/total pair, for these rows."""
    found = {qnr_id: {"job_id": None, "job_status": None, "job_progress": None} for qnr_id in ids}
    if not ids:
        return found
    rows = (
        db.query(Job.id, Job.kind, Job.status, Job.payload, Job.result)
        .filter(Job.workspace_id == workspace_id, Job.kind.in_(_JOB_KINDS))
        .order_by(Job.id.desc())
        .all()
    )
    wanted = set(ids)
    for job_id, kind, status, payload, result in rows:
        questionnaire_id = _payload_questionnaire_id(payload)
        if questionnaire_id not in wanted:
            continue
        slot = found[questionnaire_id]
        if kind == JobKind.PARSE_QUESTIONNAIRE.value and slot["job_id"] is None:
            slot["job_id"] = job_id
            slot["job_status"] = status if status in _JOB_STATUSES else None
        if slot["job_progress"] is None:
            pair = _progress_pair(result)
            if pair is not None:
                slot["job_progress"] = pair
    return found


def _row_metadata(db: Session, workspace_id: int, qnrs: list[Questionnaire]) -> list[dict]:
    ids = [qnr.id for qnr in qnrs]
    question_counts: dict[int, int] = {}
    reviewed_counts: dict[int, int] = {}
    ambiguous: set[int] = set()
    if ids:
        question_counts = {
            qnr_id: count
            for qnr_id, count in db.query(Question.questionnaire_id, func.count(Question.id))
            .filter(Question.questionnaire_id.in_(ids))
            .group_by(Question.questionnaire_id)
            .all()
        }
        reviewed_counts = {
            qnr_id: count
            for qnr_id, count in db.query(
                Question.questionnaire_id, func.count(func.distinct(Question.id))
            )
            .join(Answer, Answer.question_id == Question.id)
            .filter(Question.questionnaire_id.in_(ids), Answer.status == "approved")
            .group_by(Question.questionnaire_id)
            .all()
        }
        ambiguous = {
            qnr_id
            for (qnr_id,) in db.query(QuestionMappingPreference.questionnaire_id)
            .filter(
                QuestionMappingPreference.workspace_id == workspace_id,
                QuestionMappingPreference.questionnaire_id.in_(ids),
                QuestionMappingPreference.status == "suggested",
            )
            .distinct()
            .all()
        }
    jobs = _job_metadata(db, workspace_id, ids)
    rows = []
    for qnr in qnrs:
        question_count = int(question_counts.get(qnr.id, 0))
        job = jobs.get(qnr.id) or {"job_id": None, "job_status": None, "job_progress": None}
        is_ambiguous = qnr.id in ambiguous
        rows.append(
            {
                "id": qnr.id,
                "display_id": qnr.display_id or build_display_id("questionnaire", qnr.id),
                "filename": qnr.filename,
                "status": qnr.status,
                "parse_metadata": qnr.parse_metadata,
                "created_at": qnr.created_at.isoformat() if qnr.created_at else None,
                "deleted_at": qnr.deleted_at.isoformat() if qnr.deleted_at else None,
                "frameworks": normalize_labels(
                    parse_json_list(qnr.frameworks_json), allowed=FRAMEWORK_LABELS
                ),
                "subject_areas": normalize_labels(
                    parse_json_list(qnr.subject_areas_json), allowed=SUBJECT_AREA_LABELS
                ),
                "question_count": question_count,
                "review_reviewed": int(reviewed_counts.get(qnr.id, 0)),
                "review_total": question_count,
                "job_id": job["job_id"],
                "job_status": job["job_status"],
                "job_progress": job["job_progress"],
                "mapping_ambiguous": is_ambiguous,
                "mapping_confirmation_url": _confirmation_url(qnr.id, is_ambiguous),
                "needs_review": qnr.status == "needs_review",
            }
        )
    return rows


def _list_questionnaires_impl(
    workspace_id: int,
    session: dict,
    db: Session,
    search_q: str | None = None,
    framework: str | None = None,
    subject_area: str | None = None,
    status: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    archived: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    sort: str | None = None,
    order: str | None = None,
):
    """Shared implementation for list questionnaires (QNR-02). Optional search_q filters by filename substring."""
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    query = db.query(Questionnaire).filter(Questionnaire.workspace_id == workspace_id)
    mode = (archived or "active").strip().lower()
    if mode == "active":
        query = query.filter(Questionnaire.deleted_at.is_(None))
    elif mode == "only":
        query = query.filter(Questionnaire.deleted_at.is_not(None))
    if search_q and (q_strip := search_q.strip()[:_SEARCH_QUERY_MAX_LEN]):
        like = f"%{q_strip}%"
        query = query.filter(
            Questionnaire.filename.ilike(like)
            | Questionnaire.display_id.ilike(like)
            | Questionnaire.status.ilike(like)
            | Questionnaire.frameworks_json.ilike(like)
            | Questionnaire.subject_areas_json.ilike(like)
        )
    if framework:
        query = query.filter(Questionnaire.frameworks_json.ilike(f"%{framework.strip()}%"))
    if subject_area:
        query = query.filter(Questionnaire.subject_areas_json.ilike(f"%{subject_area.strip()}%"))
    if status:
        query = query.filter(Questionnaire.status == status)
    if created_from:
        try:
            query = query.filter(Questionnaire.created_at >= datetime.fromisoformat(created_from))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid created_from datetime")
    if created_to:
        try:
            query = query.filter(Questionnaire.created_at <= datetime.fromisoformat(created_to))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid created_to datetime")

    paging = _paging(page, page_size, sort, order)
    total = query.count()
    if paging is None:
        qnrs = query.order_by(Questionnaire.created_at.desc(), Questionnaire.id.desc()).all()
        return _row_metadata(db, workspace_id, qnrs)
    page_number, size, sort_name, direction = paging
    column = _SORT_COLUMNS[sort_name]
    ordered = column.desc() if direction == "desc" else column.asc()
    if sort_name == "id":
        query = query.order_by(ordered)
    else:
        query = query.order_by(ordered, Questionnaire.id.desc())
    qnrs = query.offset((page_number - 1) * size).limit(size).all()
    return {
        "items": _row_metadata(db, workspace_id, qnrs),
        "page": page_number,
        "page_size": size,
        "total": total,
        "sort": sort_name,
        "order": direction,
    }


@router.get("/")
@router.get("")
def list_questionnaires(
    workspace_id: int,
    q: str | None = Query(None, description="Filter by filename (case-insensitive substring)"),
    search: str | None = Query(
        None, description="Search by display id, filename, framework, subject, status"
    ),
    framework: str | None = Query(None),
    subject_area: str | None = Query(None),
    status: str | None = Query(None),
    created_from: str | None = Query(None),
    created_to: str | None = Query(None),
    archived: str | None = Query(None, description="active|include|only"),
    page: int | None = Query(None, description="1-based page. Selects the paged response."),
    page_size: int | None = Query(None, description="Page size, 1 to 100."),
    sort: str | None = Query(None, description="created_at, filename, status, or id"),
    order: str | None = Query(None, description="asc or desc"),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """List questionnaires. Optional q filters by filename substring. Accepts with or without trailing slash.

    Omitting page, page_size, sort, and order keeps the historical JSON array, newest first.
    Sending any of them returns one page. Rows include question and review counts, the newest
    parse job, job progress, needs_review, and a mapping-confirmation path when a suggestion
    is still unconfirmed.
    """
    return _list_questionnaires_impl(
        workspace_id,
        session,
        db,
        search_q=search or q,
        framework=framework,
        subject_area=subject_area,
        status=status,
        created_from=created_from,
        created_to=created_to,
        archived=archived,
        page=page,
        page_size=page_size,
        sort=sort,
        order=order,
    )


class MappingConfirmationBody(BaseModel):
    mapping_ids: list[int] = Field(min_length=1, max_length=200)


def _confirmation_payload(db: Session, workspace_id: int, qnr: Questionnaire) -> dict:
    mappings = (
        db.query(QuestionMappingPreference)
        .filter(
            QuestionMappingPreference.questionnaire_id == qnr.id,
            QuestionMappingPreference.workspace_id == workspace_id,
            QuestionMappingPreference.status == "suggested",
        )
        .order_by(QuestionMappingPreference.id)
        .all()
    )
    question_ids = [row.question_id for row in mappings if type(row.question_id) is int]
    questions = {}
    if question_ids:
        questions = {
            question.id: question
            for question in db.query(Question)
            .filter(Question.id.in_(question_ids), Question.questionnaire_id == qnr.id)
            .all()
        }
    items = []
    for mapping in mappings:
        question = questions.get(mapping.question_id)
        text = (
            question.text if question and question.text else mapping.normalized_question_text or ""
        )
        items.append(
            {
                "id": mapping.id,
                "question_id": mapping.question_id if question else None,
                "question_text": text,
                "status": mapping.status,
                "preferred_control_id": mapping.preferred_control_id,
                "preferred_framework_key": mapping.preferred_framework_key,
            }
        )
    ambiguous = bool(items)
    return {
        "questionnaire_id": qnr.id,
        "display_id": qnr.display_id or build_display_id("questionnaire", qnr.id),
        "filename": qnr.filename,
        "mapping_ambiguous": ambiguous,
        "needs_review": qnr.status == "needs_review",
        "mapping_confirmation_url": _confirmation_url(qnr.id, ambiguous),
        "items": items,
    }


@router.get("/{qnr_id}/mapping-confirmation")
def get_mapping_confirmation(
    qnr_id: int,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Suggested mappings a reviewer can read and an editor can confirm."""
    _same_workspace(session, workspace_id)
    qnr = _active_questionnaire(db, workspace_id, qnr_id)
    return _confirmation_payload(db, workspace_id, qnr)


@router.post("/{qnr_id}/mapping-confirmation")
def confirm_mapping(
    qnr_id: int,
    body: MappingConfirmationBody,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    """Approve the named suggested mappings. Unknown or non-suggested ids change nothing."""
    _same_workspace(session, workspace_id)
    qnr = _active_questionnaire(db, workspace_id, qnr_id)
    mapping_ids = list(body.mapping_ids)
    if len(mapping_ids) != len(set(mapping_ids)):
        raise HTTPException(status_code=400, detail="mapping_ids must be unique")
    if any(
        type(mapping_id) is not int or not 0 < mapping_id <= _ID_MAX for mapping_id in mapping_ids
    ):
        raise HTTPException(status_code=400, detail="Invalid mapping id")
    rows = (
        db.query(QuestionMappingPreference)
        .filter(
            QuestionMappingPreference.id.in_(mapping_ids),
            QuestionMappingPreference.questionnaire_id == qnr.id,
            QuestionMappingPreference.workspace_id == workspace_id,
            QuestionMappingPreference.status == "suggested",
        )
        .all()
    )
    if len(rows) != len(mapping_ids):
        raise HTTPException(
            status_code=400,
            detail="Mapping is not a suggested mapping for this questionnaire",
        )
    now = datetime.now(timezone.utc)
    for mapping in rows:
        mapping.status = "approved"
        mapping.approved = True
        mapping.updated_at = now
    db.commit()
    remaining = (
        db.query(QuestionMappingPreference.id)
        .filter(
            QuestionMappingPreference.questionnaire_id == qnr.id,
            QuestionMappingPreference.workspace_id == workspace_id,
            QuestionMappingPreference.status == "suggested",
        )
        .count()
    )
    return {"ok": True, "confirmed": len(rows), "mapping_ambiguous": remaining > 0}


@router.get("/{qnr_id}")
def get_questionnaire(
    qnr_id: int,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Get single questionnaire."""
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    qnr = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id == qnr_id,
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_(None),
        )
        .first()
    )
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    questions = db.query(Question).filter(Question.questionnaire_id == qnr_id).all()
    qids = [q.id for q in questions]
    answers = (
        {a.question_id: a for a in db.query(Answer).filter(Answer.question_id.in_(qids)).all()}
        if qids
        else {}
    )
    # TC-12-004a: the answer fields stay the approved row. An open draft is beside them.
    drafts = open_drafts_by_answer(db, [a.id for a in answers.values()])
    _log.info(
        "API: questionnaire fetched questionnaire_id=%s workspace_id=%s questions=%s answers=%s",
        qnr_id,
        workspace_id,
        len(questions),
        len(answers),
    )
    _rid = current_request_id()
    return {
        "id": qnr.id,
        "display_id": qnr.display_id or build_display_id("questionnaire", qnr.id),
        "document_id": qnr.document_id,
        "filename": qnr.filename,
        "status": qnr.status,
        "parse_metadata": qnr.parse_metadata,
        "frameworks": normalize_labels(
            parse_json_list(qnr.frameworks_json), allowed=FRAMEWORK_LABELS
        ),
        "subject_areas": normalize_labels(
            parse_json_list(qnr.subject_areas_json), allowed=SUBJECT_AREA_LABELS
        ),
        "questions": [
            {
                "id": q.id,
                "text": q.text,
                "section": q.section,
                "answer_type": q.answer_type,
                "source_location": q.source_location,
                "content_hash": q.content_hash,
                "original_file_hash": q.original_file_hash,
                "sheet": q.sheet,
                "question_cell": q.question_cell,
                "answer_cell": q.answer_cell,
                "mapping_version": q.mapping_version,
                "answer": (
                    {
                        "id": answers[q.id].id,
                        "text": answers[q.id].text,
                        "status": answers[q.id].status,
                        "citations": answers[q.id].citations,
                        # TC-11-001: typed generation outcome (null for legacy/manual answers).
                        "outcome_code": getattr(answers[q.id], "outcome_code", None),
                        "outcome": outcome_payload(
                            getattr(answers[q.id], "outcome_code", None), _rid
                        ),
                        "draft_revision": revision_payload(drafts.get(answers[q.id].id)),
                        # TC-12-002: updated_at is the revision the editor must send back.
                        "updated_at": answer_revision_token(answers[q.id].updated_at),
                        # TC-08-006: approved text stays; this marks a revoked source.
                        "support_stale": support_is_stale(
                            db, workspace_id, answers[q.id].citations
                        ),
                    }
                    if q.id in answers
                    else None
                ),
            }
            for q in questions
        ],
        "created_at": qnr.created_at.isoformat() if qnr.created_at else None,
        "mapping_preferred_subject_areas": _mapping_subject_areas_response(qnr),
        **_answer_evidence_payload(db, workspace_id, qnr),
    }


def _normalize_mapping_subject_areas(raw: list[str]) -> list[str]:
    """Canonical subject-area labels for AI category mapping (soft rank for control suggestions)."""
    allowed = set(SUBJECT_AREA_LABELS)
    out: list[str] = []
    for x in raw or []:
        s = str(x).strip()
        if s in allowed and s not in out:
            out.append(s)
        if len(out) >= 24:
            break
    return out


def _mapping_subject_areas_response(qnr: Questionnaire) -> list[str]:
    raw = getattr(qnr, "mapping_preferred_subject_areas_json", None)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        return _normalize_mapping_subject_areas([str(x) for x in data])
    except Exception:
        return []


class MappingPreferenceBody(BaseModel):
    mapping_preferred_subject_areas: list[str] = Field(default_factory=list)


class AnswerEvidenceBody(BaseModel):
    document_ids: list[int] = Field(default_factory=list)


@router.patch("/{qnr_id}/answer-evidence")
def update_questionnaire_answer_evidence(
    qnr_id: int,
    body: AnswerEvidenceBody,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    """Restrict draft-answer generation to specific workspace documents (truthfulness / source isolation)."""
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    qnr = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id == qnr_id,
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_(None),
        )
        .first()
    )
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    validated = validate_answer_evidence_document_ids(
        db, workspace_id, qnr_id, body.document_ids or []
    )
    qnr.answer_evidence_document_ids_json = json.dumps(validated) if validated else None
    qnr.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(qnr)
    audit_log(
        "questionnaire.answer_evidence_update",
        email=session.get("email"),
        workspace_id=workspace_id,
        resource_type="questionnaire",
        resource_id=qnr_id,
        details={"document_ids": validated},
    )
    return _answer_evidence_payload(db, workspace_id, qnr)


@router.patch("/{qnr_id}/mapping-preference")
def update_questionnaire_mapping_preference(
    qnr_id: int,
    body: MappingPreferenceBody,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    """Set subject-area preferences for AI mapping (categories align with evidence subject tags, not frameworks)."""
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    qnr = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id == qnr_id,
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_(None),
        )
        .first()
    )
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    areas = _normalize_mapping_subject_areas(body.mapping_preferred_subject_areas)
    qnr.mapping_preferred_subject_areas_json = json.dumps(areas) if areas else None
    qnr.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(qnr)
    audit_log(
        "questionnaire.mapping_preference_update",
        email=session.get("email"),
        workspace_id=workspace_id,
        resource_type="questionnaire",
        resource_id=qnr_id,
        details={"mapping_preferred_subject_areas": areas},
    )
    return {"ok": True, "mapping_preferred_subject_areas": _mapping_subject_areas_response(qnr)}


@router.post("/bulk-delete")
def bulk_delete_questionnaires(
    body: BulkDeleteBody,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    """Bulk soft-delete questionnaires. Only active (non-archived) records in workspace are processed."""
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if not body.ids:
        return {"deleted": 0, "errors": []}
    qnrs = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id.in_(body.ids),
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_(None),
        )
        .all()
    )
    for qnr in qnrs:
        soft_delete_record(qnr, session.get("user_id"))
        audit_log(
            "questionnaire.soft_delete",
            email=session.get("email"),
            workspace_id=workspace_id,
            resource_type="questionnaire",
            resource_id=qnr.id,
            details={"display_id": qnr.display_id},
        )
    db.commit()
    return {"deleted": len(qnrs), "errors": []}


@router.delete("/{qnr_id}")
def delete_questionnaire(
    qnr_id: int,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    qnr = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id == qnr_id,
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_(None),
        )
        .first()
    )
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")

    preview = build_delete_preview("questionnaire", db, workspace_id, qnr_id)
    soft_delete_record(qnr, session.get("user_id"))
    db.commit()
    audit_log(
        "questionnaire.soft_delete",
        email=session.get("email"),
        workspace_id=workspace_id,
        resource_type="questionnaire",
        resource_id=qnr_id,
        details={"display_id": qnr.display_id, "dependencies": preview.dependencies},
    )
    return {
        "ok": True,
        "id": qnr.id,
        "display_id": qnr.display_id or build_display_id("questionnaire", qnr.id),
        "dependencies": preview.dependencies,
    }


@router.get("/{qnr_id}/delete-preview")
def delete_preview_questionnaire(
    qnr_id: int,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    qnr = (
        db.query(Questionnaire)
        .filter(Questionnaire.id == qnr_id, Questionnaire.workspace_id == workspace_id)
        .first()
    )
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    preview = build_delete_preview("questionnaire", db, workspace_id, qnr_id)
    return {
        "id": qnr.id,
        "display_id": qnr.display_id or preview.display_id,
        "can_delete": preview.can_delete,
        "recommended_action": preview.recommended_action,
        "warnings": preview.warnings,
        "dependencies": preview.dependencies,
        "unmodeled_warning": preview.unmodeled_warning,
    }


@router.post("/{qnr_id}/restore")
def restore_questionnaire(
    qnr_id: int,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    qnr = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id == qnr_id,
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_not(None),
        )
        .first()
    )
    if not qnr:
        raise HTTPException(status_code=404, detail="Archived questionnaire not found")
    restore_record(qnr)
    db.commit()
    audit_log(
        "questionnaire.restore",
        email=session.get("email"),
        workspace_id=workspace_id,
        resource_type="questionnaire",
        resource_id=qnr_id,
        details={"display_id": qnr.display_id},
    )
    return {"ok": True, "id": qnr.id, "display_id": qnr.display_id}


@router.patch("/{qnr_id}/metadata")
def update_questionnaire_metadata(
    qnr_id: int,
    body: MetadataUpdateBody,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    qnr = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id == qnr_id,
            Questionnaire.workspace_id == workspace_id,
        )
        .first()
    )
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    update_metadata_json_fields(qnr, body.frameworks, body.subject_areas)
    db.commit()
    audit_log(
        "questionnaire.metadata_update",
        email=session.get("email"),
        workspace_id=workspace_id,
        resource_type="questionnaire",
        resource_id=qnr_id,
        details={
            "display_id": qnr.display_id,
            "frameworks": body.frameworks,
            "subject_areas": body.subject_areas,
        },
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Questionnaire Mapping Endpoints
# ---------------------------------------------------------------------------


def _mapping_to_dict(m: QuestionMappingPreference) -> dict:
    return {
        "id": m.id,
        "questionnaire_id": m.questionnaire_id,
        "question_id": m.question_id,
        "normalized_question_text": m.normalized_question_text,
        "preferred_control_id": m.preferred_control_id,
        "preferred_framework_key": m.preferred_framework_key,
        "preferred_tag_id": m.preferred_tag_id,
        "source": m.source,
        "confidence": m.confidence,
        "status": getattr(m, "status", "suggested"),
        "approved": m.approved,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


@router.post("/{qnr_id}/generate-mappings")
def generate_questionnaire_mappings(
    qnr_id: int,
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    """Generate AI mapping suggestions: assigns each question to a control using subject-area category bias.

    Uses ``mapping_preferred_subject_areas`` on the questionnaire (not frameworks) to softly rank controls.
    Skips questions that already have approved or manual mappings (won't overwrite).
    Re-generates for questions with status=suggested or status=rejected.
    """
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    qnr = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id == qnr_id,
            Questionnaire.workspace_id == ws,
            Questionnaire.deleted_at.is_(None),
        )
        .first()
    )
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")

    questions = (
        db.query(Question)
        .filter(
            Question.questionnaire_id == qnr_id,
        )
        .order_by(Question.id)
        .all()
    )
    if not questions:
        raise HTTPException(status_code=400, detail="No parsed questions in this questionnaire")

    if mapping_timing_enabled():
        reset_mapping_timing()
        reset_rerank_perf_stats()
        _t_gen_start = time.perf_counter()

    protected_question_ids = set()
    existing = (
        db.query(QuestionMappingPreference)
        .filter(
            QuestionMappingPreference.questionnaire_id == qnr_id,
            QuestionMappingPreference.workspace_id == ws,
        )
        .all()
    )
    existing_by_qid: dict[int, QuestionMappingPreference] = {}
    for m in existing:
        if m.question_id is not None:
            existing_by_qid[m.question_id] = m
            if m.status in ("approved", "manual"):
                protected_question_ids.add(m.question_id)

    created = 0
    updated = 0
    skipped = 0
    classification_calls = 0
    settings = get_settings()

    eligible = [q for q in questions if q.id not in protected_question_ids]
    skipped = len(questions) - len(eligible)

    # Phase 1: parallel LLM classification (all eligible questions at once)
    signal_by_qid: dict[int, Any] = {}  # noqa: F821
    if eligible:
        prompt_ver = settings.mapping_classification_prompt_version
        q_ids = [q.id for q in eligible]
        preloaded = _preload_existing_signals(db, q_ids, ws, prompt_ver)

        needs_llm = [
            (q.id, q.text or "")
            for q in eligible
            if (q.text or "").strip() and q.id not in preloaded
        ]
        for qid, sig in preloaded.items():
            signal_by_qid[qid] = sig

        if needs_llm:
            api_key = settings.openai_api_key
            model = settings.mapping_classification_model
            workers = min(_PARALLEL_WORKERS, len(needs_llm))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(_classify_one_thread_safe, qid, text, model, api_key): qid
                    for qid, text in needs_llm
                }
                for future in as_completed(futures):
                    qid = futures[future]
                    try:
                        _, parsed, raw = future.result()
                    except Exception:
                        parsed, raw = None, None
                    quality = "llm_structured" if parsed else "heuristic_fallback"
                    from app.models.question_mapping_signal import QuestionMappingSignal

                    sig = QuestionMappingSignal(
                        question_id=qid,
                        workspace_id=ws,
                        questionnaire_id=qnr_id,
                        framework_labels_json=json.dumps(parsed["frameworks"]) if parsed else None,
                        subject_labels_json=json.dumps(parsed["subjects"]) if parsed else None,
                        raw_llm_json=raw,
                        model=model,
                        prompt_version=prompt_ver,
                        mapping_quality=quality,
                        created_at=datetime.now(timezone.utc),
                    )
                    db.add(sig)
                    signal_by_qid[qid] = sig
                    if parsed:
                        classification_calls += 1

    # Phase 2: tag-based matching — match question subjects/frameworks to document tags
    # (No heuristic scoring — both questions and documents are LLM-tagged)
    from app.models.tag import DocumentTag, Tag

    doc_tags_raw = (
        db.query(DocumentTag.document_id, Tag.category, Tag.key, Tag.id)
        .join(Tag, DocumentTag.tag_id == Tag.id)
        .filter(DocumentTag.workspace_id == ws, Tag.category.in_(["framework", "topic"]))
        .all()
    )
    docs_by_tag_key: dict[str, set[int]] = {}
    tag_id_by_key: dict[str, int] = {}
    for doc_id, cat, key, tag_id in doc_tags_raw:
        docs_by_tag_key.setdefault(key, set()).add(doc_id)
        tag_id_by_key[key] = tag_id

    for q in eligible:
        sig = signal_by_qid.get(q.id)
        q_subjects: list[str] = []
        q_frameworks: list[str] = []
        if sig and getattr(sig, "mapping_quality", "") == "llm_structured":
            try:
                q_subjects = json.loads(sig.subject_labels_json or "[]")
            except Exception:
                pass
            try:
                q_frameworks = json.loads(sig.framework_labels_json or "[]")
            except Exception:
                pass

        matched_tag_id = None
        confidence = 0.0
        from app.services.registry_metadata import SUBJECT_AREA_LABEL_TO_KEY

        for subj_label in q_subjects:
            subj_key = SUBJECT_AREA_LABEL_TO_KEY.get(
                subj_label, subj_label.lower().replace(" ", "_")
            )
            if subj_key in docs_by_tag_key:
                matched_tag_id = tag_id_by_key.get(subj_key)
                confidence = 0.75
                break
        if matched_tag_id is None:
            for fw_label in q_frameworks:
                fw_key = fw_label.lower().replace(" ", "")
                if fw_key in docs_by_tag_key:
                    matched_tag_id = tag_id_by_key.get(fw_key)
                    confidence = 0.70
                    break

        if q.id in existing_by_qid:
            row = existing_by_qid[q.id]
            row.preferred_control_id = None
            row.preferred_tag_id = matched_tag_id
            row.confidence = confidence
            row.source = "ai"
            row.status = "suggested"
            row.approved = False
            row.updated_at = datetime.now(timezone.utc)
            updated += 1
        else:
            row = QuestionMappingPreference(
                workspace_id=ws,
                questionnaire_id=qnr_id,
                question_id=q.id,
                normalized_question_text=(q.text or "")[:2000],
                preferred_control_id=None,
                preferred_tag_id=matched_tag_id,
                source="ai",
                confidence=confidence,
                status="suggested",
                approved=False,
                created_by_user_id=session.get("user_id"),
            )
            db.add(row)
            created += 1

    if classification_calls > 0:
        try:
            record_mapping_calls(db, ws, classification_calls)
        except Exception:
            pass

    if mapping_timing_enabled():
        _t_commit = time.perf_counter()
    db.commit()
    _commit_ms = (time.perf_counter() - _t_commit) * 1000 if mapping_timing_enabled() else 0.0
    _total_ms = (time.perf_counter() - _t_gen_start) * 1000 if mapping_timing_enabled() else 0.0
    _log.info(
        "generate_mappings qnr=%s created=%s updated=%s skipped=%s classification_calls=%s",
        qnr_id,
        created,
        updated,
        skipped,
        classification_calls,
    )
    audit_log(
        "mapping.generate",
        email=session.get("email"),
        workspace_id=ws,
        resource_type="questionnaire",
        resource_id=qnr_id,
        details={
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "classification_calls": classification_calls,
            "mode": settings.mapping_mode,
        },
    )
    out: dict = {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "total_questions": len(questions),
        "classification_calls": classification_calls,
    }
    if mapping_timing_enabled():
        mt = get_mapping_timing_snapshot()
        rp = get_rerank_perf_snapshot()
        n_will = int(rp["rows_will_call_llm"])
        avg_c = (rp["candidate_sum"] / n_will) if n_will else 0.0
        _log.info(
            "MAPPING_TIMING qnr=%s total_ms=%.1f commit_ms=%.1f heuristic_ms=%.1f rerank_ms=%.1f wc_lookup_ms=%.1f "
            "rows_fc_hits=%d will_rerank_rows=%d avg_candidates=%.2f llm_http_calls=%d",
            qnr_id,
            _total_ms,
            _commit_ms,
            float(mt["heuristic_ms"]),
            float(mt["rerank_ms"]),
            float(mt["wc_lookup_ms"]),
            int(mt["rows_fc_hits"]),
            n_will,
            avg_c,
            int(rp["llm_http_calls"]),
        )
        out["_mapping_timing"] = {
            "total_ms": round(_total_ms, 1),
            "commit_ms": round(_commit_ms, 1),
            "heuristic_ms": round(float(mt["heuristic_ms"]), 1),
            "rerank_ms": round(float(mt["rerank_ms"]), 1),
            "wc_lookup_ms": round(float(mt["wc_lookup_ms"]), 1),
            "rows_fc_hits": int(mt["rows_fc_hits"]),
            "will_rerank_rows": n_will,
            "avg_candidates": round(avg_c, 2),
            "llm_http_calls": int(rp["llm_http_calls"]),
        }
    return out


@router.get("/{qnr_id}/mappings")
def list_questionnaire_mappings(
    qnr_id: int,
    include_suggested_evidence: bool = Query(
        False,
        description="If true, run retrieval-based suggested evidence per row (embed + search; very slow for large questionnaires).",
    ),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """List question→control mappings for policy / gap review, joined with the question text.

    Default omits suggested_evidence computation so large questionnaires return quickly;
    use GET /mappings/{mapping_id}/suggested-evidence for one row, or pass include_suggested_evidence=true.
    """
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    qnr = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id == qnr_id,
            Questionnaire.workspace_id == ws,
            Questionnaire.deleted_at.is_(None),
        )
        .first()
    )
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")

    mappings = (
        db.query(QuestionMappingPreference)
        .filter(
            QuestionMappingPreference.questionnaire_id == qnr_id,
            QuestionMappingPreference.workspace_id == ws,
        )
        .order_by(QuestionMappingPreference.question_id)
        .all()
    )

    questions = db.query(Question).filter(Question.questionnaire_id == qnr_id).all()
    q_map = {q.id: q for q in questions}

    ctrl_ids = [m.preferred_control_id for m in mappings]
    evidence_by_control = batch_supporting_evidence_for_workspace_controls(db, ws, ctrl_ids)

    wc_ids = sorted({int(x) for x in ctrl_ids if x is not None})
    wc_by_id: dict[int, WorkspaceControl] = {}
    fc_by_id: dict[int, FrameworkControl] = {}
    if wc_ids:
        for wc in (
            db.query(WorkspaceControl)
            .filter(WorkspaceControl.workspace_id == ws, WorkspaceControl.id.in_(wc_ids))
            .all()
        ):
            wc_by_id[wc.id] = wc
        fc_ids = {wc.framework_control_id for wc in wc_by_id.values() if wc.framework_control_id}
        if fc_ids:
            for fc in db.query(FrameworkControl).filter(FrameworkControl.id.in_(fc_ids)).all():
                fc_by_id[fc.id] = fc

    from app.services.framework_catalog import display_name_for_framework

    framework_names_by_id = {f.id: display_name_for_framework(f) for f in db.query(Framework).all()}

    result = []
    for m in mappings:
        d = _mapping_to_dict(m)
        q = q_map.get(m.question_id)
        qtext = q.text if q else m.normalized_question_text
        d["question_text"] = qtext
        d["question_section"] = q.section if q else None
        cid = m.preferred_control_id
        linked = evidence_by_control.get(int(cid), []) if cid is not None else []
        d["supporting_evidence"] = linked
        wc_row = wc_by_id.get(int(cid)) if cid is not None else None
        fc_row = (
            fc_by_id.get(wc_row.framework_control_id)
            if wc_row and wc_row.framework_control_id
            else None
        )
        fw_name = framework_names_by_id.get(fc_row.framework_id) if fc_row else None
        d["match_keywords"] = match_keywords_for_mapping_row(
            qtext or "", wc_row, fc_row, framework_name=fw_name
        )

        excl_docs = {int(x["document_id"]) for x in linked if x.get("document_id")}
        if include_suggested_evidence and cid is not None and (not linked):
            d["suggested_evidence"] = suggest_documents_for_mapping_review(
                db,
                ws,
                qtext or "",
                int(cid),
                exclude_document_ids=excl_docs,
                limit=3,
            )
        else:
            d["suggested_evidence"] = []
        result.append(d)

    # Count rows with a real control id (matches serialized mappings / UI "Mapped").
    mapped_count = sum(1 for d in result if d.get("preferred_control_id") is not None)
    return {
        "mappings": result,
        "total_questions": len(questions),
        "mapped_count": mapped_count,
        "mapping_preferred_subject_areas": _mapping_subject_areas_response(qnr),
    }


@router.get("/{qnr_id}/mappings/{mapping_id}/suggested-evidence")
def get_mapping_suggested_evidence(
    qnr_id: int,
    mapping_id: int,
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Retrieval-based document suggestions for one mapping (embed + search). Use for lazy load after list."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    qnr = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id == qnr_id,
            Questionnaire.workspace_id == ws,
            Questionnaire.deleted_at.is_(None),
        )
        .first()
    )
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")

    m = (
        db.query(QuestionMappingPreference)
        .filter(
            QuestionMappingPreference.id == mapping_id,
            QuestionMappingPreference.questionnaire_id == qnr_id,
            QuestionMappingPreference.workspace_id == ws,
        )
        .first()
    )
    if not m:
        raise HTTPException(status_code=404, detail="Mapping not found")

    q = db.query(Question).filter(Question.id == m.question_id).first() if m.question_id else None
    qtext = q.text if q else m.normalized_question_text
    cid = m.preferred_control_id
    if cid is None:
        return {"suggested_evidence": []}

    linked = batch_supporting_evidence_for_workspace_controls(db, ws, [cid]).get(int(cid), [])
    excl_docs = {int(x["document_id"]) for x in linked if x.get("document_id")}
    if linked:
        return {"suggested_evidence": []}

    suggested = suggest_documents_for_mapping_review(
        db,
        ws,
        qtext or "",
        int(cid),
        exclude_document_ids=excl_docs,
        limit=3,
    )
    return {"suggested_evidence": suggested}


class MappingUpdate(BaseModel):
    status: str | None = None
    preferred_control_id: int | None = None
    preferred_framework_key: str | None = None
    preferred_tag_id: int | None = None


@router.patch("/{qnr_id}/mappings/{mapping_id}")
def update_questionnaire_mapping(
    qnr_id: int,
    mapping_id: int,
    body: MappingUpdate,
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    """Update a single mapping — approve, reject, or manually override."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    # Validate the active parent and every new reference before changing any
    # mapping field. Zero retains the existing explicit-clear behavior.
    require_refs(
        db,
        ws,
        [
            ("questionnaire", qnr_id),
            ("control", body.preferred_control_id or None),
            ("tag", body.preferred_tag_id or None),
        ],
    )
    m = (
        db.query(QuestionMappingPreference)
        .filter(
            QuestionMappingPreference.id == mapping_id,
            QuestionMappingPreference.questionnaire_id == qnr_id,
            QuestionMappingPreference.workspace_id == ws,
        )
        .first()
    )
    if not m:
        raise HTTPException(status_code=404, detail="Mapping not found")

    valid_statuses = {"suggested", "approved", "rejected", "manual"}
    if body.status is not None:
        if body.status not in valid_statuses:
            raise HTTPException(
                status_code=400, detail=f"Invalid status. Allowed: {sorted(valid_statuses)}"
            )
        m.status = body.status
        m.approved = body.status in ("approved", "manual")

    if body.preferred_control_id is not None:
        m.preferred_control_id = body.preferred_control_id or None
        if m.status == "suggested":
            m.status = "manual"
            m.source = "manual"
            m.approved = True

    if body.preferred_framework_key is not None:
        m.preferred_framework_key = body.preferred_framework_key or None

    if body.preferred_tag_id is not None:
        m.preferred_tag_id = body.preferred_tag_id or None

    m.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(m)
    return _mapping_to_dict(m)


@router.post("/{qnr_id}/mappings/{mapping_id}/regenerate")
def regenerate_single_mapping(
    qnr_id: int,
    mapping_id: int,
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    """Regenerate AI suggestion for a single question's mapping."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    m = (
        db.query(QuestionMappingPreference)
        .filter(
            QuestionMappingPreference.id == mapping_id,
            QuestionMappingPreference.questionnaire_id == qnr_id,
            QuestionMappingPreference.workspace_id == ws,
        )
        .first()
    )
    if not m:
        raise HTTPException(status_code=404, detail="Mapping not found")

    qnr = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id == qnr_id,
            Questionnaire.workspace_id == ws,
            Questionnaire.deleted_at.is_(None),
        )
        .first()
    )
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")

    q = db.query(Question).filter(Question.id == m.question_id).first()
    text = q.text if q else (m.normalized_question_text or "")

    signal = classify_question_signal(
        db,
        m.question_id,
        text,
        ws,
        questionnaire_id=qnr_id,
        force=True,
    )

    q_subjects: list[str] = []
    if signal and getattr(signal, "mapping_quality", "") == "llm_structured":
        try:
            q_subjects = json.loads(signal.subject_labels_json or "[]")
        except Exception:
            pass

    from app.models.tag import DocumentTag, Tag
    from app.services.registry_metadata import SUBJECT_AREA_LABEL_TO_KEY

    matched_tag_id = None
    confidence = 0.0
    for subj_label in q_subjects:
        subj_key = SUBJECT_AREA_LABEL_TO_KEY.get(subj_label, subj_label.lower().replace(" ", "_"))
        tag = db.query(Tag).filter(Tag.key == subj_key, Tag.category == "topic").first()
        if tag:
            has_docs = (
                db.query(DocumentTag)
                .filter(DocumentTag.tag_id == tag.id, DocumentTag.workspace_id == ws)
                .first()
            )
            if has_docs:
                matched_tag_id = tag.id
                confidence = 0.75
                break

    m.preferred_control_id = None
    m.preferred_tag_id = matched_tag_id
    m.confidence = confidence
    m.source = "ai"
    m.status = "suggested"
    m.approved = False
    m.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(m)
    return _mapping_to_dict(m)
