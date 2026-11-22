"""TC-09-006: a repeated questionnaire parse follows content and file hashes.

The same bytes are a no-op. A replaced file on the same questionnaire is parsed
once. An approved answer stays on the question it was given. A draft on a
question the new file dropped is removed with that question. Synthetic
workbooks only. This file is not skipped.
"""

from __future__ import annotations

import io
import json
import threading

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Answer, Job, Question, Questionnaire
from app.services.cell_mapping import content_hash, file_hash
from app.services.job_control import cancel_job, retry_job
from app.services.question_normalizer import normalize_question

WS = 1
OTHER_WS = 2
Q_KEEP = "Does the company encrypt data at rest?"
Q_APPROVED_DROPPED = "Is access reviewed every quarter?"
Q_DRAFT_DROPPED = "Are backups tested each month?"
Q_NEW = "Is logging enabled for admin actions?"


def _require_db(migrated_db) -> None:
    del migrated_db


def _workbook(questions: list[str]) -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.append(["Question", "Answer"])
    for question in questions:
        sheet.append([question, ""])
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def _store_file(store, workspace_id: int, name: str, blob: bytes) -> str:
    key = f"raw/{workspace_id}/{name}"
    store.data[(_raw_bucket(), key)] = blob
    return key


def _raw_bucket() -> str:
    from app.services.storage import StorageClient

    return StorageClient().bucket_raw


def _questionnaire(db: Session, workspace_id: int, key: str, filename: str) -> Questionnaire:
    row = Questionnaire(
        workspace_id=workspace_id,
        storage_key=key,
        filename=filename,
        status="uploaded",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _job(db: Session, workspace_id: int, questionnaire_id: int, key: str) -> Job:
    from app.models import JobStatus

    row = Job(
        workspace_id=workspace_id,
        kind="parse_questionnaire",
        status=JobStatus.RUNNING.value,
        payload=json.dumps({"questionnaire_id": questionnaire_id, "storage_key": key}),
        attempt=1,
        input_version=key,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _parse(db: Session, job: Job) -> None:
    from app import worker

    payload = json.loads(job.payload)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(worker, "_auto_classify_questionnaire", lambda *a, **k: None)
        worker.run_parse_questionnaire(job, db, payload)
    # The worker commits a parse that wrote questions. A superseded job leaves
    # the outcome on the row for the caller to commit, which is what the claim
    # loop does. Commit here so a later expire reloads that outcome.
    db.commit()


def _questions(db: Session, questionnaire_id: int) -> list[Question]:
    db.expire_all()
    return (
        db.query(Question)
        .filter(Question.questionnaire_id == questionnaire_id)
        .order_by(Question.id)
        .all()
    )


def _digest(text: str) -> str:
    return content_hash(normalize_question(text))


def _by_hash(rows: list[Question], text: str) -> list[Question]:
    digest = _digest(text)
    return [row for row in rows if row.content_hash == digest]


def _result(job: Job) -> dict:
    return json.loads(job.result or "{}")


def _history(db: Session, job: Job) -> dict:
    from starlette.requests import Request

    from app.api.routes.jobs import _history_job

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/jobs",
        "raw_path": b"/api/jobs",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 0),
        "server": ("127.0.0.1", 80),
    }
    return _history_job(Request(scope), db, job)


_LEAK_TABLES = (
    "answers",
    "questions",
    "job_effects",
    "audit_events",
    "questionnaires",
    "jobs",
)


def _watermarks(session: Session) -> dict[str, int]:
    marks: dict[str, int] = {}
    for table in _LEAK_TABLES:
        marks[table] = int(
            session.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table}")).scalar() or 0
        )
    return marks


def _delete_after(session: Session, marks: dict[str, int]) -> None:
    session.rollback()
    for table, mark in marks.items():
        session.execute(text(f"DELETE FROM {table} WHERE id > :m"), {"m": mark})
    session.commit()


@pytest.fixture
def db(migrated_db):
    _require_db(migrated_db)
    session = SessionLocal()
    marks = _watermarks(session)
    try:
        yield session
    finally:
        try:
            _delete_after(session, marks)
        finally:
            session.close()


@pytest.fixture
def store():
    data: dict[tuple[str, str], bytes] = {}
    from unittest.mock import patch

    def upload(self, bucket, key, body, **kw):
        del kw
        data[(bucket, key)] = body.read() if hasattr(body, "read") else body
        return key

    def download(self, bucket, key):
        return data.get((bucket, key), b"")

    with (
        patch("app.services.storage.StorageClient.upload", upload),
        patch("app.services.storage.StorageClient.download", download),
        patch("app.services.storage.StorageClient.exists", lambda self, b, k: (b, k) in data),
    ):
        yield type("Store", (), {"data": data})()


