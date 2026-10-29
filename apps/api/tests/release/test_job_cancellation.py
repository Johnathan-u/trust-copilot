"""TC-10-004: cancel a job, and retry it manually with an audit.

Fakes only. The fixture records max(id) and counts, deletes rows above that id, and
asserts the counts. It does not call setval.
"""

from __future__ import annotations

import json
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.database import SessionLocal
from app.models import Job, JobStatus

WS = 1
TABLES = ("jobs", "audit_events", "user_sessions")
# user_sessions is not referenced by jobs or audit_events. Delete it with them.
DELETE_ORDER = ("jobs", "audit_events", "user_sessions")


def _refuse_foreign_eligible(db, *own_ids: int) -> None:
    from app.core.job_lease import null_lease_grace_seconds

    own = {int(job_id) for job_id in own_ids}
    rows = db.execute(
        text(
            """
            SELECT id
            FROM jobs
            WHERE status = 'running'
              AND (
                    (lease_expires_at IS NOT NULL AND lease_expires_at <= now())
                 OR (
                        lease_owner IS NULL
                    AND lease_expires_at IS NULL
                    AND COALESCE(updated_at, started_at)
                        <= now() - make_interval(secs => :grace)
                    )
                  )
            ORDER BY id
            """
        ),
        {"grace": float(null_lease_grace_seconds())},
    ).scalars()
    foreign = [int(row) for row in rows if int(row) not in own]
    assert foreign == [], (
        "refusing to recover: foreign running jobs are eligible and would be mutated: "
        + ", ".join(str(job_id) for job_id in foreign)
    )


@pytest.fixture
def db(_ensure_test_data):
    if not _ensure_test_data:
        pytest.skip("Postgres test DB unavailable")
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


