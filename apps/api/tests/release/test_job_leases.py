"""TC-10-001: periodic job leases and abandoned-job recovery.

On master, ``jobs`` has no lease columns. ``claim_job`` marks a row running and never stores an
owner token. A second ``claim_job`` will not take that row, and nothing sends it back through the
retry cap, so a killed worker leaves the job running. These tests fail on that code.

Fakes only: no network, no real keys, a side ``*_test`` database. Lease instants are the
database clock. Tests move ``lease_expires_at`` relative to ``now()``; they do not sleep.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import inspect, text

from app.core.job_errors import LEASE_EXPIRED
from app.core.job_lease import (
    JobLeaseHeartbeat,
    LeaseLost,
    install_commit_fence,
    lease_heartbeat_seconds,
    lease_seconds,
    renew_lease,
)

WS = 1
EFFECT = "synthetic_widget"
TABLES = ("jobs", "audit_events", "idempotency_keys", "job_effects", "workspaces")
DELETE_ORDER = ("job_effects", "jobs", "audit_events", "idempotency_keys", "workspaces")


def _set_lease_offset(session, job_id: int, seconds_from_now: float) -> None:
    """Move one job's expiry relative to the database clock. Negative means already expired."""
    session.execute(
        text(
            """
            UPDATE jobs
            SET lease_expires_at = now() + make_interval(secs => :seconds)
            WHERE id = :id
            """
        ),
        {"id": job_id, "seconds": seconds_from_now},
    )
    session.commit()
    session.expire_all()


def _seconds_left(session, job_id: int) -> float:
    session.expire_all()
    value = session.execute(
        text("SELECT EXTRACT(EPOCH FROM (lease_expires_at - now())) FROM jobs WHERE id = :id"),
        {"id": job_id},
    ).scalar()
    return float(value)


@pytest.fixture(autouse=True)
def _reset_lease_hooks():
    yield
    from app import worker
    from app.core import job_lease

    worker.set_clock(None)
    job_lease._clamp_logged = False
    job_lease._grace_clamp_logged = False


@pytest.fixture
def db(_ensure_test_data):
    """Snapshot every table this module writes. Delete only rows created by the test. No setval."""
    if not _ensure_test_data:
        pytest.skip("Postgres test DB unavailable")
    from app.core.database import SessionLocal

    session = SessionLocal()
    snap: dict[str, tuple[int, int]] = {}
    for table in TABLES:
        max_id, count = session.execute(
            text(f"SELECT COALESCE(MAX(id), 0), COUNT(*) FROM {table}")
        ).one()
        snap[table] = (int(max_id), int(count))
    session.commit()
    try:
        yield session
    finally:
        try:
            session.rollback()
        except Exception:
            pass
        try:
            session.close()
        except Exception:
            pass
        cleanup = SessionLocal()
        try:
            for table in DELETE_ORDER:
                cleanup.execute(
                    text(f"DELETE FROM {table} WHERE id > :max_id"),
                    {"max_id": snap[table][0]},
                )
            cleanup.commit()
            for table in TABLES:
                got = cleanup.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                assert int(got) == snap[table][1], table
        finally:
            cleanup.close()


def _only(job_id: int):
    from app import worker
    from app.models import Job

    real = worker.claimable_filter
    return patch.object(worker, "claimable_filter", lambda now=None: real(now) & (Job.id == job_id))


def _audits(db, job_id: int, action: str):
    from app.models.audit_event import AuditEvent

    return (
        db.query(AuditEvent)
        .filter(
            AuditEvent.resource_type == "job",
            AuditEvent.resource_id == str(job_id),
            AuditEvent.action == action,
        )
        .all()
    )


def _details(audit) -> dict:
    raw = audit.details
    if isinstance(raw, str):
        return json.loads(raw)
    return raw or {}


# ---------------------------------------------------------------------------------------------------------
# Configuration (no database)
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.unit
def test_lease_config_defaults_and_clamps(monkeypatch):
    monkeypatch.delenv("JOB_LEASE_SECONDS", raising=False)
    monkeypatch.delenv("JOB_LEASE_HEARTBEAT_SECONDS", raising=False)
    assert lease_seconds() == 60
    assert lease_heartbeat_seconds() == 15
    monkeypatch.setenv("JOB_LEASE_SECONDS", "nope")
    monkeypatch.setenv("JOB_LEASE_HEARTBEAT_SECONDS", "also-nope")
    assert lease_seconds() == 60
    assert lease_heartbeat_seconds() == 15
    monkeypatch.setenv("JOB_LEASE_SECONDS", "1")
    assert lease_seconds() == 10  # floor
    monkeypatch.setenv("JOB_LEASE_SECONDS", "99999")
    assert lease_seconds() == 3600  # ceiling
    monkeypatch.setenv("JOB_LEASE_SECONDS", "30")
    monkeypatch.setenv("JOB_LEASE_HEARTBEAT_SECONDS", "100")
    assert lease_heartbeat_seconds() * 2 <= lease_seconds()
    assert lease_heartbeat_seconds() == 15  # half of 30


