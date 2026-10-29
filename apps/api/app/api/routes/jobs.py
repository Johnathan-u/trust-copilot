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
from app.core.job_errors import effective_max_attempts, is_retryable_code
from app.models import Job, JobStatus
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
