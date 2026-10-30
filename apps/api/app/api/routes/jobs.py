"""Job status API (JOB-03).

Exposes lifecycle fields for UI polling. Status values match ``JobStatus`` in ``app.models.job``:
``queued`` → ``running`` → ``completed`` | ``failed`` | ``cancelled``.
``charge_uncertain`` is true when a paid provider call of an interrupted or failed attempt may have been charged
(TC-10-003). A no-op run records ``result.outcome`` = ``already_applied`` | ``reconciled`` | ``superseded``.
For ``generate_answers`` jobs, ``result`` may contain JSON ``{"generated": N, "total": M}`` while running.
Failed jobs expose ``error_code`` and ``error_detail`` (``ApiError``: code/message/request_id/retryable).

TC-10-002 (additive): ``error_code`` (the column TC-11-001 added) is the typed class of the last failure: the
TC-11-001 ``model_*`` code for model-provider failures, otherwise a ``app.core.job_errors`` code (``rate_limited``,
``database_unavailable``, ``bad_input`` ...). ``retryable`` says whether that class is retried. A ``queued`` job with ``retry_scheduled`` true is waiting for
``next_attempt_at`` after a failed attempt (``attempt`` of ``max_attempts``; ``error`` describes it). A ``failed``
job with ``retries_exhausted`` true used every attempt on a transient error; it is never reported as completed.
"""

import json
import logging
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.api_errors import (
    IDEMPOTENCY_CONFLICT_CODE,
    IDEMPOTENCY_CONFLICT_MESSAGE,
    ApiError,
    api_error_response,
    current_request_id,
    job_error_payload,
)
from app.core.auth_deps import require_can_admin, require_can_review
from app.core.database import get_db
from app.core.job_errors import effective_max_attempts, is_known_code, is_retryable_code
from app.models import Document, Job, JobKind, JobStatus, Questionnaire
from app.services.job_control import cancel_job, retry_job
from app.services.job_effects import charge_uncertain

router = APIRouter(prefix="/jobs", tags=["jobs"])
_log = logging.getLogger(__name__)

_NOT_CANCELLABLE = "This job is already finished and cannot be cancelled."
_NOT_RETRYABLE = "Only a failed or cancelled job can be retried."


def _conflict(request: Request, code: str, message: str) -> JSONResponse:
    error = ApiError(
        code=code,
        message=message,
        request_id=current_request_id(request),
        retryable=False,
    )
    return api_error_response(error, 409)


def _public_job(request: Request, db: Session, job: Job) -> dict:
    result_payload = None
    if job.result:
        try:
            result_payload = json.loads(job.result)
        except json.JSONDecodeError:
            result_payload = job.result
    max_attempts = effective_max_attempts(job.max_attempts)
    retryable = is_retryable_code(job.error_code)
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "attempt": job.attempt,
        "error": job.error,
        # TC-11-001: stable typed failure (ApiError schema); never contains provider payloads.
        "error_code": job.error_code,
        "error_detail": job_error_payload(job, current_request_id(request)),
        # TC-10-002: retry state (error_code is shared with TC-11-001).
        "max_attempts": max_attempts,
        "retryable": retryable if job.error_code else None,
        "next_attempt_at": job.next_attempt_at.isoformat() if job.next_attempt_at else None,
        "retry_scheduled": job.status == JobStatus.QUEUED.value and job.next_attempt_at is not None,
        "retries_exhausted": job.status == JobStatus.FAILED.value
        and retryable
        and int(job.attempt or 0) >= max_attempts,
        "result": result_payload,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        # TC-10-003: a provider call of an interrupted/failed attempt may have been charged.
        "charge_uncertain": charge_uncertain(db, job.id),
    }


def _same_workspace(session: dict, workspace_id: int) -> None:
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=404, detail="Job not found")


def _history_json(raw: str | None) -> dict:
    try:
        value = json.loads(raw) if raw else {}
    except (TypeError, ValueError, RecursionError):
        return {}
    return value if isinstance(value, dict) else {}


def _history_object(db: Session, job: Job, payload: dict) -> dict | None:
    # A job's stored input is not authority. Re-check its current parent; no titles,
    # storage addresses, download grants or arbitrary payload URLs are returned.
    if job.kind in (JobKind.INDEX_DOCUMENT.value, JobKind.PARSE_EVIDENCE.value):
        model, field, object_type = Document, "document_id", "document"
    elif job.kind in (
        JobKind.PARSE_QUESTIONNAIRE.value,
        JobKind.GENERATE_ANSWERS.value,
        JobKind.EXPORT.value,
    ):
        model, field, object_type = Questionnaire, "questionnaire_id", "questionnaire"
    else:
        return None
    object_id = payload.get(field)
    # Reject bools, coerced strings and values outside the database integer range.
    if type(object_id) is not int or not 0 < object_id <= 2147483647:
        return None
    row = (
        db.query(model.id)
        .filter(
            model.id == object_id,
            model.workspace_id == job.workspace_id,
            model.deleted_at.is_(None),
        )
        .first()
    )
    return {"type": object_type, "id": row.id} if row is not None else None