@pytest.mark.unit
def test_null_lease_grace_defaults_and_clamps(monkeypatch):
    """The grace stays several times the lease, and an invalid value falls back to 3600."""
    from app.core.job_lease import null_lease_grace_seconds

    monkeypatch.delenv("JOB_LEASE_SECONDS", raising=False)
    monkeypatch.delenv("JOB_NULL_LEASE_GRACE_SECONDS", raising=False)
    assert null_lease_grace_seconds() == 3600
    monkeypatch.setenv("JOB_NULL_LEASE_GRACE_SECONDS", "nope")
    assert null_lease_grace_seconds() == 3600
    monkeypatch.setenv("JOB_LEASE_SECONDS", "60")
    monkeypatch.setenv("JOB_NULL_LEASE_GRACE_SECONDS", "10")
    assert null_lease_grace_seconds() == 300  # 5 times the lease
    monkeypatch.setenv("JOB_NULL_LEASE_GRACE_SECONDS", "999999")
    assert null_lease_grace_seconds() == 86400
    monkeypatch.setenv("JOB_LEASE_SECONDS", "3600")
    monkeypatch.setenv("JOB_NULL_LEASE_GRACE_SECONDS", "3600")
    assert null_lease_grace_seconds() == 18000  # raised to 5 times the longer lease


@pytest.mark.unit
def test_heartbeat_is_at_most_half_the_lease(monkeypatch):
    """A value under the lease still clamps when two beats would not fit."""
    monkeypatch.setenv("JOB_LEASE_SECONDS", "60")
    monkeypatch.setenv("JOB_LEASE_HEARTBEAT_SECONDS", "40")
    assert lease_seconds() == 60
    assert lease_heartbeat_seconds() == 30
    assert lease_heartbeat_seconds() * 2 <= lease_seconds()


@pytest.mark.unit
def test_heartbeat_loop_uses_injected_sleep_and_stops_when_renewal_fails():
    calls = {"n": 0}
    slept: list[float] = []

    def renew() -> bool:
        calls["n"] += 1
        return calls["n"] < 3

    def sleep(seconds: float) -> None:
        slept.append(seconds)

    heartbeat = JobLeaseHeartbeat(renew, interval_sec=5, sleep=sleep)
    heartbeat.run_until_stopped()
    assert calls["n"] == 3
    assert slept == [5, 5]
    assert heartbeat.beats == 2
    assert heartbeat.lost is True


@pytest.mark.unit
def test_heartbeat_loop_keeps_renewing_until_stopped():
    calls = {"n": 0}

    def renew() -> bool:
        calls["n"] += 1
        return True

    heartbeat = JobLeaseHeartbeat(renew, interval_sec=5, sleep=lambda _s: None)
    # The sleep stands in for the interval. Stop once four renewals have happened.
    original = heartbeat.run_until_stopped

    def stop_after_four() -> None:
        if calls["n"] >= 4:
            heartbeat.stop()

    heartbeat._sleep = lambda _s: stop_after_four()
    original()
    assert calls["n"] == 4
    assert heartbeat.lost is False
    assert heartbeat.beats == 4


# ---------------------------------------------------------------------------------------------------------
# Two workers, one lease
# ---------------------------------------------------------------------------------------------------------


