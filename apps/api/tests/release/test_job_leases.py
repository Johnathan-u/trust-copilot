"""TC-10-001: periodic job leases and abandoned-job recovery.

On master, ``jobs`` has no lease columns. ``claim_job`` marks a row running and never stores an
owner token. A second ``claim_job`` will not take that row, and nothing sends it back through the
retry cap, so a killed worker leaves the job running. These tests fail on that code.

Fakes only: no network, no real keys, a side ``*_test`` database. Time is an injected clock.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timedelta
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


class Clock:
    """Deterministic naive-UTC clock. Tests advance it; nothing sleeps."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def _past_clock() -> Clock:
    """A clock in 2020, so advancing it cannot expire leases other tests stored with wall time."""
    return Clock(datetime(2020, 6, 1, 12, 0, 0))


@pytest.fixture(autouse=True)
def _reset_lease_hooks():
    yield
    from app import worker
    from app.core import job_lease

    worker.set_clock(None)
    job_lease._clamp_logged = False


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
    assert lease_heartbeat_seconds() < 30
    assert lease_heartbeat_seconds() == (30 - 1) // 3


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
    now = expiry - timedelta(seconds=1)
    assert (
        renew_lease(
            job_id,
            "f" * 32,
            now=now,
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
            now=now,
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

    clock = _past_clock()
    worker.set_clock(clock)
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
    first_expiry = claimed.lease_expires_at
    assert first_expiry == clock.now + timedelta(seconds=lease_seconds())

    def renew() -> bool:
        return renew_lease(
            job_id,
            owner,
            now=clock(),
            extend_seconds=lease_seconds(),
            session_factory=SessionLocal,
        )

    heartbeat = JobLeaseHeartbeat(
        renew, interval_sec=lease_heartbeat_seconds(), sleep=lambda _s: None
    )
    # Still inside the original lease: one beat pushes the expiry out.
    clock.advance(50)
    assert heartbeat.beat_once() is True
    db.expire_all()
    extended = db.get(Job, job_id).lease_expires_at
    assert extended == clock.now + timedelta(seconds=lease_seconds())
    assert extended > first_expiry
    # Past the original expiry, the renewed lease is still held.
    clock.advance(20)
    assert clock.now > first_expiry
    assert heartbeat.beat_once() is True
    assert heartbeat.lost is False
    assert heartbeat.beats == 2

    def stale() -> bool:
        return renew_lease(
            job_id,
            "a" * 32,
            now=clock(),
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

    clock = _past_clock()
    worker.set_clock(clock)
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
    clock.advance(lease_seconds() + 5)
    session = SessionLocal()
    try:
        stale = session.get(Job, job_id)
        stale.result = '{"from":"stale-owner"}'
        stale.status = JobStatus.COMPLETED.value
        install_commit_fence(session, job_id, owner, clock)
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

    clock = _past_clock()
    worker.set_clock(clock)
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
    clock.advance(lease_seconds() + 5)

    session = SessionLocal()
    try:
        stale = session.get(Job, job_id)
        stale.result = '{"from":"stale-owner"}'
        install_commit_fence(session, job_id, owner, clock)
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
            now=clock(),
            extend_seconds=60,
            session_factory=SessionLocal,
        )
        is False
    )


def test_attempt_cap_stops_an_abandoned_job(db, monkeypatch):
    from app import worker
    from app.models import Job, JobStatus

    clock = _past_clock()
    worker.set_clock(clock)
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
        lease_expires_at=clock.now,
    )
    db.add(job)
    db.commit()
    job_id = job.id
    clock.advance(1)
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


def test_null_lease_on_a_running_job_is_not_recovered(db):
    """Rows from before leases existed stay running. NULL is not an expired lease."""
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
    assert module.down_revision == "tc21006_gap_evaluation"

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
        heads = _alembic("heads")
        assert "tc10001_job_leases" in heads
        assert heads.count("(head)") == 1
        assert version_width() == 32
    finally:
        _alembic("upgrade", "head")
