"""Idempotent job side effects (TC-10-003).

The worker does not promise exactly-once execution (PRODUCT_SPEC job contract): a job can run again after a
crash, a lease takeover (TC-10-001) or a retry (TC-10-002). This module makes re-execution safe instead:

* ``enqueue_job`` dedupes identical work at enqueue time: at most one QUEUED job per
  (workspace_id, kind, idempotency_key), enforced by a partial unique index.
* ``JobEffects`` is the per-job side-effect ledger used by the handlers:
  - ``is_applied(effect)`` / ``mark_applied(effect)``: the marker is added to the caller's session, so it
    commits atomically with the effect. A re-run sees the marker and skips the effect.
  - ``provider_call_started(provider)``: committed on a separate connection BEFORE a paid provider call;
    ``settle(provider)`` records the attempt's outcome. Unsettled calls are marked ``uncertain``
    (``reconcile_previous_attempts`` on the next claim, ``mark_unsettled_uncertain`` on failure), so a
    possible provider charge for discarded work is recorded rather than silently lost.

The interface is deliberately small so TC-10-001 (leases/heartbeats), TC-10-002 (retries) and TC-10-005
(outbox/storage reconciliation) can build on it without changing call sites.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Job, JobStatus
from app.models.job_effect import (
    EFFECT_APPLIED,
    EFFECT_SETTLED,
    EFFECT_STARTED,
    EFFECT_UNCERTAIN,
    JobEffect,
)

logger = logging.getLogger(__name__)

PROVIDER_PREFIX = "provider:"
# One original insert plus one retry when the race winner already left QUEUED (TC-10-003a).
_ENQUEUE_ATTEMPTS = 2


def job_idempotency_key(kind: str, *parts: Any) -> str:
    """Deterministic, bounded dedupe key for a job kind and its identifying inputs."""
    digest = hashlib.sha256(
        json.dumps([kind, *parts], sort_keys=True, default=str).encode()
    ).hexdigest()
    return f"{kind}:{digest[:48]}"


def enqueue_job(
    db: Session,
    *,
    workspace_id: int,
    kind: str,
    payload: dict,
    idempotency_key: str | None = None,
    input_version: str | None = None,
) -> tuple[Job, bool]:
    """Create a QUEUED job, or return the already-QUEUED job with the same key. Returns (job, created).

    Only QUEUED jobs are deduped: a RUNNING job may already have read its input, so a later request must
    get its own job. Commits.

    Race handling (TC-10-003a): when a concurrent identical enqueue wins the partial unique index, the winner
    is returned. If the winner has already left QUEUED by the time we look it up (a worker claimed it), the
    unique slot is free again, so the insert is retried once instead of surfacing the IntegrityError as a 500.
    """
    for attempt in range(_ENQUEUE_ATTEMPTS):
        if idempotency_key:
            existing = _queued_with_key(db, workspace_id, kind, idempotency_key)
            if existing is not None:
                return existing, False
        job = Job(
            workspace_id=workspace_id,
            kind=kind,
            status=JobStatus.QUEUED.value,
            payload=json.dumps(payload),
            idempotency_key=idempotency_key,
            input_version=input_version,
        )
        try:
            with db.begin_nested():
                db.add(job)
                db.flush()
        except IntegrityError:
            if not idempotency_key:
                raise
            # Lost the race against a concurrent identical enqueue: return the winner if still queued.
            existing = _queued_with_key(db, workspace_id, kind, idempotency_key)
            if existing is not None:
                db.commit()
                return existing, False
            if attempt + 1 >= _ENQUEUE_ATTEMPTS:
                raise
            logger.info(
                "enqueue_job: race winner already left queued; retrying insert once "
                "(workspace_id=%s kind=%s)",
                workspace_id,
                kind,
            )
            continue
        db.commit()
        db.refresh(job)
        return job, True
    raise AssertionError("unreachable")  # pragma: no cover


def _queued_with_key(db: Session, workspace_id: int, kind: str, key: str) -> Job | None:
    return (
        db.query(Job)
        .filter(
            Job.workspace_id == workspace_id,
            Job.kind == kind,
            Job.idempotency_key == key,
            Job.status == JobStatus.QUEUED.value,
        )
        .first()
    )


class JobEffects:
    """Side-effect ledger for one job execution attempt (see module docstring)."""

    def __init__(self, db: Session, job: Job):
        self.db = db
        self.job = job

    # -- durable effects (atomic with the caller's commit) -------------------------------------------
    def is_applied(self, effect: str) -> bool:
        return (
            self.db.query(JobEffect.id)
            .filter(
                JobEffect.job_id == self.job.id,
                JobEffect.effect == effect,
                JobEffect.attempt == 0,
                JobEffect.state == EFFECT_APPLIED,
            )
            .first()
            is not None
        )

    def mark_applied(self, effect: str, detail: dict | None = None) -> None:
        """Add the applied marker to the caller's session; it commits with the effect itself."""
        self.db.add(
            JobEffect(
                job_id=self.job.id,
                workspace_id=self.job.workspace_id,
                effect=effect,
                attempt=0,
                state=EFFECT_APPLIED,
                detail=json.dumps({**(detail or {}), "by_attempt": self.job.attempt}),
            )
        )

    def applied_detail(self, effect: str) -> dict:
        row = (
            self.db.query(JobEffect)
            .filter(
                JobEffect.job_id == self.job.id, JobEffect.effect == effect, JobEffect.attempt == 0
            )
            .first()
        )
        if not row or not row.detail:
            return {}
        try:
            return json.loads(row.detail)
        except ValueError:
            return {}

    # -- provider calls (charge tracking) -------------------------------------------------------------
    def provider_call_started(self, provider: str) -> None:
        """Commit a ``started`` marker on a separate connection before a paid call (idempotent per attempt).

        A separate connection is used so the marker survives a rollback or crash of the main transaction,
        and so the main transaction (which may hold uncommitted effects) is not committed early.
        """
        stmt = text(
            "INSERT INTO job_effects (job_id, workspace_id, effect, attempt, state, created_at, updated_at) "
            "VALUES (:job_id, :ws, :effect, :attempt, :state, NOW() AT TIME ZONE 'utc', NOW() AT TIME ZONE 'utc') "
            "ON CONFLICT (job_id, effect, attempt) DO NOTHING"
        )
        params = {
            "job_id": self.job.id,
            "ws": self.job.workspace_id,
            "effect": PROVIDER_PREFIX + provider,
            "attempt": int(self.job.attempt or 0),
            "state": EFFECT_STARTED,
        }
        with self.db.get_bind().connect() as conn:
            conn.execute(stmt, params)
            conn.commit()

    def settle(self, provider: str, detail: dict | None = None) -> None:
        """Mark this attempt's provider calls settled (in the caller's session)."""
        row = (
            self.db.query(JobEffect)
            .filter(
                JobEffect.job_id == self.job.id,
                JobEffect.effect == PROVIDER_PREFIX + provider,
                JobEffect.attempt == int(self.job.attempt or 0),
            )
            .first()
        )
        if row is None:
            return
        row.state = EFFECT_SETTLED
        if detail:
            row.detail = json.dumps(detail)