def test_two_workers_cannot_own_the_same_lease(db):
    """AC1: exactly one of two concurrent claims receives the owner token."""
    from app import worker
    from app.core.database import SessionLocal
    from app.models import Job, JobStatus

    job = Job(
        workspace_id=WS,
        kind="parse_evidence",
        status=JobStatus.QUEUED.value,
        payload="{}",
        attempt=0,
        max_attempts=3,
    )
    db.add(job)
    db.commit()
    job_id = job.id
    barrier = threading.Barrier(2)
    results: list[tuple[int, str] | None] = []
    errors: list[BaseException] = []

    def claim() -> None:
        session = SessionLocal()
        try:
            barrier.wait(timeout=5)
            claimed = worker.claim_job(session)
            if claimed is None:
                results.append(None)
            else:
                results.append((claimed.id, claimed.lease_owner))
        except BaseException as exc:  # noqa: BLE001 - report the thread failure in the assertion
            errors.append(exc)
        finally:
            session.close()

    with _only(job_id):
        threads = [threading.Thread(target=claim), threading.Thread(target=claim)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
    assert errors == []
    assert len(results) == 2
    winners = [item for item in results if item is not None]
    assert len(winners) == 1
    assert winners[0][0] == job_id
    owner = winners[0][1]
    assert isinstance(owner, str) and len(owner) == 32
    db.expire_all()
    stored = db.get(Job, job_id)
    assert stored.status == JobStatus.RUNNING.value
    assert stored.lease_owner == owner
    assert stored.lease_expires_at is not None
    assert stored.attempt == 1
    # The loser, and any other token, cannot renew the winner's lease.
    expiry = stored.lease_expires_at
    assert (
        renew_lease(
            job_id,
            "f" * 32,
            extend_seconds=60,
            session_factory=SessionLocal,
        )
        is False
    )
    db.expire_all()
    assert db.get(Job, job_id).lease_expires_at == expiry
    assert (
        renew_lease(
            job_id,
            owner,
            extend_seconds=60,
            session_factory=SessionLocal,
        )
        is True
    )


def test_heartbeat_renews_only_for_the_current_owner(db):
    """AC1: heartbeats during long work keep the lease; a stale token cannot extend it."""
    from app import worker
    from app.core.database import SessionLocal
    from app.models import Job, JobStatus

    job = Job(
        workspace_id=WS,
        kind="parse_evidence",
        status=JobStatus.QUEUED.value,
        payload="{}",
        attempt=0,
        max_attempts=3,
    )
    db.add(job)
    db.commit()
    job_id = job.id
    with _only(job_id):
        claimed = worker.claim_job(db)
    owner = claimed.lease_owner
    assert lease_seconds() - 5 <= _seconds_left(db, job_id) <= lease_seconds() + 1

    def renew() -> bool:
        return renew_lease(
            job_id,
            owner,
            extend_seconds=lease_seconds(),
            session_factory=SessionLocal,
        )

    heartbeat = JobLeaseHeartbeat(
        renew, interval_sec=lease_heartbeat_seconds(), sleep=lambda _s: None
    )
    # A lease that is about to expire is pushed back out by the owner's heartbeat.
    _set_lease_offset(db, job_id, 5)
    short_expiry = db.get(Job, job_id).lease_expires_at
    assert heartbeat.beat_once() is True
    db.expire_all()
    extended = db.get(Job, job_id).lease_expires_at
    assert extended > short_expiry
    assert lease_seconds() - 5 <= _seconds_left(db, job_id) <= lease_seconds() + 1
    assert heartbeat.beat_once() is True
    assert heartbeat.lost is False
    assert heartbeat.beats == 2

    def stale() -> bool:
        return renew_lease(
            job_id,
            "a" * 32,
            extend_seconds=lease_seconds(),
            session_factory=SessionLocal,
        )

    stale_beat = JobLeaseHeartbeat(stale, interval_sec=15, sleep=lambda _s: None)
    db.expire_all()
    before = db.get(Job, job_id).lease_expires_at
    assert stale_beat.beat_once() is False
    assert stale_beat.lost is True
    db.expire_all()
    assert db.get(Job, job_id).lease_expires_at == before
    assert db.get(Job, job_id).status == JobStatus.RUNNING.value


def test_lost_lease_does_not_commit_the_result(db):
    """A worker whose lease has expired must not persist its result."""
    from app import worker
    from app.core.database import SessionLocal
    from app.models import Job, JobStatus

    job = Job(
        workspace_id=WS,
        kind="parse_evidence",
        status=JobStatus.QUEUED.value,
        payload="{}",
        attempt=0,
        max_attempts=3,
    )
    db.add(job)
    db.commit()
    job_id = job.id
    with _only(job_id):
        claimed = worker.claim_job(db)
    owner = claimed.lease_owner
    _set_lease_offset(db, job_id, -1)
    session = SessionLocal()
    try:
        stale = session.get(Job, job_id)
        stale.result = '{"from":"stale-owner"}'
        stale.status = JobStatus.COMPLETED.value
        install_commit_fence(session, job_id, owner)
        with pytest.raises(LeaseLost):
            session.commit()
    finally:
        session.rollback()
        session.close()
    db.expire_all()
    stored = db.get(Job, job_id)
    assert stored.result is None
    assert stored.status == JobStatus.RUNNING.value
    assert stored.lease_owner == owner
    lost = _audits(db, job_id, "job.lease_lost")
    # The fence itself does not audit; the worker loop does. This direct commit must not write one.
    assert lost == []


def test_expired_lease_is_recovered_without_running_the_side_effect_twice(db, monkeypatch):
    """AC2: a killed worker's job is retried by a second worker, and the effect ledger runs once."""
    from app import worker
    from app.core.database import SessionLocal
    from app.models import Job, JobStatus
    from app.models.job_effect import JobEffect
    from app.services.job_effects import JobEffects, enqueue_job

    monkeypatch.setenv("JOB_RETRY_BASE_SECONDS", "0")
    monkeypatch.setenv("JOB_RETRY_MAX_SECONDS", "0")
    key = f"parse_evidence:{uuid.uuid4().hex}"
    job, created = enqueue_job(
        db,
        workspace_id=WS,
        kind="parse_evidence",
        payload={"synthetic": True},
        idempotency_key=key,
    )
    assert created is True
    job_id = job.id
    with _only(job_id):
        claimed = worker.claim_job(db)
    owner = claimed.lease_owner
    JobEffects(db, claimed).mark_applied(EFFECT, {"n": 1})
    db.commit()
    _set_lease_offset(db, job_id, -1)

    session = SessionLocal()
    try:
        stale = session.get(Job, job_id)
        stale.result = '{"from":"stale-owner"}'
        install_commit_fence(session, job_id, owner)
        with pytest.raises(LeaseLost):
            session.commit()
    finally:
        session.rollback()
        session.close()

    assert worker.recover_abandoned_jobs(db) == 1
    db.expire_all()
    recovered = db.get(Job, job_id)
    assert recovered.status == JobStatus.QUEUED.value
    assert recovered.attempt == 1  # the abandoned claim already counted; recovery does not add one
    assert recovered.error_code == LEASE_EXPIRED
    assert recovered.lease_owner is None and recovered.lease_expires_at is None
    assert "lease expired" in (recovered.error or "")
    assert recovered.next_attempt_at is not None
    (abandoned,) = _audits(db, job_id, "job.abandoned")
    abandoned_details = _details(abandoned)
    assert abandoned_details["error_code"] == LEASE_EXPIRED
    assert abandoned_details["previous_owner_prefix"] == owner[:8]
    assert abandoned_details["status"] == JobStatus.QUEUED.value
    assert owner not in json.dumps(abandoned_details)
    assert _audits(db, job_id, "job.retry_scheduled")

    again, created_again = enqueue_job(
        db,
        workspace_id=WS,
        kind="parse_evidence",
        payload={"synthetic": True},
        idempotency_key=key,
    )
    assert created_again is False and again.id == job_id

    applied = {"n": 0}

    def fake_run(running, session):
        effects = JobEffects(session, running)
        if effects.is_applied(EFFECT):
            running.result = json.dumps({"outcome": "already_applied"})
            return
        applied["n"] += 1
        effects.mark_applied(EFFECT, {"n": 1})
        session.commit()

    monkeypatch.setattr(worker, "SessionFactory", SessionLocal)
    monkeypatch.setattr(worker, "last_compliance_webhook_run", 10**12)
    monkeypatch.setattr(worker, "last_usage_cleanup_run", 10**12)
    monkeypatch.setattr(worker, "last_dedupe_prune_run", 10**12)
    monkeypatch.setattr(worker, "run_job", fake_run)
    with _only(job_id):
        assert worker._process_one_job() is True
    assert applied["n"] == 0
    db.expire_all()
    done = db.get(Job, job_id)
    assert done.status == JobStatus.COMPLETED.value
    assert done.attempt == 2
    assert json.loads(done.result)["outcome"] == "already_applied"
    assert done.lease_owner is None
    rows = db.query(JobEffect).filter(JobEffect.job_id == job_id, JobEffect.effect == EFFECT).all()
    assert len(rows) == 1
    assert (
        renew_lease(
            job_id,
            owner,
            extend_seconds=60,
            session_factory=SessionLocal,
        )
        is False
    )


def test_attempt_cap_stops_an_abandoned_job(db, monkeypatch):
    from app import worker
    from app.models import Job, JobStatus

    monkeypatch.setenv("JOB_RETRY_BASE_SECONDS", "0")
    monkeypatch.setenv("JOB_RETRY_MAX_SECONDS", "0")
    job = Job(
        workspace_id=WS,
        kind="parse_evidence",
        status=JobStatus.RUNNING.value,
        payload="{}",
        attempt=3,
        max_attempts=3,
        lease_owner="ab" * 16,
    )
    db.add(job)
    db.commit()
    job_id = job.id
    _set_lease_offset(db, job_id, -1)
    assert worker.recover_abandoned_jobs(db) == 1
    db.expire_all()
    failed = db.get(Job, job_id)
    assert failed.status == JobStatus.FAILED.value
    assert failed.status != JobStatus.COMPLETED.value
    assert failed.error_code == LEASE_EXPIRED
    assert failed.error.startswith("Retries exhausted after 3 attempt(s) (lease_expired)")
    assert failed.next_attempt_at is None
    assert failed.lease_owner is None
    (audit,) = _audits(db, job_id, "job.failed")
    assert _details(audit)["retries_exhausted"] is True
    assert _details(audit)["error_code"] == LEASE_EXPIRED
    assert _audits(db, job_id, "job.abandoned")
    assert not _audits(db, job_id, "job.retry_scheduled")


def test_two_recoverers_take_one_expired_job(db, monkeypatch):
    """One expired job, two sessions. The row lock makes exactly one of them the recoverer."""
    from app import worker
    from app.core.database import SessionLocal
    from app.models import Job, JobStatus

    monkeypatch.setenv("JOB_RETRY_BASE_SECONDS", "0")
    monkeypatch.setenv("JOB_RETRY_MAX_SECONDS", "0")
    job = Job(
        workspace_id=WS,
        kind="parse_evidence",
        status=JobStatus.RUNNING.value,
        payload="{}",
        attempt=1,
        max_attempts=3,
        lease_owner="ab" * 16,
    )
    db.add(job)
    db.commit()
    job_id = job.id
    _set_lease_offset(db, job_id, -1)
    barrier = threading.Barrier(2)
    results: list[int] = []
    errors: list[BaseException] = []

    def recover() -> None:
        session = SessionLocal()
        try:
            barrier.wait(timeout=5)
            results.append(worker.recover_abandoned_jobs(session))
        except BaseException as exc:  # noqa: BLE001 - report the thread failure
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=recover), threading.Thread(target=recover)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert errors == []
    assert sorted(results) == [0, 1]
    assert len(_audits(db, job_id, "job.abandoned")) == 1
    assert len(_audits(db, job_id, "job.retry_scheduled")) == 1
    assert not _audits(db, job_id, "job.failed")
    db.expire_all()
    stored = db.get(Job, job_id)
    assert stored.status == JobStatus.QUEUED.value
    assert stored.attempt == 1