@pytest.mark.unit
def test_status_fence_rejects_a_non_string_or_unknown_status():
    """An unexpected status is not running, so the failure write is skipped."""
    from app import worker

    job = Job(
        workspace_id=WS,
        kind="parse_evidence",
        status=JobStatus.RUNNING.value,
        payload="{}",
        attempt=1,
        lease_owner="owner-token",
    )
    job.id = 4

    class _Rows:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    class _Session:
        def __init__(self, row):
            self._row = row

        @property
        def no_autoflush(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            return _Rows(self._row)

    assert worker._still_running_for_owner(_Session(("running", "owner-token")), job) is True
    assert worker._still_running_for_owner(_Session((None, "owner-token")), job) is False
    assert worker._still_running_for_owner(_Session((object(), "owner-token")), job) is False
    assert worker._still_running_for_owner(_Session(("not-a-status", "owner-token")), job) is False
    assert worker._still_running_for_owner(_Session(None), job) is False


def _job(db, **kwargs) -> Job:
    job = Job(
        workspace_id=kwargs.pop("workspace_id", WS),
        kind="parse_evidence",
        status=kwargs.pop("status", JobStatus.QUEUED.value),
        payload="{}",
        attempt=kwargs.pop("attempt", 0),
        max_attempts=3,
        **kwargs,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _audits(db, job_id: int, action: str):
    from app.models.audit_event import AuditEvent

    db.expire_all()
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


def _login(client: TestClient, email: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200


def _admin(client: TestClient) -> None:
    _login(client, "admin@trust.local", "a")


def _actor_id(db) -> int:
    from app.models import User

    return db.query(User).filter(User.email == "admin@trust.local").one().id


def test_cancel_queued_job_is_terminal_and_not_claimed(client: TestClient, db, monkeypatch):
    from app import worker

    _admin(client)
    job = _job(db)
    response = client.post(f"/api/jobs/{job.id}/cancel?workspace_id={WS}")
    assert response.status_code == 200
    assert response.json()["status"] == JobStatus.CANCELLED.value
    db.expire_all()
    stored = db.get(Job, job.id)
    assert stored.status == JobStatus.CANCELLED.value
    assert stored.attempt == 0
    assert stored.next_attempt_at is None
    assert len(_audits(db, job.id, "job.cancelled")) == 1
    monkeypatch.setattr(worker, "SessionFactory", SessionLocal)
    real = worker.claimable_filter
    monkeypatch.setattr(worker, "claimable_filter", lambda now=None: real(now) & (Job.id == job.id))
    assert worker.claim_job(db) is None
    db.expire_all()
    assert db.get(Job, job.id).status == JobStatus.CANCELLED.value


def test_cancel_while_running_blocks_the_workers_late_completion(db, monkeypatch):
    from app import worker
    from app.services.job_control import cancel_job

    job = _job(db)
    job_id = job.id

    def fake_run(running, session):
        del session
        other = SessionLocal()
        try:
            kind, _row = cancel_job(
                other,
                running.id,
                workspace_id=WS,
                actor_user_id=1,
                actor_email="admin@trust.local",
            )
            assert kind == "cancelled"
        finally:
            other.close()
        running.result = '{"from":"late"}'

    monkeypatch.setattr(worker, "SessionFactory", SessionLocal)
    monkeypatch.setattr(worker, "last_compliance_webhook_run", 10**12)
    monkeypatch.setattr(worker, "last_usage_cleanup_run", 10**12)
    monkeypatch.setattr(worker, "last_dedupe_prune_run", 10**12)
    monkeypatch.setattr(worker, "run_job", fake_run)
    real = worker.claimable_filter
    monkeypatch.setattr(worker, "claimable_filter", lambda now=None: real(now) & (Job.id == job_id))
    _refuse_foreign_eligible(db)
    assert worker._process_one_job() is True
    db.expire_all()
    stored = db.get(Job, job_id)
    assert stored.status == JobStatus.CANCELLED.value
    assert stored.attempt == 1
    assert stored.result is None
    assert not _audits(db, job_id, "job.completed")
    assert not _audits(db, job_id, "job.retry_scheduled")
    assert not _audits(db, job_id, "job.failed")


def test_cancel_retrying_job_clears_the_schedule(client: TestClient, db):
    from datetime import datetime, timedelta

    _admin(client)
    job = _job(
        db,
        status=JobStatus.QUEUED.value,
        attempt=1,
        error_code="rate_limited",
        error="Attempt 1 of 3 failed (rate_limited): synthetic.",
        next_attempt_at=datetime.utcnow() + timedelta(hours=1),
    )
    response = client.post(f"/api/jobs/{job.id}/cancel?workspace_id={WS}")
    assert response.status_code == 200
    db.expire_all()
    stored = db.get(Job, job.id)
    assert stored.status == JobStatus.CANCELLED.value
    assert stored.attempt == 1
    assert stored.next_attempt_at is None
    assert len(_audits(db, job.id, "job.cancelled")) == 1


def test_cancel_racing_lease_recovery_stays_cancelled(db, monkeypatch):
    from app import worker
    from app.services.job_control import cancel_job

    monkeypatch.setenv("JOB_RETRY_BASE_SECONDS", "0")
    monkeypatch.setenv("JOB_RETRY_MAX_SECONDS", "0")
    job = _job(
        db,
        status=JobStatus.RUNNING.value,
        attempt=1,
        lease_owner="ab" * 16,
    )
    db.execute(
        text(
            """
            UPDATE jobs
            SET lease_expires_at = now() - interval '1 second'
            WHERE id = :id
            """
        ),
        {"id": job.id},
    )
    db.commit()
    _refuse_foreign_eligible(db, job.id)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def recover() -> None:
        session = SessionLocal()
        try:
            barrier.wait(timeout=5)
            worker.recover_abandoned_jobs(session)
        except BaseException as exc:  # noqa: BLE001 - report the thread failure
            errors.append(exc)
        finally:
            session.close()

    def cancel() -> None:
        session = SessionLocal()
        try:
            barrier.wait(timeout=5)
            cancel_job(
                session,
                job.id,
                workspace_id=WS,
                actor_user_id=1,
                actor_email="admin@trust.local",
            )
        except BaseException as exc:  # noqa: BLE001 - report the thread failure
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=recover), threading.Thread(target=cancel)]
    for thread in threads:
        thread.start()
    try:
        pass
    finally:
        for thread in threads:
            thread.join(timeout=10)
        for thread in threads:
            assert not thread.is_alive()
    assert errors == []
    db.expire_all()
    stored = db.get(Job, job.id)
    assert stored.status == JobStatus.CANCELLED.value
    assert stored.attempt == 1
    assert len(_audits(db, job.id, "job.cancelled")) == 1
    _refuse_foreign_eligible(db)
    assert worker.recover_abandoned_jobs(db) == 0
    db.expire_all()
    assert db.get(Job, job.id).status == JobStatus.CANCELLED.value
    assert not _audits(db, job.id, "job.completed")


def test_repeat_cancel_does_not_write_a_second_audit(client: TestClient, db):
    _admin(client)
    job = _job(db)
    first = client.post(f"/api/jobs/{job.id}/cancel?workspace_id={WS}")
    second = client.post(f"/api/jobs/{job.id}/cancel?workspace_id={WS}")
    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["status"] == JobStatus.CANCELLED.value
    assert len(_audits(db, job.id, "job.cancelled")) == 1


def test_cancel_of_another_workspace_is_not_found(client: TestClient, db):
    _admin(client)
    job = _job(db, workspace_id=2, status=JobStatus.QUEUED.value)
    same = client.post(f"/api/jobs/{job.id}/cancel?workspace_id={WS}")
    other = client.post(f"/api/jobs/{job.id}/cancel?workspace_id=2")
    assert same.status_code == 404 and same.json()["detail"] == "Job not found"
    assert other.status_code == 404 and other.json()["detail"] == "Job not found"
    db.expire_all()
    assert db.get(Job, job.id).status == JobStatus.QUEUED.value
    assert not _audits(db, job.id, "job.cancelled")


def test_cancel_completed_job_is_a_conflict(client: TestClient, db):
    _admin(client)
    job = _job(db, status=JobStatus.COMPLETED.value, attempt=1, result='{"ok":true}')
    response = client.post(f"/api/jobs/{job.id}/cancel?workspace_id={WS}")
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "job_not_cancellable"
    assert body["detail"] == body["error"]["message"]
    assert body["error"]["retryable"] is False
    assert body["error"]["request_id"]
    db.expire_all()
    stored = db.get(Job, job.id)
    assert stored.status == JobStatus.COMPLETED.value
    assert stored.result == '{"ok":true}'
    assert not _audits(db, job.id, "job.cancelled")


def test_manual_retry_records_the_actor_and_prior_attempt(client: TestClient, db):
    _admin(client)
    actor = _actor_id(db)
    job = _job(
        db,
        status=JobStatus.FAILED.value,
        attempt=2,
        error_code="rate_limited",
        error="Attempt 2 of 3 failed (rate_limited): synthetic.",
    )
    response = client.post(f"/api/jobs/{job.id}/retry?workspace_id={WS}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == JobStatus.QUEUED.value
    assert body["attempt"] == 0
    db.expire_all()
    stored = db.get(Job, job.id)
    assert stored.status == JobStatus.QUEUED.value
    assert stored.attempt == 0
    assert stored.lease_owner is None
    (audit,) = _audits(db, job.id, "job.manual_retry")
    details = _details(audit)
    assert audit.user_id == actor
    assert details["actor_user_id"] == actor
    assert details["prior_error_code"] == "rate_limited"
    assert details["prior_error"] == "Attempt 2 of 3 failed (rate_limited): synthetic."
    assert details["prior_attempt"] == 2
    assert details["prior_status"] == JobStatus.FAILED.value


def test_two_manual_retries_one_wins(db):
    """Two admins retry one failed job. One re-queues it and the other gets 409."""
    from app.main import app
    from tests.conftest import TEST_HEADERS, TEST_ORIGIN

    job = _job(
        db,
        status=JobStatus.FAILED.value,
        attempt=2,
        error_code="rate_limited",
        error="Attempt 2 of 3 failed (rate_limited): synthetic.",
    )
    barrier = threading.Barrier(2)
    codes: list[int] = []
    errors: list[BaseException] = []

    def retry() -> None:
        client = TestClient(app, base_url=TEST_ORIGIN, headers=TEST_HEADERS)
        try:
            _admin(client)
            barrier.wait(timeout=5)
            response = client.post(f"/api/jobs/{job.id}/retry?workspace_id={WS}")
            codes.append(response.status_code)
        except BaseException as exc:  # noqa: BLE001 - report the thread failure
            errors.append(exc)
        finally:
            client.close()

    threads = [threading.Thread(target=retry), threading.Thread(target=retry)]
    for thread in threads:
        thread.start()
    try:
        pass
    finally:
        for thread in threads:
            thread.join(timeout=15)
        for thread in threads:
            assert not thread.is_alive()
    assert errors == []
    assert sorted(codes) == [200, 409]
    db.expire_all()
    stored = db.get(Job, job.id)
    assert stored.status == JobStatus.QUEUED.value
    assert stored.attempt == 0
    assert len(_audits(db, job.id, "job.manual_retry")) == 1


def test_manual_retry_by_a_non_admin_is_forbidden(client: TestClient, db):
    _login(client, "editor@trust.local", "e")
    job = _job(
        db, status=JobStatus.FAILED.value, attempt=1, error_code="timeout", error="synthetic"
    )
    response = client.post(f"/api/jobs/{job.id}/retry?workspace_id={WS}")
    assert response.status_code == 403
    db.expire_all()
    assert db.get(Job, job.id).status == JobStatus.FAILED.value
    assert not _audits(db, job.id, "job.manual_retry")


def test_manual_retry_of_another_workspace_is_not_found(client: TestClient, db):
    _admin(client)
    job = _job(db, workspace_id=2, status=JobStatus.FAILED.value, attempt=1)
    same = client.post(f"/api/jobs/{job.id}/retry?workspace_id={WS}")
    other = client.post(f"/api/jobs/{job.id}/retry?workspace_id=2")
    assert same.status_code == 404 and same.json()["detail"] == "Job not found"
    assert other.status_code == 404 and other.json()["detail"] == "Job not found"
    db.expire_all()
    assert db.get(Job, job.id).status == JobStatus.FAILED.value


def test_manual_retry_of_a_queued_job_is_a_conflict(client: TestClient, db):
    _admin(client)
    job = _job(db, status=JobStatus.QUEUED.value, attempt=0)
    response = client.post(f"/api/jobs/{job.id}/retry?workspace_id={WS}")
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "job_not_retryable"
    assert body["detail"] == body["error"]["message"]
    assert body["error"]["retryable"] is False
    db.expire_all()
    assert db.get(Job, job.id).status == JobStatus.QUEUED.value
    assert not _audits(db, job.id, "job.manual_retry")


def test_enqueue_after_cancel_does_not_resurrect_the_cancelled_job(db):
    from app.services.job_control import cancel_job
    from app.services.job_effects import enqueue_job

    key = f"parse_evidence:{uuid.uuid4().hex}"
    job = _job(db, idempotency_key=key)
    kind, _row = cancel_job(
        db, job.id, workspace_id=WS, actor_user_id=1, actor_email="admin@trust.local"
    )
    assert kind == "cancelled"
    again, created = enqueue_job(
        db,
        workspace_id=WS,
        kind="parse_evidence",
        payload={"synthetic": True},
        idempotency_key=key,
    )
    assert created is True
    assert again.id != job.id
    db.expire_all()
    assert db.get(Job, job.id).status == JobStatus.CANCELLED.value