def test_same_bytes_replay_does_not_duplicate_questions(db, store):
    blob = _workbook([Q_KEEP, Q_DRAFT_DROPPED])
    key = _store_file(store, WS, "same.xlsx", blob)
    qnr = _questionnaire(db, WS, key, "same.xlsx")
    _parse(db, _job(db, WS, qnr.id, key))
    first = _questions(db, qnr.id)
    assert len(first) == 2
    first_ids = [row.id for row in first]
    replay = _job(db, WS, qnr.id, key)
    _parse(db, replay)
    second = _questions(db, qnr.id)
    assert [row.id for row in second] == first_ids
    assert {row.content_hash for row in second} == {row.content_hash for row in first}
    assert {row.original_file_hash for row in second} == {file_hash(blob)}
    assert _result(replay)["outcome"] == "reconciled"
    assert "input_version_changed" not in _result(replay).values()
    shown = _history(db, replay)
    assert shown["input_version_changed"] is False
    assert shown["questionnaire_status"] == "parsed"


def test_replaced_file_parses_once_and_keeps_approved_answers(db, store):
    original = _workbook([Q_KEEP, Q_APPROVED_DROPPED, Q_DRAFT_DROPPED])
    old_key = _store_file(store, WS, "original.xlsx", original)
    qnr = _questionnaire(db, WS, old_key, "original.xlsx")
    _parse(db, _job(db, WS, qnr.id, old_key))
    rows = _questions(db, qnr.id)
    kept = _by_hash(rows, Q_KEEP)[0]
    approved = _by_hash(rows, Q_APPROVED_DROPPED)[0]
    drafted = _by_hash(rows, Q_DRAFT_DROPPED)[0]
    db.add_all(
        [
            Answer(question_id=kept.id, text="Approved answer stays", status="approved"),
            Answer(question_id=approved.id, text="Approval survives the drop", status="approved"),
            Answer(question_id=drafted.id, text="Draft does not survive", status="draft"),
        ]
    )
    db.commit()
    replacement = _workbook([Q_KEEP, Q_NEW])
    new_key = _store_file(store, WS, "replacement.xlsx", replacement)
    qnr.storage_key = new_key
    qnr.filename = "replacement.xlsx"
    db.commit()
    stale = _job(db, WS, qnr.id, old_key)
    _parse(db, stale)
    assert _result(stale)["outcome"] == "superseded"
    assert _result(stale)["reason"] == "input_version_changed"
    assert len(_questions(db, qnr.id)) == 3

    fresh = _job(db, WS, qnr.id, new_key)
    _parse(db, fresh)
    parsed = _questions(db, qnr.id)
    assert _result(fresh).get("reason") != "input_version_changed"
    assert db.get(Questionnaire, qnr.id).status == "parsed"
    kept_after = _by_hash(parsed, Q_KEEP)
    assert len(kept_after) == 1 and kept_after[0].id == kept.id
    assert kept_after[0].original_file_hash == file_hash(replacement)
    kept_answer = db.query(Answer).filter(Answer.question_id == kept.id).one()
    assert kept_answer.status == "approved"
    assert kept_answer.text == "Approved answer stays"
    dropped = _by_hash(parsed, Q_APPROVED_DROPPED)
    assert len(dropped) == 1 and dropped[0].id == approved.id
    assert dropped[0].original_file_hash == file_hash(original)
    dropped_answer = db.query(Answer).filter(Answer.question_id == approved.id).one()
    assert dropped_answer.status == "approved"
    assert dropped_answer.text == "Approval survives the drop"
    assert _by_hash(parsed, Q_DRAFT_DROPPED) == []
    assert db.query(Answer).filter(Answer.question_id == drafted.id).count() == 0
    added = _by_hash(parsed, Q_NEW)
    assert len(added) == 1
    assert added[0].original_file_hash == file_hash(replacement)
    stale_view = _history(db, stale)
    assert stale_view["input_version_changed"] is True
    assert stale_view["questionnaire_status"] == "parsed"
    fresh_view = _history(db, fresh)
    assert fresh_view["input_version_changed"] is False
    assert fresh_view["questionnaire_status"] == "parsed"

    again = _job(db, WS, qnr.id, new_key)
    _parse(db, again)
    replayed = _questions(db, qnr.id)
    assert [row.id for row in replayed] == [row.id for row in parsed]
    assert _result(again)["outcome"] == "reconciled"
    assert _history(db, again)["input_version_changed"] is False
    assert _history(db, stale)["input_version_changed"] is True
    assert _history(db, stale)["questionnaire_status"] == "parsed"


def test_input_version_changed_is_cleared_on_the_parse_of_the_new_bytes(db, store):
    blob = _workbook([Q_KEEP])
    old_key = _store_file(store, WS, "before.xlsx", blob)
    qnr = _questionnaire(db, WS, old_key, "before.xlsx")
    qnr.storage_key = _store_file(store, WS, "after.xlsx", _workbook([Q_NEW]))
    db.commit()
    stale = _job(db, WS, qnr.id, old_key)
    _parse(db, stale)
    assert _result(stale)["reason"] == "input_version_changed"
    current_key = qnr.storage_key
    current = _job(db, WS, qnr.id, current_key)
    _parse(db, current)
    assert _result(current).get("reason") != "input_version_changed"
    assert len(_by_hash(_questions(db, qnr.id), Q_NEW)) == 1
    assert _history(db, stale)["input_version_changed"] is True
    assert _history(db, stale)["questionnaire_status"] == "parsed"
    assert _history(db, current)["input_version_changed"] is False
    assert _history(db, current)["questionnaire_status"] == "parsed"