def _expired_running(db, attempt: int = 1, max_attempts: int = 3) -> int:
    from app.models import Job, JobStatus

    job = Job(
        workspace_id=WS,
        kind="parse_evidence",
        status=JobStatus.RUNNING.value,
        payload="{}",
        attempt=attempt,
        max_attempts=max_attempts,
        lease_owner="ab" * 16,
    )
    db.add(job)
    db.commit()
    _set_lease_offset(db, job.id, -1)
    return job.id


def _reclaim(job_id: int) -> None:
    """A second worker claims the job the moment classification has committed it."""
    from app.core.database import SessionLocal

    other = SessionLocal()
    try:
        other.execute(
            text(
                """
                UPDATE jobs
                SET status = 'running',
                    attempt = attempt + 1,
                    lease_owner = :owner,
                    lease_expires_at = now() + interval '60 seconds',
                    next_attempt_at = NULL
                WHERE id = :id AND status = 'queued'
                """
            ),
            {"id": job_id, "owner": "d" * 32},
        )
        other.commit()
    finally:
        other.close()


def test_reclaim_after_classify_keeps_one_abandoned_audit(db, monkeypatch):
    """A claim in the gap after classification still leaves the abandoned audit."""
    from app import worker
    from app.models import Job, JobStatus

    monkeypatch.setenv("JOB_RETRY_BASE_SECONDS", "0")
    monkeypatch.setenv("JOB_RETRY_MAX_SECONDS", "0")
    job_id = _expired_running(db)
    real = worker._persist_job_audit

    def hooked(session, job, action, payload, error=None, extra=None):
        real(session, job, action, payload, error=error, extra=extra)
        if action == "job.retry_scheduled" and job.id == job_id:
            _reclaim(job_id)

    monkeypatch.setattr(worker, "_persist_job_audit", hooked)
    worker.recover_abandoned_jobs(db)
    db.expire_all()
    assert len(_audits(db, job_id, "job.abandoned")) == 1
    assert len(_audits(db, job_id, "job.retry_scheduled")) == 1
    stored = db.get(Job, job_id)
    assert stored.status == JobStatus.RUNNING.value
    assert stored.attempt == 2


