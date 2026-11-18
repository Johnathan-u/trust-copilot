"""TC-15-038d: a locked job row must not hang the running-progress publisher.

``publish_running_progress`` takes ``FOR UPDATE`` on the job row from the
worker's own thread. The job transaction does not hold that lock today. This
test holds it anyway, the way a later change might, and requires the publisher
to return ``False`` while the lock is still held.
"""

from __future__ import annotations

import json
import threading
import time

import pytest
from sqlalchemy import text

# Several times the 250ms lock_timeout, and far below an unbounded wait.
RETURN_BOUND_SECONDS = 1.5


@pytest.fixture
def db(_ensure_test_data):
    if not _ensure_test_data:
        pytest.skip("Postgres test DB unavailable")
    from app.core.database import SessionLocal

    session = SessionLocal()
    max_id, count = session.execute(text("SELECT COALESCE(MAX(id), 0), COUNT(*) FROM jobs")).one()
    snap = (int(max_id), int(count))
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
            cleanup.execute(text("DELETE FROM jobs WHERE id > :max_id"), {"max_id": snap[0]})
            cleanup.commit()
            got = cleanup.execute(text("SELECT COUNT(*) FROM jobs")).scalar()
            assert int(got) == snap[1]
        finally:
            cleanup.close()


def _insert_running_job(db, owner: str) -> int:
    from app.models import Job, JobStatus

    job = Job(
        workspace_id=1,
        kind="parse_questionnaire",
        status=JobStatus.RUNNING.value,
        payload="{}",
        attempt=1,
        max_attempts=3,
        lease_owner=owner,
        result=json.dumps({"generated": 0, "total": 3}),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return int(job.id)


def _read_result(job_id: int) -> dict | None:
    from app.core.database import SessionLocal

    reader = SessionLocal()
    try:
        reader.execute(text("SET LOCAL statement_timeout = '2s'"))
        raw = reader.execute(
            text("SELECT result FROM jobs WHERE id = :id"), {"id": job_id}
        ).scalar()
    finally:
        reader.rollback()
        reader.close()
    if not raw:
        return None
    data = json.loads(raw)
    assert isinstance(data, dict)
    return data


def test_locked_job_row_skips_running_progress_quickly(db):
    from app import worker
    from app.core.database import SessionLocal

    owner = "tc-15-038d-lock"
    job_id = _insert_running_job(db, owner)
    holder = SessionLocal()
    outcome: dict = {}

    def run() -> None:
        started = time.monotonic()
        try:
            outcome["value"] = worker.publish_running_progress(job_id, owner, 1, 3, force=True)
        except Exception as exc:
            outcome["error"] = exc
        finally:
            outcome["elapsed"] = time.monotonic() - started

    thread = threading.Thread(target=run, daemon=True)
    try:
        holder.execute(text("SELECT id FROM jobs WHERE id = :id FOR UPDATE"), {"id": job_id})
        thread.start()
        thread.join(RETURN_BOUND_SECONDS)
        assert (
            not thread.is_alive()
        ), "publish_running_progress did not return while the job row stayed locked"
        assert outcome.get("error") is None
        assert outcome["value"] is False
        assert outcome["elapsed"] < RETURN_BOUND_SECONDS
        assert _read_result(job_id) == {"generated": 0, "total": 3}
    finally:
        holder.rollback()
        holder.close()
        thread.join(5)

    assert worker.publish_running_progress(job_id, owner, 1, 3, force=True) is True
    assert _read_result(job_id) == {"generated": 1, "total": 3}


def test_unlocked_job_row_still_publishes_running_progress(db):
    from app import worker

    owner = "tc-15-038d-open"
    job_id = _insert_running_job(db, owner)
    assert worker.publish_running_progress(job_id, owner, 2, 3, force=True) is True
    assert _read_result(job_id) == {"generated": 2, "total": 3}
