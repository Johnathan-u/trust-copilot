"""Cancel a job, or queue an authorized manual retry (TC-10-004).

Cancellation and retry are conditional on the locked row. A terminal status that is not
eligible is left as it is. Actor, prior error, and prior attempt are stored on the audit
event, not on new columns.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import persist_audit
from app.models import Job, JobStatus

_OPEN = frozenset({JobStatus.QUEUED.value, JobStatus.RUNNING.value})
_RETRYABLE = frozenset({JobStatus.FAILED.value, JobStatus.CANCELLED.value})
CANCELLED_CODE = "cancelled"
CANCELLED_MESSAGE = "Cancelled before the job finished."


def _lock(session: Session, job_id: int, workspace_id: int) -> Job | None:
    return (
        session.query(Job)
        .filter(Job.id == job_id, Job.workspace_id == workspace_id)
        .with_for_update()
        .first()
    )


def _prior(job: Job) -> dict:
    error = job.error
    return {
        "prior_status": job.status,
        "prior_error_code": job.error_code,
        "prior_error": None if error is None else str(error)[:1000],
        "prior_attempt": int(job.attempt or 0),
    }


def cancel_job(
    session: Session,
    job_id: int,
    *,
    workspace_id: int,
    actor_user_id: int | None,
    actor_email: str | None,
) -> tuple[str, Job | None]:
    """Lock one job and cancel it when it is queued or running.

    Returns ``(already, job)`` when it is already cancelled (no second audit),
    ``(terminal, job)`` when it is completed or failed, ``(missing, None)`` when
    this workspace has no such row, or ``(cancelled, job)`` after the audit commits.
    """
    job = _lock(session, job_id, workspace_id)
    if job is None:
        return "missing", None
    if job.status == JobStatus.CANCELLED.value:
        session.rollback()
        return "already", job
    if job.status not in _OPEN:
        session.rollback()
        return "terminal", job
    prior = _prior(job)
    job.status = JobStatus.CANCELLED.value
    job.lease_owner = None
    job.lease_expires_at = None
    job.next_attempt_at = None
    job.completed_at = datetime.now(timezone.utc)
    if not job.error_code:
        job.error_code = CANCELLED_CODE
        job.error = CANCELLED_MESSAGE
    session.flush()
    persist_audit(
        session,
        "job.cancelled",
        user_id=actor_user_id,
        email=actor_email,
        workspace_id=job.workspace_id,
        resource_type="job",
        resource_id=job.id,
        details={"actor_user_id": actor_user_id, **prior},
    )
    session.refresh(job)
    return "cancelled", job


def retry_job(
    session: Session,
    job_id: int,
    *,
    workspace_id: int,
    actor_user_id: int | None,
    actor_email: str | None,
) -> tuple[str, Job | None]:
    """Re-queue a failed or cancelled job as a fresh attempt.

    ``attempt`` goes back to 0 so the next claim is attempt 1. The audit keeps the
    prior attempt. Returns ``(not_retryable, job)`` for any other status.
    """
    job = _lock(session, job_id, workspace_id)
    if job is None:
        return "missing", None
    if job.status not in _RETRYABLE:
        session.rollback()
        return "not_retryable", job
    if job.idempotency_key:
        other = (
            session.query(Job.id)
            .filter(
                Job.workspace_id == job.workspace_id,
                Job.kind == job.kind,
                Job.idempotency_key == job.idempotency_key,
                Job.id != job.id,
                Job.status.in_((JobStatus.QUEUED.value, JobStatus.RUNNING.value)),
            )
            .first()
        )
        if other is not None:
            session.rollback()
            return "conflict", None
    prior = _prior(job)
    job.status = JobStatus.QUEUED.value
    job.attempt = 0
    job.next_attempt_at = None
    job.completed_at = None
    job.lease_owner = None
    job.lease_expires_at = None
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return "conflict", None
    persist_audit(
        session,
        "job.manual_retry",
        user_id=actor_user_id,
        email=actor_email,
        workspace_id=job.workspace_id,
        resource_type="job",
        resource_id=job.id,
        details={"actor_user_id": actor_user_id, **prior},
    )
    session.refresh(job)
    return "retried", job