def test_one_conflict_in_a_batch_still_recovers_the_others(db, monkeypatch):
    """A conflict on one of three expired jobs does not drop the other two."""
    from app import worker
    from app.models import Job, JobStatus

    monkeypatch.setenv("JOB_RETRY_BASE_SECONDS", "0")
    monkeypatch.setenv("JOB_RETRY_MAX_SECONDS", "0")
    ids = [_expired_running(db) for _ in range(3)]
    conflict_id = ids[1]
    real = worker._persist_job_audit

    def hooked(session, job, action, payload, error=None, extra=None):
        real(session, job, action, payload, error=error, extra=extra)
        if action == "job.retry_scheduled" and job.id == conflict_id:
            _reclaim(conflict_id)

    monkeypatch.setattr(worker, "_persist_job_audit", hooked)
    worker.recover_abandoned_jobs(db)
    db.expire_all()
    for job_id in ids:
        assert len(_audits(db, job_id, "job.abandoned")) == 1
    for job_id in (ids[0], ids[2]):
        stored = db.get(Job, job_id)
        assert stored.status == JobStatus.QUEUED.value
        assert stored.attempt == 1
    conflicted = db.get(Job, conflict_id)
    assert conflicted.status == JobStatus.RUNNING.value
    assert conflicted.attempt == 2


def test_recovery_reraises_when_completed_status_query_fails(db, monkeypatch):
    """A status-query error during recovery propagates and leaves the job untouched."""
    from app import worker
    from app.core.database import SessionLocal
    from app.models import Job, JobStatus

    monkeypatch.setenv("JOB_RETRY_BASE_SECONDS", "0")
    monkeypatch.setenv("JOB_RETRY_MAX_SECONDS", "0")
    job_id = _expired_running(db)
    owner = "ab" * 16
    session = SessionLocal()
    original = session.query

    def query(*args, **kwargs):
        if args and args[0] is Job.status:
            raise RuntimeError("synthetic status query failure")
        return original(*args, **kwargs)

    session.query = query
    try:
        with pytest.raises(RuntimeError, match="synthetic status query failure"):
            worker.recover_abandoned_jobs(session)
    finally:
        session.rollback()
        session.close()
    db.expire_all()
    stored = db.get(Job, job_id)
    assert stored.status == JobStatus.RUNNING.value
    assert stored.lease_owner == owner
    assert stored.attempt == 1
    assert _seconds_left(db, job_id) < 0
    assert not _audits(db, job_id, "job.abandoned")
    assert not _audits(db, job_id, "job.retry_scheduled")
    assert not _audits(db, job_id, "job.failed")


def _prepare_worker_loop(monkeypatch, job_id: int):
    from app import worker
    from app.core.database import SessionLocal

    monkeypatch.setattr(worker, "SessionFactory", SessionLocal)
    monkeypatch.setattr(worker, "last_compliance_webhook_run", 10**12)
    monkeypatch.setattr(worker, "last_usage_cleanup_run", 10**12)
    monkeypatch.setattr(worker, "last_dedupe_prune_run", 10**12)
    return worker