def test_cross_workspace_parse_does_not_insert_or_replace(db, store):
    blob = _workbook([Q_KEEP])
    own_key = _store_file(store, WS, "own.xlsx", blob)
    other_key = _store_file(store, OTHER_WS, "other.xlsx", blob)
    own = _questionnaire(db, WS, own_key, "own.xlsx")
    other = _questionnaire(db, OTHER_WS, other_key, "other.xlsx")
    mismatched = _job(db, WS, other.id, other_key)
    with pytest.raises(ValueError, match="workspace mismatch"):
        _parse(db, mismatched)
    assert _questions(db, other.id) == []
    assert _questions(db, own.id) == []
    _parse(db, _job(db, OTHER_WS, other.id, other_key))
    _parse(db, _job(db, WS, own.id, own_key))
    assert len(_questions(db, own.id)) == 1
    assert len(_questions(db, other.id)) == 1
    assert _questions(db, own.id)[0].id != _questions(db, other.id)[0].id
    _parse(db, _job(db, WS, own.id, own_key))
    assert len(_questions(db, own.id)) == 1
    assert len(_questions(db, other.id)) == 1


def test_cancel_and_retry_keep_questionnaire_state(db, store):
    blob = _workbook([Q_KEEP])
    key = _store_file(store, WS, "cancel.xlsx", blob)
    qnr = _questionnaire(db, WS, key, "cancel.xlsx")
    _parse(db, _job(db, WS, qnr.id, key))
    parsed_ids = [row.id for row in _questions(db, qnr.id)]
    running = _job(db, WS, qnr.id, key)
    kind, cancelled = cancel_job(
        db,
        running.id,
        workspace_id=WS,
        actor_user_id=1,
        actor_email="admin@trust.local",
    )
    assert kind == "cancelled"
    assert cancelled.status == "cancelled"
    db.expire_all()
    assert db.get(Questionnaire, qnr.id).status == "parsed"
    assert [row.id for row in _questions(db, qnr.id)] == parsed_ids
    retry_kind, retried = retry_job(
        db,
        running.id,
        workspace_id=WS,
        actor_user_id=1,
        actor_email="admin@trust.local",
    )
    assert retry_kind == "retried"
    assert retried.status == "queued"
    retried.status = "running"
    db.commit()
    _parse(db, retried)
    assert [row.id for row in _questions(db, qnr.id)] == parsed_ids
    assert db.get(Questionnaire, qnr.id).status == "parsed"
    assert _history(db, retried)["questionnaire_status"] == "parsed"
    assert _history(db, retried)["input_version_changed"] is False


def test_concurrent_delivery_of_the_same_job_inserts_once(db, store):
    blob = _workbook([Q_KEEP, Q_NEW])
    key = _store_file(store, WS, "concurrent.xlsx", blob)
    qnr = _questionnaire(db, WS, key, "concurrent.xlsx")
    job = _job(db, WS, qnr.id, key)
    job_id = job.id
    qnr_id = qnr.id
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def deliver() -> None:
        session = SessionLocal()
        try:
            from app import worker
            from app.services.file_service import FileService

            running = session.query(Job).filter(Job.id == job_id).one()
            real = FileService.download_raw

            def gated(self, storage_key):
                barrier.wait(timeout=10)
                return real(self, storage_key)

            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(worker, "_auto_classify_questionnaire", lambda *a, **k: None)
                patch.setattr(FileService, "download_raw", gated)
                worker.run_parse_questionnaire(running, session, json.loads(running.payload))
        except BaseException as exc:  # noqa: BLE001 — the assertion reports the thread error
            errors.append(exc)
        finally:
            session.close()

    first = threading.Thread(target=deliver)
    second = threading.Thread(target=deliver)
    first.start()
    second.start()
    first.join(timeout=30)
    second.join(timeout=30)
    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    rows = _questions(db, qnr_id)
    assert len(rows) == 2
    assert {row.original_file_hash for row in rows} == {file_hash(blob)}
    assert len({row.content_hash for row in rows}) == 2


def test_history_hides_an_unknown_questionnaire_status(db, store):
    blob = _workbook([Q_KEEP])
    key = _store_file(store, WS, "status.xlsx", blob)
    qnr = _questionnaire(db, WS, key, "status.xlsx")
    _parse(db, _job(db, WS, qnr.id, key))
    qnr.status = "PRIVATE status"
    db.commit()
    shown = _history(db, _job(db, WS, qnr.id, key))
    assert shown["questionnaire_status"] is None
    assert shown["input_version_changed"] is False
    assert "PRIVATE" not in json.dumps(shown)