def _history_job(request: Request, db: Session, job: Job) -> dict:
    result = _history_json(job.result)
    progress = None
    if job.kind == JobKind.GENERATE_ANSWERS.value:
        generated, total = result.get("generated"), result.get("total")
        if (
            type(generated) is int
            and type(total) is int
            and 0 <= generated <= total <= 9007199254740991
        ):
            progress = {"generated": generated, "total": total}
    outcome = result.get("outcome")
    if outcome not in ("already_applied", "reconciled", "superseded"):
        outcome = None
    max_attempts = effective_max_attempts(job.max_attempts)
    retryable = is_retryable_code(job.error_code)
    # Keep the existing typed error catalog/fallback, but never copy a stored
    # request_id from untrusted payload JSON into this collection response.
    safe_error = SimpleNamespace(status=job.status, error_code=job.error_code, payload=None)
    return {
        "id": job.id,
        "kind": job.kind if job.kind in {kind.value for kind in JobKind} else None,
        "status": job.status if job.status in {status.value for status in JobStatus} else None,
        "attempt": job.attempt,
        "max_attempts": max_attempts,
        "error_code": (
            job.error_code
            if is_known_code(job.error_code) or job.error_code == "cancelled"
            else None
        ),
        "error_detail": job_error_payload(safe_error, current_request_id(request)),
        "retryable": retryable if job.error_code else None,
        "next_attempt_at": job.next_attempt_at.isoformat() if job.next_attempt_at else None,
        "retry_scheduled": job.status == JobStatus.QUEUED.value and job.next_attempt_at is not None,
        "retries_exhausted": job.status == JobStatus.FAILED.value
        and retryable
        and int(job.attempt or 0) >= max_attempts,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "charge_uncertain": charge_uncertain(db, job.id),
        "progress": progress,
        "outcome": outcome,
        "object_ref": _history_object(db, job, _history_json(job.payload)),
    }


@router.get("")
def list_jobs(
    request: Request,
    workspace_id: int = Query(..., description="Required for workspace isolation"),
    limit: int = Query(25, ge=1, le=100),
    before_id: int | None = Query(None, gt=0),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """List persisted job history, newest first, with authorized current object references."""
    _same_workspace(session, workspace_id)
    query = db.query(Job).filter(Job.workspace_id == workspace_id)
    if before_id is not None:
        query = query.filter(Job.id < before_id)
    rows = query.order_by(Job.id.desc()).limit(limit + 1).all()
    page = rows[:limit]
    return {
        "items": [_history_job(request, db, job) for job in page],
        "next_before_id": page[-1].id if len(rows) > limit else None,
    }


@router.get("/{job_id}")
def get_job(
    request: Request,
    job_id: int,
    workspace_id: int = Query(..., description="Required for workspace isolation"),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Get job status for UI polling. Requires auth and workspace access."""
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    job = db.query(Job).filter(Job.id == job_id, Job.workspace_id == workspace_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _log.info(
        "API: job status fetched job_id=%s kind=%s status=%s workspace_id=%s",
        job.id,
        job.kind,
        job.status,
        workspace_id,
    )
    return _public_job(request, db, job)


@router.post("/{job_id}/cancel")
def cancel_job_route(
    request: Request,
    job_id: int,
    workspace_id: int = Query(..., description="Required for workspace isolation"),
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Cancel a queued, running, or retrying job.

    A job that is already cancelled is returned unchanged. A completed or failed job is rejected.
    """
    _same_workspace(session, workspace_id)
    kind, job = cancel_job(
        db,
        job_id,
        workspace_id=workspace_id,
        actor_user_id=session.get("user_id"),
        actor_email=session.get("email"),
    )
    if kind == "missing" or job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if kind == "terminal":
        return _conflict(request, "job_not_cancellable", _NOT_CANCELLABLE)
    return _public_job(request, db, job)


@router.post("/{job_id}/retry")
def retry_job_route(
    request: Request,
    job_id: int,
    workspace_id: int = Query(..., description="Required for workspace isolation"),
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Queue another attempt of a failed or cancelled job.

    The actor, the prior error, and the prior attempt are recorded on the audit event.
    """
    _same_workspace(session, workspace_id)
    kind, job = retry_job(
        db,
        job_id,
        workspace_id=workspace_id,
        actor_user_id=session.get("user_id"),
        actor_email=session.get("email"),
    )
    if kind == "missing":
        raise HTTPException(status_code=404, detail="Job not found")
    if kind == "not_retryable":
        return _conflict(request, "job_not_retryable", _NOT_RETRYABLE)
    if kind == "conflict":
        return _conflict(request, IDEMPOTENCY_CONFLICT_CODE, IDEMPOTENCY_CONFLICT_MESSAGE)
    return _public_job(request, db, job)