def test_worker_loop_does_not_commit_after_the_lease_expires(db, monkeypatch):
    """The worker loop itself stops when the lease is gone, and recovery can requeue afterwards."""
    from app.core.database import SessionLocal
    from app.models import Job, JobStatus

    job = Job(
        workspace_id=WS,
        kind="parse_evidence",
        status=JobStatus.QUEUED.value,
        payload="{}",
        attempt=0,
        max_attempts=3,
    )
    db.add(job)
    db.commit()
    job_id = job.id
    seen: dict[str, str] = {}

    def fake_run(running, session):
        del session
        seen["owner"] = running.lease_owner
        other = SessionLocal()
        try:
            other.execute(
                text(
                    "UPDATE jobs SET lease_expires_at = now() - interval '1 second' WHERE id = :id"
                ),
                {"id": running.id},
            )
            other.commit()
        finally:
            other.close()
        running.result = '{"from":"loser"}'

    worker = _prepare_worker_loop(monkeypatch, job_id)
    monkeypatch.setattr(worker, "run_job", fake_run)
    monkeypatch.setenv("JOB_RETRY_BASE_SECONDS", "0")
    monkeypatch.setenv("JOB_RETRY_MAX_SECONDS", "0")
    with _only(job_id):
        assert worker._process_one_job() is True
    owner = seen["owner"]
    db.expire_all()
    stored = db.get(Job, job_id)
    assert stored.status == JobStatus.RUNNING.value
    assert stored.result is None
    assert stored.attempt == 1
    assert not _audits(db, job_id, "job.completed")
    (lost,) = _audits(db, job_id, "job.lease_lost")
    details = _details(lost)
    assert details["owner_prefix"] == owner[:8]
    assert len(details["owner_prefix"]) == 8
    assert owner not in json.dumps(details)
    assert worker.recover_abandoned_jobs(db) == 1
    db.expire_all()
    requeued = db.get(Job, job_id)
    assert requeued.status == JobStatus.QUEUED.value
    assert requeued.attempt == 1
    assert _audits(db, job_id, "job.retry_scheduled")


def test_worker_loop_does_not_retry_after_a_lost_lease_exception(db, monkeypatch):
    """A handler that raises once the lease is gone must not schedule the retry itself."""
    from app.core.database import SessionLocal
    from app.models import Job, JobStatus

    job = Job(
        workspace_id=WS,
        kind="parse_evidence",
        status=JobStatus.QUEUED.value,
        payload="{}",
        attempt=0,
        max_attempts=3,
    )
    db.add(job)
    db.commit()
    job_id = job.id

    def fake_run(running, session):
        del session
        other = SessionLocal()
        try:
            other.execute(
                text("UPDATE jobs SET lease_owner = :token WHERE id = :id"),
                {"token": "c" * 32, "id": running.id},
            )
            other.commit()
        finally:
            other.close()
        raise RuntimeError("synthetic lost lease")

    worker = _prepare_worker_loop(monkeypatch, job_id)
    monkeypatch.setattr(worker, "run_job", fake_run)
    with _only(job_id):
        assert worker._process_one_job() is True
    db.expire_all()
    stored = db.get(Job, job_id)
    assert stored.status == JobStatus.RUNNING.value
    assert stored.attempt == 1
    assert stored.result is None
    assert not _audits(db, job_id, "job.failed")
    assert not _audits(db, job_id, "job.retry_scheduled")
    assert not _audits(db, job_id, "job.completed")


def _age_job(db, job_id: int, *, updated_age: float | None, started_age: float | None) -> None:
    """Move timestamps relative to the database clock. None stores NULL."""
    db.execute(
        text(
            """
            UPDATE jobs
            SET updated_at = CASE
                    WHEN :updated_age IS NULL THEN NULL
                    ELSE now() - make_interval(secs => :updated_age)
                END,
                started_at = CASE
                    WHEN :started_age IS NULL THEN NULL
                    ELSE now() - make_interval(secs => :started_age)
                END
            WHERE id = :id
            """
        ),
        {"id": job_id, "updated_age": updated_age, "started_age": started_age},
    )
    db.commit()
    db.expire_all()


def _null_running(db) -> int:
    from app.models import Job, JobStatus

    job = Job(
        workspace_id=WS,
        kind="parse_evidence",
        status=JobStatus.RUNNING.value,
        payload="{}",
        attempt=1,
        max_attempts=3,
        lease_owner=None,
        lease_expires_at=None,
    )
    db.add(job)
    db.commit()
    return job.id


def _grace(monkeypatch, seconds: str = "600") -> None:
    monkeypatch.setenv("JOB_LEASE_SECONDS", "60")
    monkeypatch.setenv("JOB_NULL_LEASE_GRACE_SECONDS", seconds)
    monkeypatch.setenv("JOB_RETRY_BASE_SECONDS", "0")
    monkeypatch.setenv("JOB_RETRY_MAX_SECONDS", "0")