def reconcile_previous_attempts(db: Session, job: Job) -> int:
    """On claim: earlier attempts' provider calls that never settled are now ``uncertain``. Commits."""
    n = (
        db.query(JobEffect)
        .filter(
            JobEffect.job_id == job.id,
            JobEffect.effect.like(PROVIDER_PREFIX + "%"),
            JobEffect.attempt < int(job.attempt or 0),
            JobEffect.state == EFFECT_STARTED,
        )
        .update(
            {
                JobEffect.state: EFFECT_UNCERTAIN,
                JobEffect.detail: json.dumps({"reason": "attempt_interrupted"}),
            },
            synchronize_session=False,
        )
    )
    if n:
        db.commit()
        logger.warning(
            "job_effects: job_id=%s %s provider call(s) from interrupted attempts marked uncertain",
            job.id,
            n,
        )
    return n


def mark_unsettled_uncertain(db: Session, job: Job, reason: str = "attempt_failed") -> int:
    """On failure: this attempt's unsettled provider calls are ``uncertain``. Does not commit."""
    return (
        db.query(JobEffect)
        .filter(
            JobEffect.job_id == job.id,
            JobEffect.effect.like(PROVIDER_PREFIX + "%"),
            JobEffect.attempt == int(job.attempt or 0),
            JobEffect.state == EFFECT_STARTED,
        )
        .update(
            {JobEffect.state: EFFECT_UNCERTAIN, JobEffect.detail: json.dumps({"reason": reason})},
            synchronize_session=False,
        )
    )


def charge_uncertain(db: Session, job_id: int) -> bool:
    """True if any provider call of this job may have been charged without its result being kept."""
    return (
        db.query(JobEffect.id)
        .filter(JobEffect.job_id == job_id, JobEffect.state == EFFECT_UNCERTAIN)
        .first()
        is not None
    )
