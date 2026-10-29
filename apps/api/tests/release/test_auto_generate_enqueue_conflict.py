"""TC-10-003d: parse completion survives an auto-generate enqueue conflict.

Synthetic rows only, on the side ``*_test`` database. No network and no provider calls.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.core.database import SessionLocal
from app.models import Job, JobStatus, Question, Questionnaire
from app.models.workspace import Workspace
from app.services.job_effects import job_idempotency_key

WS = 1
_OPENAPI_ID = re.compile(r"TC-\d{2}-[A-Za-z0-9]+|QNR-\d+")
_TOUCHED_OPERATIONS = {
    "upload_questionnaire",
    "list_questionnaires",
    "get_questionnaire",
}
# Same shape as TC-21-005's _counts(): snapshot these before the test and require the
# same counts after teardown. job_effects is included because a claimed job can write one;
# deleting the job cascades that row.
_COUNTED = (
    "audit_events",
    "jobs",
    "questionnaires",
    "questions",
    "idempotency_keys",
    "documents",
    "evidence_gaps",
    "job_effects",
)


def _counts() -> dict[str, int]:
    session = SessionLocal()
    try:
        return {
            name: int(session.execute(text(f"SELECT count(*) FROM {name}")).scalar() or 0)
            for name in _COUNTED
        }
    finally:
        session.close()


@pytest.fixture
def db(_ensure_test_data):
    if not _ensure_test_data:
        pytest.skip("Postgres test DB unavailable")
    session = SessionLocal()
    marks = {
        table: int(session.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table}")).scalar() or 0)
        for table in ("questionnaires", "questions", "jobs", "audit_events")
    }
    before_counts = _counts()
    try:
        yield session
    finally:
        try:
            session.rollback()
            session.execute(
                text("DELETE FROM audit_events WHERE id > :m"),
                {"m": marks["audit_events"]},
            )
            session.execute(
                text(
                    "DELETE FROM questions WHERE questionnaire_id IN "
                    "(SELECT id FROM questionnaires WHERE id > :m)"
                ),
                {"m": marks["questionnaires"]},
            )
            session.execute(text("DELETE FROM jobs WHERE id > :m"), {"m": marks["jobs"]})
            session.execute(
                text("DELETE FROM questionnaires WHERE id > :m"), {"m": marks["questionnaires"]}
            )
            session.commit()
            after_counts = _counts()
            assert after_counts == before_counts, {"before": before_counts, "after": after_counts}
        finally:
            session.close()


@pytest.fixture
def automation_on(db):
    """Turn automation on for workspace 1 and put the previous value back."""
    ws = db.query(Workspace).filter(Workspace.id == WS).one()
    previous = bool(ws.ai_automate_everything)
    ws.ai_automate_everything = True
    db.commit()
    try:
        yield
    finally:
        restore = SessionLocal()
        try:
            row = restore.query(Workspace).filter(Workspace.id == WS).one()
            row.ai_automate_everything = previous
            restore.commit()
        finally:
            restore.close()


def _questionnaire(db) -> Questionnaire:
    qnr = Questionnaire(
        workspace_id=WS,
        filename=f"synthetic-{uuid.uuid4().hex}.xlsx",
        storage_key=f"raw/{WS}/{uuid.uuid4().hex}.xlsx",
        status="parsed",
    )
    db.add(qnr)
    db.commit()
    db.refresh(qnr)
    db.add(Question(questionnaire_id=qnr.id, text="Synthetic question for auto-generate?"))
    db.commit()
    return qnr


def _queued_parse(db, qnr: Questionnaire) -> Job:
    job = Job(
        workspace_id=WS,
        kind="parse_questionnaire",
        status=JobStatus.QUEUED.value,
        payload=json.dumps({"questionnaire_id": qnr.id, "storage_key": qnr.storage_key}),
        attempt=0,
        max_attempts=3,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _generate_key(qnr_id: int) -> str:
    # Same parts as automation_service.maybe_auto_generate (model and style default to None).
    return job_idempotency_key("generate_answers", WS, qnr_id, None, None)


def _worker_for(monkeypatch, job_id: int):
    from app import worker

    monkeypatch.setattr(worker, "SessionFactory", SessionLocal)
    monkeypatch.setattr(worker, "last_compliance_webhook_run", time.time())
    monkeypatch.setattr(worker, "last_usage_cleanup_run", time.time())
    monkeypatch.setattr(worker, "last_dedupe_prune_run", time.time())
    real_filter = worker.claimable_filter
    monkeypatch.setattr(
        worker, "claimable_filter", lambda now=None: real_filter(now) & (Job.id == job_id)
    )
    monkeypatch.setattr(worker, "notify_workspace", lambda *a, **k: None)
    monkeypatch.setattr(worker, "run_job", lambda job, session: None)
    return worker


def _committed_job(job_id: int) -> dict:
    session = SessionLocal()
    try:
        job = session.get(Job, job_id)
        assert job is not None
        try:
            result = json.loads(job.result) if job.result else None
        except (TypeError, ValueError):
            result = job.result
        return {
            "status": job.status,
            "completed_at": job.completed_at,
            "result": result,
            "error": job.error,
            "error_code": job.error_code,
        }
    finally:
        session.close()


def _jobs_with_key(key: str) -> list[dict]:
    session = SessionLocal()
    try:
        rows = session.query(Job).filter(Job.idempotency_key == key).order_by(Job.id).all()
        return [
            {
                "id": row.id,
                "status": row.status,
                "kind": row.kind,
                "payload": row.payload,
                "workspace_id": row.workspace_id,
            }
            for row in rows
        ]
    finally:
        session.close()


def test_parse_job_stays_completed_when_auto_generate_enqueue_conflicts(
    db, automation_on, monkeypatch, caplog
):
    """The queued-slot race rolls the worker session back. The parse job must still be completed.

    The conflict is logged and stored on the job result. The pre-existing generate row is the only
    one with that key: the lost inserts are rolled back, so nothing half-committed remains.
    """
    qnr = _questionnaire(db)
    key = _generate_key(qnr.id)
    # Holds the QUEUED unique slot, but its payload does not match maybe_auto_generate's
    # questionnaire filter, so the worker still calls enqueue_job and loses the race.
    winner = Job(
        workspace_id=WS,
        kind="generate_answers",
        status=JobStatus.QUEUED.value,
        payload=json.dumps({"synthetic": "held-slot"}),
        idempotency_key=key,
    )
    db.add(winner)
    db.commit()
    db.refresh(winner)
    parse_job = _queued_parse(db, qnr)
    worker = _worker_for(monkeypatch, parse_job.id)

    def fake_run(job, session):
        job.result = json.dumps({"count": 1})

    monkeypatch.setattr(worker, "run_job", fake_run)
    caplog.set_level(logging.WARNING)
    with patch("app.services.job_effects._queued_with_key", return_value=None):
        assert worker._process_one_job() is True

    saved = _committed_job(parse_job.id)
    assert saved["status"] == JobStatus.COMPLETED.value
    assert saved["completed_at"] is not None
    assert saved["error"] is None
    assert saved["result"] == {"count": 1, "auto_generate": "enqueue_conflict"}
    assert "auto-generate enqueue conflict" in caplog.text
    assert "lost the queued-slot race" in caplog.text

    rows = _jobs_with_key(key)
    assert rows == [
        {
            "id": winner.id,
            "status": JobStatus.QUEUED.value,
            "kind": "generate_answers",
            "payload": json.dumps({"synthetic": "held-slot"}),
            "workspace_id": WS,
        }
    ]


def test_happy_path_enqueues_exactly_one_generate_job(db, automation_on, monkeypatch, caplog):
    qnr = _questionnaire(db)
    key = _generate_key(qnr.id)
    parse_job = _queued_parse(db, qnr)
    worker = _worker_for(monkeypatch, parse_job.id)

    caplog.set_level(logging.WARNING)
    assert worker._process_one_job() is True

    saved = _committed_job(parse_job.id)
    assert saved["status"] == JobStatus.COMPLETED.value
    assert saved["completed_at"] is not None
    result = saved["result"] or {}
    assert result.get("auto_generate") != "enqueue_conflict"
    assert "enqueue conflict" not in caplog.text.lower()

    rows = _jobs_with_key(key)
    assert len(rows) == 1
    assert rows[0]["status"] == JobStatus.QUEUED.value
    assert rows[0]["kind"] == "generate_answers"
    assert json.loads(rows[0]["payload"]) == {"questionnaire_id": qnr.id, "workspace_id": WS}


def test_non_conflict_exception_keeps_parse_job_completed(db, automation_on, monkeypatch):
    """A non-conflict failure from auto-generate is still swallowed. The parse job completes.

    No generate row is inserted. This is today's behavior: the worker does not fail the parse.
    """
    qnr = _questionnaire(db)
    key = _generate_key(qnr.id)
    parse_job = _queued_parse(db, qnr)
    worker = _worker_for(monkeypatch, parse_job.id)

    def boom(*args, **kwargs):
        raise RuntimeError("synthetic non-conflict")

    with patch("app.services.job_effects.enqueue_job", side_effect=boom):
        assert worker._process_one_job() is True

    saved = _committed_job(parse_job.id)
    assert saved["status"] == JobStatus.COMPLETED.value
    assert saved["completed_at"] is not None
    assert saved["error"] is None
    result = saved["result"] or {}
    assert result.get("auto_generate") != "enqueue_conflict"
    assert _jobs_with_key(key) == []


def test_non_conflict_rollback_does_not_drop_committed_parse_completion(
    db, automation_on, monkeypatch
):
    """A non-conflict error that rolls the session back must not undo the parse completion.

    Safer than today's implicit boundary: the completion is committed before auto-generate, so a
    later rollback cannot return the job to running. The worker still does not fail the parse,
    and no generate row is left behind.
    """
    qnr = _questionnaire(db)
    key = _generate_key(qnr.id)
    parse_job = _queued_parse(db, qnr)
    worker = _worker_for(monkeypatch, parse_job.id)

    def boom(session, **kwargs):
        session.rollback()
        raise RuntimeError("synthetic non-conflict after rollback")

    with patch("app.services.job_effects.enqueue_job", side_effect=boom):
        assert worker._process_one_job() is True

    saved = _committed_job(parse_job.id)
    assert saved["status"] == JobStatus.COMPLETED.value
    assert saved["completed_at"] is not None
    assert saved["error"] is None
    assert _jobs_with_key(key) == []


def test_touched_route_openapi_has_no_ticket_or_requirement_ids():
    """Published summary and description of the questionnaire routes edited here."""
    from app.main import app

    schema = app.openapi()
    checked = []
    violations = []
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            operation_id = operation.get("operationId") or ""
            if not any(name in operation_id for name in _TOUCHED_OPERATIONS):
                continue
            text = "\n".join(
                [
                    operation.get("summary") or "",
                    operation.get("description") or "",
                ]
            )
            checked.append(operation_id)
            found = _OPENAPI_ID.findall(text)
            if found:
                violations.append((method, path, found))
    assert any("upload_questionnaire" in name for name in checked)
    assert any("list_questionnaires" in name for name in checked)
    assert any("get_questionnaire" in name for name in checked)
    assert violations == []