def test_null_lease_older_than_the_grace_is_recovered_once(db, monkeypatch):
    """A NULL-lease job past the grace is classified once, with both audits."""
    from app import worker
    from app.models import Job, JobStatus

    _grace(monkeypatch)
    job_id = _null_running(db)
    _age_job(db, job_id, updated_age=601, started_age=601)
    assert worker.recover_abandoned_jobs(db) == 1
    assert worker.recover_abandoned_jobs(db) == 0
    db.expire_all()
    stored = db.get(Job, job_id)
    assert stored.status == JobStatus.QUEUED.value
    assert stored.attempt == 1
    assert stored.lease_owner is None and stored.lease_expires_at is None
    assert len(_audits(db, job_id, "job.abandoned")) == 1
    assert len(_audits(db, job_id, "job.retry_scheduled")) == 1
    assert not _audits(db, job_id, "job.failed")


def test_null_lease_younger_than_the_grace_is_untouched(db, monkeypatch):
    """A recent updated_at keeps the job, even when started_at is already past the grace."""
    from app import worker
    from app.models import Job, JobStatus

    _grace(monkeypatch)
    job_id = _null_running(db)
    _age_job(db, job_id, updated_age=10, started_age=5000)
    assert worker.recover_abandoned_jobs(db) == 0
    db.expire_all()
    stored = db.get(Job, job_id)
    assert stored.status == JobStatus.RUNNING.value
    assert stored.attempt == 1
    assert stored.lease_owner is None and stored.lease_expires_at is None
    assert not _audits(db, job_id, "job.abandoned")
    assert not _audits(db, job_id, "job.retry_scheduled")


def test_null_lease_uses_started_at_when_updated_at_is_null(db, monkeypatch):
    """With no updated_at, started_at is the age. Both NULL stays unrecovered."""
    from app import worker
    from app.models import Job, JobStatus

    _grace(monkeypatch)
    aged = _null_running(db)
    _age_job(db, aged, updated_age=None, started_age=601)
    blank = _null_running(db)
    _age_job(db, blank, updated_age=None, started_age=None)
    assert worker.recover_abandoned_jobs(db) == 1
    db.expire_all()
    assert db.get(Job, aged).status == JobStatus.QUEUED.value
    assert len(_audits(db, aged, "job.abandoned")) == 1
    stored = db.get(Job, blank)
    assert stored.status == JobStatus.RUNNING.value
    assert stored.lease_owner is None
    assert not _audits(db, blank, "job.abandoned")


def test_two_recoverers_take_one_null_lease_job(db, monkeypatch):
    """Two sessions, one NULL-lease job past the grace: one recovers it and the other does not."""
    from app import worker
    from app.core.database import SessionLocal
    from app.models import Job, JobStatus

    _grace(monkeypatch)
    job_id = _null_running(db)
    _age_job(db, job_id, updated_age=601, started_age=601)
    barrier = threading.Barrier(2)
    results: list[int] = []
    errors: list[BaseException] = []

    def recover() -> None:
        session = SessionLocal()
        try:
            barrier.wait(timeout=5)
            results.append(worker.recover_abandoned_jobs(session))
        except BaseException as exc:  # noqa: BLE001 - report the thread failure
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=recover), threading.Thread(target=recover)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert errors == []
    assert sorted(results) == [0, 1]
    assert len(_audits(db, job_id, "job.abandoned")) == 1
    assert len(_audits(db, job_id, "job.retry_scheduled")) == 1
    db.expire_all()
    stored = db.get(Job, job_id)
    assert stored.status == JobStatus.QUEUED.value
    assert stored.attempt == 1


def test_mixed_null_and_expired_leases_are_all_recovered(db, monkeypatch):
    """One expired lease and one NULL lease past the grace are both recovered."""
    from app import worker
    from app.models import Job, JobStatus

    _grace(monkeypatch)
    expired = _expired_running(db)
    null_id = _null_running(db)
    _age_job(db, null_id, updated_age=601, started_age=601)
    assert worker.recover_abandoned_jobs(db) == 2
    db.expire_all()
    for job_id in (expired, null_id):
        stored = db.get(Job, job_id)
        assert stored.status == JobStatus.QUEUED.value
        assert stored.attempt == 1
        assert len(_audits(db, job_id, "job.abandoned")) == 1
        assert len(_audits(db, job_id, "job.retry_scheduled")) == 1


def test_null_lease_on_a_running_job_is_not_recovered(db):
    """A fresh NULL lease is inside the grace. NULL alone is not an expired lease."""
    from app import worker
    from app.models import Job, JobStatus

    job = Job(
        workspace_id=WS,
        kind="parse_evidence",
        status=JobStatus.RUNNING.value,
        payload="{}",
        attempt=1,
        max_attempts=3,
    )
    db.add(job)
    db.commit()
    job_id = job.id
    assert worker.recover_abandoned_jobs(db) == 0
    db.expire_all()
    stored = db.get(Job, job_id)
    assert stored.status == JobStatus.RUNNING.value
    assert stored.attempt == 1
    assert stored.lease_owner is None and stored.lease_expires_at is None


