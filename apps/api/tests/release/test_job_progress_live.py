"""A second session can read parse progress before the parse transaction commits.

The worker publishes ``generated``/``total`` on its own short connection. The
question rows stay in the worker transaction until the end.
"""

from __future__ import annotations

import json
import threading

import pytest
from sqlalchemy import text

TABLES = ("questions", "job_effects", "jobs", "questionnaires")
DELETE_ORDER = ("questions", "job_effects", "jobs", "questionnaires")


class _Store:
    def __init__(self, blob: bytes):
        self.blob = blob
        self.bucket_raw = "raw"
        self.bucket_exports = "exports"

    def download(self, bucket: str, key: str) -> bytes:
        return self.blob


@pytest.fixture
def db(_ensure_test_data):
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


def test_parse_progress_is_visible_to_another_session_while_running(db, monkeypatch):
    from app import worker
    from app.core.database import SessionLocal
    from app.models import Job, JobStatus, Questionnaire

    questionnaire = Questionnaire(
        workspace_id=1,
        filename="questions.xlsx",
        storage_key="raw/1/questions.xlsx",
        status="uploaded",
    )
    db.add(questionnaire)
    db.commit()
    db.refresh(questionnaire)
    job = Job(
        workspace_id=1,
        kind="parse_questionnaire",
        status=JobStatus.RUNNING.value,
        payload=json.dumps(
            {"questionnaire_id": questionnaire.id, "storage_key": questionnaire.storage_key}
        ),
        attempt=1,
        max_attempts=3,
        lease_owner="owner-token",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    job_id = job.id
    questions = [{"text": "one"}, {"text": "two"}, {"text": "three"}]
    monkeypatch.setattr(worker, "parse_xlsx_questionnaire", lambda path: list(questions))
    monkeypatch.setattr(worker, "_auto_classify_questionnaire", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker, "StorageClient", lambda: _Store(b"workbook"))
    seen = threading.Event()
    release = threading.Event()
    real = worker.publish_running_progress

    def wrapped(published_job_id, owner, generated, total, **kwargs):
        wrote = real(published_job_id, owner, generated, total, **kwargs)
        if generated == 1 and wrote:
            seen.set()
            assert release.wait(5)
        return wrote

    monkeypatch.setattr(worker, "publish_running_progress", wrapped)
    errors: list[BaseException] = []

    def run() -> None:
        session = SessionLocal()
        try:
            current = session.get(Job, job_id)
            worker.run_parse_questionnaire(
                current,
                session,
                {"questionnaire_id": questionnaire.id, "storage_key": questionnaire.storage_key},
            )
        except Exception as exc:
            errors.append(exc)
            release.set()
        finally:
            session.close()

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert seen.wait(5), errors
        reader = SessionLocal()
        try:
            mid = json.loads(reader.get(Job, job_id).result)
        finally:
            reader.close()
        assert 0 < mid["generated"] < mid["total"]
        assert mid["total"] == len(questions)
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert errors == []
    reader = SessionLocal()
    try:
        done = json.loads(reader.get(Job, job_id).result)
    finally:
        reader.close()
    assert done["generated"] == done["total"] == len(questions)