def test_idempotency_owner_fence_still_holds_beside_a_job_lease(db):
    """The idempotency owner token (TC-10-003b) still fences set/release while job leases exist."""
    from app.core import idempotency

    key = f"ws:{WS}:job-lease:{uuid.uuid4().hex}"
    owner = idempotency.claim(db, key)
    assert isinstance(owner, str) and len(owner) == 32
    db.execute(
        text("UPDATE idempotency_keys SET expires_at = :past WHERE idempotency_key = :key"),
        {"past": datetime(2000, 1, 1), "key": key},
    )
    db.commit()
    new_owner = idempotency.claim(db, key)
    assert isinstance(new_owner, str) and new_owner != owner
    assert idempotency.set(db, key, 200, {"ok": True}, owner=owner) is False
    assert idempotency.release(db, key, owner=owner) is False
    assert idempotency.set(db, key, 200, {"synthetic": True}, owner=new_owner) is True
    stored = idempotency.get(db, key)
    assert stored is not None and stored[0] == 200 and stored[1]["synthetic"] is True


# ---------------------------------------------------------------------------------------------------------
# Migration round trip
# ---------------------------------------------------------------------------------------------------------


def _alembic(*args: str) -> str:
    from app.core.database import engine

    env = {**os.environ, "DATABASE_URL": os.environ["DATABASE_URL"], "TRUST_COPILOT_TESTING": "1"}
    engine.dispose()
    try:
        from app import worker

        worker.engine.dispose()
    except Exception:
        pass
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(Path(__file__).resolve().parents[2]),
        env=env,
        capture_output=True,
        text=True,
    )
    engine.dispose()
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout


def test_migration_upgrade_downgrade_upgrade_is_lossless(db, _ensure_test_data):
    if not _ensure_test_data:
        pytest.skip("Postgres test DB unavailable")
    api_dir = Path(__file__).resolve().parents[2]
    path = api_dir / "alembic" / "versions" / "tc10001_job_leases.py"
    spec = importlib.util.spec_from_file_location("tc10001_mig", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "tc10001_job_leases"
    assert len(module.revision) <= 32
    # Parent is whatever the migration file says, not a hard-coded revision id.
    assert isinstance(module.down_revision, str) and module.down_revision

    from app.core.database import SessionLocal, engine

    def version_width() -> int:
        session = SessionLocal()
        try:
            width = session.execute(
                text(
                    """
                    SELECT character_maximum_length
                    FROM information_schema.columns
                    WHERE table_name = 'alembic_version' AND column_name = 'version_num'
                    """
                )
            ).scalar()
            return int(width)
        finally:
            session.close()

    def job_columns() -> set[str]:
        engine.dispose()
        return {column["name"] for column in inspect(engine).get_columns("jobs")}

    assert version_width() == 32
    sentinel = '{"synthetic":"tc10001-roundtrip"}'
    token = uuid.uuid4().hex
    session = SessionLocal()
    try:
        job_id = session.execute(
            text(
                """
                INSERT INTO jobs (
                    workspace_id, kind, status, payload, attempt, max_attempts,
                    idempotency_key, error, lease_owner, lease_expires_at
                )
                VALUES (
                    1, 'parse_evidence', 'queued', :payload, 2, 3,
                    :key, 'sentinel-error', 'synthetic-owner', '2020-01-01 00:00:00'
                )
                RETURNING id
                """
            ),
            {"payload": sentinel, "key": f"roundtrip-{token}"},
        ).scalar()
        session.commit()
    finally:
        session.close()

    def row() -> tuple:
        session = SessionLocal()
        try:
            return session.execute(
                text(
                    """
                    SELECT payload, status, attempt, error, idempotency_key
                    FROM jobs WHERE id = :id
                    """
                ),
                {"id": job_id},
            ).one()
        finally:
            session.close()

    expected = (sentinel, "queued", 2, "sentinel-error", f"roundtrip-{token}")
    try:
        _alembic("downgrade", module.down_revision)
        assert "lease_owner" not in job_columns()
        assert "lease_expires_at" not in job_columns()
        assert row() == expected
        _alembic("upgrade", "head")
        assert {"lease_owner", "lease_expires_at"} <= job_columns()
        assert row() == expected
        cleared = SessionLocal()
        try:
            lease = cleared.execute(
                text("SELECT lease_owner, lease_expires_at FROM jobs WHERE id = :id"),
                {"id": job_id},
            ).one()
            assert lease[0] is None and lease[1] is None
        finally:
            cleared.close()
        # upgrade, downgrade, upgrade: the non-lease columns survive both passes.
        _alembic("downgrade", module.down_revision)
        assert row() == expected
        _alembic("upgrade", "head")
        assert row() == expected
        from tests.release.test_notification_delivery import (
            _revision_is_applied,
            _revision_token,
        )

        head = _revision_token(_alembic("heads"))
        assert _revision_is_applied(head, module.revision)
        engine.dispose()
        index_names = {idx["name"] for idx in inspect(engine).get_indexes("jobs")}
        assert "ix_jobs_running_lease_expires_at" in index_names
        assert version_width() == 32
    finally:
        _alembic("upgrade", "head")
