"""TC-10-003: idempotent parse / index / generate / export side effects.

Every test uses synthetic data, an in-memory fake object store, and fake embeddings / retrieval. No model or
provider call is made (OPENAI_API_KEY is either empty or a fake placeholder and the client is never invoked).
Crashes are injected by raising from a patched function immediately before or after a side effect commits.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, text

from app.core.database import SessionLocal, engine
from app.models import (
    Answer,
    Chunk,
    Document,
    ExportRecord,
    Job,
    JobStatus,
    Question,
    Questionnaire,
)
from app.models.job_effect import EFFECT_SETTLED, EFFECT_STARTED, EFFECT_UNCERTAIN, JobEffect
from app.models.workspace_quota import WorkspaceUsage
from app.services import job_effects as je
from app.services.answer_generation import AnswerWriteGuard, _WRITE_GUARD, _upsert_answer

WS = 1
FIXTURE_XLSX = (
    Path(__file__).resolve().parents[1] / "fixtures" / "questionnaires" / "simple_soc2.xlsx"
)


class Crash(RuntimeError):
    """Injected worker crash."""


# Rows these tests commit (they have to: a second connection must see them). Delete only rows
# created during the test so a later test that does ``.first()`` on workspace 1 is not handed
# one of these questionnaires. Children are listed before parents.
_LEAK_TABLES = (
    "evidence_gaps",
    "question_mapping_signals",
    "question_mapping_preferences",
    "export_records",
    "answers",
    "questions",
    "chunks",
    "job_effects",
    "questionnaires",
    "documents",
    "jobs",
    "workspace_usage",
    "idempotency_keys",
    "audit_events",
    "in_app_notifications",
)


def _id_watermarks(session) -> dict[str, int]:
    marks: dict[str, int] = {}
    for table in _LEAK_TABLES:
        marks[table] = int(
            session.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table}")).scalar() or 0
        )
    return marks


def _delete_rows_after(session, marks: dict[str, int]) -> None:
    session.rollback()
    for table, mark in marks.items():
        session.execute(text(f"DELETE FROM {table} WHERE id > :m"), {"m": mark})
    session.commit()


@pytest.fixture
def db(_ensure_test_data):
    if not _ensure_test_data:
        pytest.skip("Postgres test DB unavailable")
    s = SessionLocal()
    marks = _id_watermarks(s)
    try:
        yield s
    finally:
        try:
            _delete_rows_after(s, marks)
        finally:
            s.close()


@pytest.fixture
def store():
    """In-memory fake object store patched over StorageClient."""
    data: dict[tuple[str, str], bytes] = {}
    uploads: list[tuple[str, str]] = []

    def upload(self, bucket, key, body, **kw):
        data[(bucket, key)] = body.read() if hasattr(body, "read") else body
        uploads.append((bucket, key))
        return key

    def download(self, bucket, key):
        return data.get((bucket, key), b"")

    with (
        patch("app.services.storage.StorageClient.upload", upload),
        patch("app.services.storage.StorageClient.download", download),
        patch("app.services.storage.StorageClient.exists", lambda self, b, k: (b, k) in data),
        patch(
            "app.services.storage.StorageClient.download_stream",
            lambda self, b, k: io.BytesIO(data.get((b, k), b"")),
        ),
    ):
        yield type("Store", (), {"data": data, "uploads": uploads})


def _raw_bucket() -> str:
    from app.services.storage import StorageClient

    return StorageClient().bucket_raw


def _claimed_job(
    db, kind: str, payload: dict, input_version: str | None = None, attempt: int = 1
) -> Job:
    job = Job(
        workspace_id=WS,
        kind=kind,
        status=JobStatus.RUNNING.value,
        payload=json.dumps(payload),
        attempt=attempt,
        input_version=input_version,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _effects(db, job_id: int) -> list[JobEffect]:
    return db.query(JobEffect).filter(JobEffect.job_id == job_id).order_by(JobEffect.id).all()


# ---------------------------------------------------------------------------------------------------------
# Enqueue dedupe
# ---------------------------------------------------------------------------------------------------------


def test_enqueue_dedupes_only_queued_jobs(db):
    key = je.job_idempotency_key("export", WS, uuid.uuid4().hex, "xlsx")
    j1, c1 = je.enqueue_job(
        db, workspace_id=WS, kind="export", payload={"x": 1}, idempotency_key=key
    )
    j2, c2 = je.enqueue_job(
        db, workspace_id=WS, kind="export", payload={"x": 1}, idempotency_key=key
    )
    assert c1 is True and c2 is False and j1.id == j2.id
    # Once running, the job may already have read its input: a new request gets its own job.
    j1.status = JobStatus.RUNNING.value
    db.commit()
    j3, c3 = je.enqueue_job(
        db, workspace_id=WS, kind="export", payload={"x": 1}, idempotency_key=key
    )
    assert c3 is True and j3.id != j1.id
    # Different workspace / kind never collide.
    j4, c4 = je.enqueue_job(
        db, workspace_id=2, kind="export", payload={"x": 1}, idempotency_key=key
    )
    assert c4 is True and j4.id not in (j1.id, j3.id)


def test_enqueue_race_returns_winner_via_unique_index(db):
    key = je.job_idempotency_key("generate_answers", WS, uuid.uuid4().hex, None, None)
    winner, _ = je.enqueue_job(
        db, workspace_id=WS, kind="generate_answers", payload={}, idempotency_key=key
    )
    calls = {"n": 0}
    real = je._queued_with_key

    def first_miss(*a, **kw):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(*a, **kw)

    with patch.object(je, "_queued_with_key", side_effect=first_miss):
        loser, created = je.enqueue_job(
            db, workspace_id=WS, kind="generate_answers", payload={}, idempotency_key=key
        )
    assert created is False and loser.id == winner.id
    n = (
        db.query(func.count(Job.id))
        .filter(Job.idempotency_key == key, Job.status == "queued")
        .scalar()
    )
    assert n == 1


def test_enqueue_retries_once_when_race_winner_already_left_queued(db):
    """TC-10-003a (a): the race winner is claimed by a worker before the loser looks it up.

    The loser's insert hit the partial unique index, but the winner is RUNNING by the time of the lookup, so
    the slot is free again: the loser retries the insert once and gets its own job instead of a 500.
    """
    key = je.job_idempotency_key("export", WS, uuid.uuid4().hex, "xlsx")
    winner, _ = je.enqueue_job(
        db, workspace_id=WS, kind="export", payload={"x": 1}, idempotency_key=key
    )
    calls = {"n": 0}
    real = je._queued_with_key

    def racing_lookup(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # pre-check ran before the winner committed
        if calls["n"] == 2:
            # Between the loser's IntegrityError and its lookup, a worker claims the winner.
            other = SessionLocal()
            try:
                other.execute(
                    text("UPDATE jobs SET status = 'running' WHERE id = :id"), {"id": winner.id}
                )
                other.commit()
            finally:
                other.close()
        return real(*a, **kw)

    with patch.object(je, "_queued_with_key", side_effect=racing_lookup):
        loser, created = je.enqueue_job(
            db, workspace_id=WS, kind="export", payload={"x": 1}, idempotency_key=key
        )
    assert created is True and loser.id != winner.id
    assert calls["n"] == 3  # pre-check, post-conflict lookup, retry pre-check
    db.expire_all()
    rows = {j.id: j.status for j in db.query(Job).filter(Job.idempotency_key == key).all()}
    assert rows == {winner.id: "running", loser.id: "queued"}


def test_enqueue_retries_only_once_then_raises(db):
    """TC-10-003a (a): the retry is bounded; a second unexplained conflict still raises.

    TC-10-003b: it raises the typed, retryable ``EnqueueConflictError`` (an IntegrityError is its cause).
    """
    from sqlalchemy.exc import IntegrityError

    key = je.job_idempotency_key("export", WS, uuid.uuid4().hex, "xlsx")
    je.enqueue_job(db, workspace_id=WS, kind="export", payload={"x": 1}, idempotency_key=key)
    calls = {"n": 0}

    def always_miss(*a, **kw):
        calls["n"] += 1
        return None

    with patch.object(je, "_queued_with_key", side_effect=always_miss):
        with pytest.raises(je.EnqueueConflictError) as exc_info:
            je.enqueue_job(
                db, workspace_id=WS, kind="export", payload={"x": 1}, idempotency_key=key
            )
    assert isinstance(exc_info.value.__cause__, IntegrityError)
    db.rollback()
    # pre-check + lookup on the first attempt, pre-check + lookup on the single retry.
    assert calls["n"] == 4


# ---------------------------------------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------------------------------------


def _qnr_with_file(db, store) -> tuple[Questionnaire, str]:
    key = f"raw/{WS}/{uuid.uuid4().hex}.xlsx"
    store.data[(_raw_bucket(), key)] = FIXTURE_XLSX.read_bytes()
    qnr = Questionnaire(
        workspace_id=WS, storage_key=key, filename="synthetic.xlsx", status="uploaded"
    )
    db.add(qnr)
    db.commit()
    db.refresh(qnr)
    return qnr, key


def _n_questions(db, qnr_id: int) -> int:
    db.expire_all()
    return db.query(func.count(Question.id)).filter(Question.questionnaire_id == qnr_id).scalar()


def test_parse_crash_after_commit_does_not_duplicate_questions(db, store):
    from app import worker

    qnr, key = _qnr_with_file(db, store)
    job = _claimed_job(
        db, "parse_questionnaire", {"questionnaire_id": qnr.id, "storage_key": key}, key
    )
    with patch.object(
        worker, "_auto_classify_questionnaire", side_effect=Crash("after questions commit")
    ):
        with pytest.raises(Crash):
            worker.run_parse_questionnaire(job, db, json.loads(job.payload))
    db.rollback()
    first = _n_questions(db, qnr.id)
    assert first > 0
    with patch.object(worker, "_auto_classify_questionnaire") as classify:
        worker.run_parse_questionnaire(job, db, json.loads(job.payload))
        classify.assert_called_once()  # classification (cached per question) may finish on the re-run
    assert json.loads(job.result)["outcome"] == "already_applied"
    assert _n_questions(db, qnr.id) == first


def test_parse_crash_before_commit_applies_exactly_once(db, store):
    from app import worker

    qnr, key = _qnr_with_file(db, store)
    job = _claimed_job(
        db, "parse_questionnaire", {"questionnaire_id": qnr.id, "storage_key": key}, key
    )
    with patch.object(je.JobEffects, "mark_applied", side_effect=Crash("before questions commit")):
        with pytest.raises(Crash):
            worker.run_parse_questionnaire(job, db, json.loads(job.payload))
    db.rollback()
    assert _n_questions(db, qnr.id) == 0
    with patch.object(worker, "_auto_classify_questionnaire"):
        worker.run_parse_questionnaire(job, db, json.loads(job.payload))
    n = _n_questions(db, qnr.id)
    assert n > 0
    assert [e.effect for e in _effects(db, job.id)] == ["questions"]


def test_parse_second_job_reconciles_instead_of_duplicating(db, store):
    from app import worker

    qnr, key = _qnr_with_file(db, store)
    payload = {"questionnaire_id": qnr.id, "storage_key": key}
    with patch.object(worker, "_auto_classify_questionnaire"):
        worker.run_parse_questionnaire(
            _claimed_job(db, "parse_questionnaire", payload, key), db, payload
        )
        n = _n_questions(db, qnr.id)
        job2 = _claimed_job(db, "parse_questionnaire", payload, key)
        worker.run_parse_questionnaire(job2, db, payload)
    assert json.loads(job2.result)["outcome"] == "reconciled"
    assert _n_questions(db, qnr.id) == n


@pytest.mark.parametrize("change", ["storage_key", "deleted"])
def test_parse_stale_input_is_superseded(db, store, change):
    from app import worker

    qnr, key = _qnr_with_file(db, store)
    payload = {"questionnaire_id": qnr.id, "storage_key": key}
    job = _claimed_job(db, "parse_questionnaire", payload, key)
    if change == "storage_key":
        qnr.storage_key = f"raw/{WS}/{uuid.uuid4().hex}.xlsx"
    else:
        qnr.deleted_at = datetime.utcnow()
    db.commit()
    worker.run_parse_questionnaire(job, db, payload)
    assert json.loads(job.result)["outcome"] == "superseded"
    assert _n_questions(db, qnr.id) == 0


# ---------------------------------------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------------------------------------


def _doc_with_file(db, store) -> Document:
    key = f"raw/{WS}/{uuid.uuid4().hex}.txt"
    store.data[(_raw_bucket(), key)] = (
        f"Synthetic policy {uuid.uuid4().hex}. We encrypt data at rest with AES-256 and review access quarterly."
    ).encode()
    doc = Document(
        workspace_id=WS, storage_key=key, filename="synthetic-policy.txt", status="uploaded"
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


class FakeEmbed:
    def __init__(self, fail: bool = False):
        self.calls = 0
        self.fail = fail

    def __call__(self, texts, on_failure=None):
        self.calls += 1
        if self.fail:
            raise Crash("provider call interrupted")
        return [[0.001] * 1536 for _ in texts]


def _n_chunks(db, doc_id: int) -> int:
    db.expire_all()
    return db.query(func.count(Chunk.id)).filter(Chunk.document_id == doc_id).scalar()


def _run_index(db, job, embed):
    from app import worker

    with (
        patch("app.services.index_service.embed_texts", embed),
        patch("app.services.tag_service.auto_tag_document", return_value=0),
    ):
        worker.run_index_document(job, db, json.loads(job.payload))


def test_index_rerun_after_commit_does_not_reembed_or_duplicate(db, store):
    doc = _doc_with_file(db, store)
    job = _claimed_job(db, "index_document", {"document_id": doc.id}, doc.storage_key)
    embed = FakeEmbed()
    _run_index(db, job, embed)
    n = _n_chunks(db, doc.id)
    assert n > 0 and embed.calls == 1
    _run_index(db, job, embed)  # e.g. crash after commit, job re-claimed
    assert _n_chunks(db, doc.id) == n and embed.calls == 1
    states = {(e.effect, e.state) for e in _effects(db, job.id)}
    assert ("chunks", "applied") in states and ("provider:embeddings", EFFECT_SETTLED) in states
    assert je.charge_uncertain(db, job.id) is False


def test_index_crash_during_provider_call_records_uncertain_charge(db, store):
    doc = _doc_with_file(db, store)
    job = _claimed_job(db, "index_document", {"document_id": doc.id}, doc.storage_key)
    with pytest.raises(Crash):
        _run_index(db, job, FakeEmbed(fail=True))
    db.rollback()  # crash: the main transaction is gone, the started marker survived
    assert _n_chunks(db, doc.id) == 0
    assert [(e.effect, e.state) for e in _effects(db, job.id)] == [
        ("provider:embeddings", EFFECT_STARTED)
    ]
    # Next claim (attempt 2) reconciles the interrupted attempt.
    job.attempt = 2
    db.commit()
    assert je.reconcile_previous_attempts(db, job) == 1
    assert je.charge_uncertain(db, job.id) is True
    embed = FakeEmbed()
    _run_index(db, job, embed)
    assert _n_chunks(db, doc.id) > 0 and embed.calls == 1
    assert je.charge_uncertain(db, job.id) is True  # still recorded after a successful retry


def test_failure_path_marks_unsettled_provider_calls_uncertain(db, store):
    doc = _doc_with_file(db, store)
    job = _claimed_job(db, "index_document", {"document_id": doc.id}, doc.storage_key)
    with pytest.raises(Crash):
        _run_index(db, job, FakeEmbed(fail=True))
    db.rollback()
    assert je.mark_unsettled_uncertain(db, job) == 1
    db.commit()
    assert [e.state for e in _effects(db, job.id)] == [EFFECT_UNCERTAIN]


def test_index_second_job_same_version_reconciles_without_embedding(db, store):
    doc = _doc_with_file(db, store)
    _run_index(
        db,
        _claimed_job(db, "index_document", {"document_id": doc.id}, doc.storage_key),
        FakeEmbed(),
    )
    n = _n_chunks(db, doc.id)
    job2 = _claimed_job(db, "index_document", {"document_id": doc.id}, doc.storage_key)
    embed = FakeEmbed()
    _run_index(db, job2, embed)
    assert json.loads(job2.result)["outcome"] == "reconciled"
    assert embed.calls == 0 and _n_chunks(db, doc.id) == n


def test_concurrent_index_second_job_sees_applied_state_without_reembedding(db, store):
    """Second session already holds the document, so FOR UPDATE must refresh it.

    Without populate_existing the locked re-query returns the stale identity-map row.
    The second job then re-embeds (a second paid call) and can fail on the applied marker.
    """
    from app import worker

    doc = _doc_with_file(db, store)
    second = SessionLocal()
    try:
        stale = second.query(Document).filter(Document.id == doc.id).one()
        assert stale.status == "uploaded"

        first = _claimed_job(db, "index_document", {"document_id": doc.id}, doc.storage_key)
        first_embed = FakeEmbed()
        _run_index(db, first, first_embed)
        assert first_embed.calls == 1
        db.expire_all()
        assert db.query(Document).filter(Document.id == doc.id).one().status == "indexed"
        # The other session's identity map still has the pre-index row until it is refreshed.
        assert second.query(Document).filter(Document.id == doc.id).one() is stale
        assert stale.status == "uploaded"

        job2 = _claimed_job(db, "index_document", {"document_id": doc.id}, doc.storage_key)
        job2_in_second = second.query(Job).filter(Job.id == job2.id).one()
        embed = FakeEmbed()
        with (
            patch("app.services.index_service.embed_texts", embed),
            patch("app.services.tag_service.auto_tag_document", return_value=0),
        ):
            worker.run_index_document(job2_in_second, second, {"document_id": doc.id})
        second.commit()
        assert embed.calls == 0
        assert json.loads(job2_in_second.result)["outcome"] == "reconciled"
        assert _n_chunks(db, doc.id) > 0
    finally:
        second.rollback()
        second.close()


def test_index_stale_input_version_is_superseded(db, store):
    doc = _doc_with_file(db, store)
    job = _claimed_job(
        db, "index_document", {"document_id": doc.id}, input_version="raw/1/older-object.txt"
    )
    embed = FakeEmbed()
    _run_index(db, job, embed)
    assert json.loads(job.result) == {"outcome": "superseded", "reason": "input_version_changed"}
    assert embed.calls == 0 and _n_chunks(db, doc.id) == 0


# ---------------------------------------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------------------------------------


@pytest.fixture
def fake_ai(monkeypatch):
    """Fake embeddings + empty retrieval so every question is gated (no LLM call). Placeholder key only."""
    from app.core.config import get_settings

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-placeholder-not-a-real-key")
    get_settings.cache_clear()
    embed = FakeEmbed()

    def no_llm(*a, **kw):
        raise AssertionError("LLM must not be called in this test")

    with (
        patch("app.services.answer_generation.embed_texts", embed),
        patch(
            "app.services.answer_generation.RetrievalService.batch_search",
            lambda self, ws, queries, **kw: [[] for _ in queries],
        ),
        patch("app.services.answer_generation._completion_create_with_retry", no_llm),
        patch(
            "app.services.evidence_gap_service.generate_gaps_for_questionnaire",
            return_value={"generated": 0},
            create=True,
        ),
    ):
        yield embed
    get_settings.cache_clear()


def _qnr_with_answers(db):
    qnr = Questionnaire(workspace_id=WS, storage_key=None, filename="gen.xlsx", status="parsed")
    db.add(qnr)
    db.commit()
    tag = uuid.uuid4().hex
    qs = [
        Question(questionnaire_id=qnr.id, text=f"Synthetic question {i} {tag}?") for i in range(4)
    ]
    db.add_all(qs)
    db.commit()
    return qnr, qs


def _run_generate(db, job):
    from app import worker

    worker.run_generate_answers(job, db, json.loads(job.payload))


def test_generate_never_overwrites_approved_or_newer_answers(db, fake_ai):
    qnr, (q_approved, q_newer, q_old, q_new) = _qnr_with_answers(db)
    old = datetime.utcnow() - timedelta(hours=2)
    db.add_all(
        [
            Answer(
                question_id=q_approved.id,
                text="Human approved text",
                status="approved",
                created_at=old,
                updated_at=old,
            ),
            Answer(
                question_id=q_old.id,
                text="Old draft",
                status="draft",
                created_at=old,
                updated_at=old,
            ),
        ]
    )
    db.commit()
    job = Job(
        workspace_id=WS,
        kind="generate_answers",
        status="running",
        attempt=1,
        payload=json.dumps({"questionnaire_id": qnr.id, "workspace_id": WS}),
        created_at=datetime.utcnow() - timedelta(minutes=5),
    )
    db.add(job)
    db.commit()
    # A human edits an answer after the job was requested: the stale job must not overwrite it.
    db.add(Answer(question_id=q_newer.id, text="Human edit after request", status="draft"))
    db.commit()

    _run_generate(db, job)
    db.expire_all()
    by_q = {
        a.question_id: a
        for a in db.query(Answer).filter(
            Answer.question_id.in_([q.id for q in (q_approved, q_newer, q_old, q_new)])
        )
    }
    assert (
        by_q[q_approved.id].text == "Human approved text"
        and by_q[q_approved.id].status == "approved"
    )
    assert (
        by_q[q_newer.id].text == "Human edit after request" and by_q[q_newer.id].status == "draft"
    )
    assert by_q[q_old.id].status == "insufficient_evidence"  # unprotected work is regenerated
    assert by_q[q_new.id].status == "insufficient_evidence"
    stats = json.loads(job.result)["stats"]
    assert stats["skipped_protected"] == 2
    assert {(e.effect, e.state) for e in _effects(db, job.id)} >= {
        ("usage:ai_jobs", "applied"),
        ("provider:openai", EFFECT_SETTLED),
    }


def test_generate_rerun_is_idempotent_and_counts_usage_once(db, fake_ai):
    qnr, qs = _qnr_with_answers(db)
    job = Job(
        workspace_id=WS,
        kind="generate_answers",
        status="running",
        attempt=1,
        payload=json.dumps({"questionnaire_id": qnr.id, "workspace_id": WS}),
        created_at=datetime.utcnow() - timedelta(minutes=1),
    )
    db.add(job)
    db.commit()

    def usage():
        db.expire_all()
        return (
            db.query(func.coalesce(func.sum(WorkspaceUsage.count), 0))
            .filter(WorkspaceUsage.workspace_id == WS, WorkspaceUsage.resource_type == "ai_jobs")
            .scalar()
        )

    u0 = usage()
    _run_generate(db, job)
    _run_generate(db, job)  # re-run of the same job (crash after the work committed)
    db.expire_all()
    n = db.query(func.count(Answer.id)).filter(Answer.question_id.in_([q.id for q in qs])).scalar()
    assert n == len(qs)  # one answer per question, never duplicated
    assert usage() - u0 == 1


def test_upsert_guard_rechecks_answer_approved_mid_run(db):
    qnr, (q, *_rest) = _qnr_with_answers(db)
    a = Answer(
        question_id=q.id,
        text="draft",
        status="draft",
        created_at=datetime.utcnow() - timedelta(hours=1),
        updated_at=datetime.utcnow() - timedelta(hours=1),
    )
    db.add(a)
    db.commit()
    guard = AnswerWriteGuard(datetime.utcnow() - timedelta(minutes=30))
    assert guard.is_protected(a) is False
    # Another session approves it while the run is in flight.
    other = SessionLocal()
    try:
        other.query(Answer).filter(Answer.id == a.id).update({"status": "approved"})
        other.commit()
    finally:
        other.close()
    token = _WRITE_GUARD.set(guard)
    try:
        _upsert_answer(db, q.id, "regenerated", [], 0, "insufficient_evidence")
    finally:
        _WRITE_GUARD.reset(token)
    db.commit()
    db.expire_all()
    a2 = db.query(Answer).filter(Answer.id == a.id).one()
    assert a2.status == "approved" and a2.text == "draft"
    assert q.id in guard.protected_qids


# ---------------------------------------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------------------------------------


def _export_setup(db, store):
    qnr, key = _qnr_with_file(db, store)
    q = Question(
        questionnaire_id=qnr.id,
        text="Synthetic export question?",
        source_location=json.dumps({"sheet": "Sheet1", "row": 2, "col": 2}),
    )
    db.add(q)
    db.commit()
    db.add(Answer(question_id=q.id, text="Synthetic approved answer.", status="approved"))
    db.commit()
    payload = {"questionnaire_id": qnr.id, "workspace_id": WS, "format": "xlsx"}
    return qnr, _claimed_job(db, "export", payload)


def _export_usage(db) -> int:
    db.expire_all()
    return (
        db.query(func.coalesce(func.sum(WorkspaceUsage.count), 0))
        .filter(WorkspaceUsage.workspace_id == WS, WorkspaceUsage.resource_type == "exports")
        .scalar()
    )


def test_export_crash_after_upload_before_record_reuses_key(db, store):
    from app import worker

    qnr, job = _export_setup(db, store)
    u0 = _export_usage(db)
    with patch.object(
        je.JobEffects, "mark_applied", side_effect=Crash("after upload, before record commit")
    ):
        with pytest.raises(Crash):
            worker.run_export(job, db, json.loads(job.payload))
    db.rollback()
    assert db.query(ExportRecord).filter(ExportRecord.job_id == job.id).count() == 0
    worker.run_export(job, db, json.loads(job.payload))
    worker.run_export(
        job, db, json.loads(job.payload)
    )  # crash after commit: re-run reuses the record
    recs = db.query(ExportRecord).filter(ExportRecord.job_id == job.id).all()
    assert len(recs) == 1
    expected = f"exports/{WS}/job-{job.id}.xlsx"
    assert recs[0].storage_key == expected
    assert {k for _b, k in store.uploads} == {
        expected
    }  # re-upload overwrote the same object: no orphan
    assert json.loads(job.result)["outcome"] == "already_applied"
    assert _export_usage(db) - u0 == 1


def test_export_record_job_id_is_unique(db, store):
    from sqlalchemy.exc import IntegrityError

    qnr, job = _export_setup(db, store)
    for _ in range(2):
        db.add(
            ExportRecord(
                workspace_id=WS,
                questionnaire_id=qnr.id,
                storage_key=f"exports/{WS}/x-{uuid.uuid4().hex}",
                filename="x.xlsx",
                status="completed",
                job_id=job.id,
            )
        )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ---------------------------------------------------------------------------------------------------------
# Routes: scoped Idempotency-Key, no cached 403, release on 429, jobs API
# ---------------------------------------------------------------------------------------------------------


def _login(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert r.status_code == 200


def _route_qnr(db) -> Questionnaire:
    qnr = Questionnaire(
        workspace_id=WS,
        storage_key=f"raw/{WS}/{uuid.uuid4().hex}.xlsx",
        filename="r.xlsx",
        status="parsed",
    )
    db.add(qnr)
    db.commit()
    return qnr


def test_export_route_idempotency_key_scoped_and_released_on_429(client: TestClient, db):
    from app.core import idempotency

    _login(client)
    qnr = _route_qnr(db)
    k = f"client-key-{uuid.uuid4().hex}"
    # 403 is decided before the key is claimed, so nothing is cached for it.
    r = client.post(f"/api/exports/export/{qnr.id}?workspace_id=3", headers={"Idempotency-Key": k})
    assert r.status_code == 403
    assert (
        db.execute(
            idempotency.text("SELECT count(*) FROM idempotency_keys WHERE idempotency_key LIKE :p"),
            {"p": f"%{k}"},
        ).scalar()
        == 0
    )
    # 429 releases the claim, so the client's retry with the same key is not stuck at 409.
    with patch("app.services.quota_service.check_quota", return_value=(False, 5, 5)):
        r = client.post(
            f"/api/exports/export/{qnr.id}?workspace_id=1", headers={"Idempotency-Key": k}
        )
    assert r.status_code == 429
    r1 = client.post(f"/api/exports/export/{qnr.id}?workspace_id=1", headers={"Idempotency-Key": k})
    assert r1.status_code == 200
    r2 = client.post(f"/api/exports/export/{qnr.id}?workspace_id=1", headers={"Idempotency-Key": k})
    assert r2.status_code == 200 and r2.json()["job_id"] == r1.json()["job_id"]
    # Same client key on another questionnaire is a different request.
    qnr2 = _route_qnr(db)
    r3 = client.post(
        f"/api/exports/export/{qnr2.id}?workspace_id=1", headers={"Idempotency-Key": k}
    )
    assert r3.status_code == 200 and r3.json()["job_id"] != r1.json()["job_id"]
    stored = (
        db.execute(
            idempotency.text(
                "SELECT idempotency_key FROM idempotency_keys WHERE idempotency_key LIKE :p"
            ),
            {"p": f"%{k}"},
        )
        .scalars()
        .all()
    )
    assert all(s.startswith("ws:1:export:") for s in stored) and len(stored) == 2


def _idem_row(db, key: str):
    from app.core import idempotency

    return db.execute(
        idempotency.text(
            "SELECT response_body, expires_at FROM idempotency_keys WHERE idempotency_key = :k"
        ),
        {"k": key},
    ).one()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def test_expired_idempotency_claim_can_be_reclaimed(db):
    from app.core import idempotency

    key = f"reclaim-{uuid.uuid4().hex}"
    assert idempotency.try_claim(db, key) is True
    row = _idem_row(db, key)
    assert row.response_body is None
    # In progress: a short lease, not the 24h completion TTL.
    assert _as_utc(row.expires_at) < datetime.now(timezone.utc) + timedelta(minutes=10)
    db.execute(
        idempotency.text("UPDATE idempotency_keys SET expires_at = :t WHERE idempotency_key = :k"),
        {"t": datetime.now(timezone.utc) - timedelta(seconds=5), "k": key},
    )
    db.commit()
    assert idempotency.try_claim(db, key) is True
    reclaimed = _idem_row(db, key)
    assert reclaimed.response_body is None
    assert _as_utc(reclaimed.expires_at) > datetime.now(timezone.utc)
    idempotency.set(db, key, 200, {"ok": True})
    stored = _idem_row(db, key)
    assert json.loads(stored.response_body) == {"ok": True}
    assert _as_utc(stored.expires_at) > datetime.now(timezone.utc) + timedelta(hours=1)


def test_unexpired_in_progress_idempotency_claim_returns_409(client: TestClient, db):
    from app.core import idempotency

    _login(client)
    qnr = _route_qnr(db)
    k = f"busy-{uuid.uuid4().hex}"
    scoped = idempotency.scoped_key(WS, "export", qnr.id, k)
    assert idempotency.try_claim(db, scoped) is True
    assert idempotency.try_claim(db, scoped) is False
    r = client.post(f"/api/exports/export/{qnr.id}?workspace_id=1", headers={"Idempotency-Key": k})
    assert r.status_code == 409
    assert "in progress" in r.json()["detail"].lower()


def test_cleanup_expired_idempotency_keys_deletes_only_expired_rows(db):
    from app.core import idempotency

    fresh = f"fresh-{uuid.uuid4().hex}"
    expired = f"expired-{uuid.uuid4().hex}"
    assert idempotency.try_claim(db, fresh) is True
    assert idempotency.try_claim(db, expired) is True
    db.execute(
        idempotency.text("UPDATE idempotency_keys SET expires_at = :t WHERE idempotency_key = :k"),
        {"t": datetime.now(timezone.utc) - timedelta(hours=1), "k": expired},
    )
    db.commit()
    deleted = idempotency.cleanup_expired(db)
    assert deleted >= 1
    left = (
        db.execute(
            idempotency.text(
                "SELECT idempotency_key FROM idempotency_keys "
                "WHERE idempotency_key IN (:fresh, :expired)"
            ),
            {"fresh": fresh, "expired": expired},
        )
        .scalars()
        .all()
    )
    assert fresh in left and expired not in left


@pytest.mark.parametrize(
    "bad_key",
    ["", "   ", "has space", "bad/key", "a" * 256, "a" * 255],
)
def test_idempotency_key_rejects_empty_oversized_and_bad_characters(
    client: TestClient, db, bad_key: str
):
    from app.core import idempotency

    _login(client)
    qnr = _route_qnr(db)
    before = db.execute(idempotency.text("SELECT count(*) FROM idempotency_keys")).scalar()
    r = client.post(
        f"/api/exports/export/{qnr.id}?workspace_id=1",
        headers={"Idempotency-Key": bad_key},
    )
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == "invalid_idempotency_key"
    assert body["detail"] == body["error"]["message"]
    assert body["error"]["field_errors"][0]["field"] == "Idempotency-Key"
    after = db.execute(idempotency.text("SELECT count(*) FROM idempotency_keys")).scalar()
    assert after == before


def test_idempotency_key_accepts_token_characters(client: TestClient, db):
    _login(client)
    qnr = _route_qnr(db)
    r = client.post(
        f"/api/exports/export/{qnr.id}?workspace_id=1",
        headers={"Idempotency-Key": "Ok.key_1:part-9"},
    )
    assert r.status_code == 200


def test_export_route_without_key_reuses_identical_queued_job(client: TestClient, db):
    _login(client)
    qnr = _route_qnr(db)
    r1 = client.post(f"/api/exports/export/{qnr.id}?workspace_id=1")
    r2 = client.post(f"/api/exports/export/{qnr.id}?workspace_id=1")
    r3 = client.post(f"/api/exports/export/{qnr.id}?workspace_id=1", json={"format": "docx"})
    assert r1.json()["job_id"] == r2.json()["job_id"] != r3.json()["job_id"]


def _idem_count(db, client_key: str) -> int:
    from app.core import idempotency

    return db.execute(
        idempotency.text("SELECT count(*) FROM idempotency_keys WHERE idempotency_key LIKE :p"),
        {"p": f"%:{client_key}"},
    ).scalar()


@pytest.fixture
def reset_workspace_ai_jobs(db):
    """Zero workspace 1's current-hour ``ai_jobs`` count, then put the saved count back.

    Earlier tests in this module can spend the hourly limit of 10. This test expects 400,
    and a full counter turns that request into 429. The quota service is not changed.
    """
    from app.services.quota_service import _current_window_start

    window = _current_window_start()
    rows = (
        db.query(WorkspaceUsage)
        .filter(
            WorkspaceUsage.workspace_id == WS,
            WorkspaceUsage.resource_type == "ai_jobs",
            WorkspaceUsage.window_start == window,
        )
        .all()
    )
    saved = [(row.id, int(row.count)) for row in rows]
    for row in rows:
        row.count = 0
    if saved:
        db.commit()
    try:
        yield
    finally:
        db.rollback()
        db.expire_all()
        for row_id, count in saved:
            row = db.get(WorkspaceUsage, row_id)
            if row is None:
                continue
            row.count = count
        if saved:
            db.commit()


def test_replay_returns_same_error_body_as_live_response(
    client: TestClient, db, reset_workspace_ai_jobs
):
    """TC-10-003a (b): an idempotent replay of a 4xx returns exactly the live status and body."""
    _login(client)
    qnr = _route_qnr(db)
    # 400 from validation (generate with an unsupported model). No questions, so no API key is needed.
    k400 = f"err400-{uuid.uuid4().hex}"
    url = f"/api/exports/generate/{qnr.id}?workspace_id=1"
    live = client.post(url, json={"model": "not-a-model"}, headers={"Idempotency-Key": k400})
    replay = client.post(url, json={"model": "not-a-model"}, headers={"Idempotency-Key": k400})
    assert live.status_code == 400
    assert (replay.status_code, replay.json()) == (live.status_code, live.json())
    # 404 whose underlying message differs from the public text: the replay must not leak the internal
    # message; it repeats the live "Questionnaire not found".
    k404 = f"err404-{uuid.uuid4().hex}"
    url = f"/api/exports/export/{qnr.id}?workspace_id=1"
    with patch(
        "app.api.routes.exports.enqueue_export_job",
        side_effect=ValueError("Synthetic template not found for format"),
    ):
        live = client.post(url, headers={"Idempotency-Key": k404})
    replay = client.post(url, headers={"Idempotency-Key": k404})
    assert live.status_code == 404 and live.json() == {"detail": "Questionnaire not found"}
    assert (replay.status_code, replay.json()) == (live.status_code, live.json())
    # Real missing questionnaire: same on replay too.
    k404b = f"err404b-{uuid.uuid4().hex}"
    url = "/api/exports/export/987654321?workspace_id=1"
    live = client.post(url, headers={"Idempotency-Key": k404b})
    replay = client.post(url, headers={"Idempotency-Key": k404b})
    assert live.status_code == 404
    assert (replay.status_code, replay.json()) == (live.status_code, live.json())


def test_5xx_response_is_not_cached_and_frees_the_claim(client: TestClient, db):
    """TC-10-003a (c): a 503 is not replayed; the claim is released so the same key can retry."""
    from types import SimpleNamespace

    _login(client)
    qnr, _qs = _qnr_with_answers(db)
    k = f"err503-{uuid.uuid4().hex}"
    url = f"/api/exports/generate/{qnr.id}?workspace_id=1"
    with patch(
        "app.api.routes.exports.get_settings",
        return_value=SimpleNamespace(openai_api_key=""),
    ):
        r1 = client.post(url, headers={"Idempotency-Key": k})
    assert r1.status_code == 503
    assert _idem_count(db, k) == 0
    # Same key after the server is fixed: runs for real instead of replaying the 503.
    with (
        patch(
            "app.api.routes.exports.get_settings",
            return_value=SimpleNamespace(openai_api_key="sk-fake-not-used"),
        ),
        patch("app.services.quota_service.check_quota", return_value=(True, 0, 100)),
    ):
        r2 = client.post(url, headers={"Idempotency-Key": k})
        r3 = client.post(url, headers={"Idempotency-Key": k})
    assert r2.status_code == 200 and r2.json()["status"] == "queued"
    assert (r3.status_code, r3.json()) == (200, r2.json())


def test_idempotency_set_never_stores_5xx(db):
    """TC-10-003a (c): defense in depth at the store layer for any 5xx."""
    from app.core import idempotency

    key = f"set5xx-{uuid.uuid4().hex}"
    assert idempotency.try_claim(db, key) is True
    idempotency.set(db, key, 502, {"detail": "Synthetic upstream failure"})
    assert idempotency.get(db, key) is None
    assert (
        db.execute(
            idempotency.text("SELECT count(*) FROM idempotency_keys WHERE idempotency_key = :k"),
            {"k": key},
        ).scalar()
        == 0
    )
    # The freed key can be claimed again immediately (no 409 for the lease).
    assert idempotency.try_claim(db, key) is True
    idempotency.set(db, key, 422, {"detail": "Synthetic validation"})
    assert idempotency.get(db, key) == (422, {"detail": "Synthetic validation"})


def test_jobs_api_reports_charge_uncertain(client: TestClient, db):
    _login(client)
    job = _claimed_job(db, "generate_answers", {"questionnaire_id": 0, "workspace_id": WS})
    db.add(
        JobEffect(
            job_id=job.id,
            workspace_id=WS,
            effect="provider:openai",
            attempt=1,
            state=EFFECT_UNCERTAIN,
        )
    )
    db.commit()
    r = client.get(f"/api/jobs/{job.id}?workspace_id=1")
    assert r.status_code == 200 and r.json()["charge_uncertain"] is True


def test_upload_routes_set_input_version(client: TestClient, db):
    _login(client)
    with patch("app.services.storage.StorageClient.upload", lambda self, b, k, body, **kw: k):
        r = client.post(
            "/api/documents/upload",
            data={"workspace_id": "1"},
            files={
                "file": ("synthetic.txt", b"Synthetic evidence text for TC-10-003.", "text/plain")
            },
        )
    assert r.status_code == 200, r.text
    job = db.query(Job).filter(Job.id == r.json()["job_id"]).one()
    assert job.input_version == r.json()["storage_key"] and job.idempotency_key


# ---------------------------------------------------------------------------------------------------------
# Migration rollback
# ---------------------------------------------------------------------------------------------------------


def test_migration_downgrade_and_upgrade_roundtrip(_ensure_test_data):
    if not _ensure_test_data:
        pytest.skip("Postgres test DB unavailable")
    import importlib.util

    api_dir = Path(__file__).resolve().parents[2]
    mig = api_dir / "alembic" / "versions" / "077_tc10003_job_idempotency.py"
    spec = importlib.util.spec_from_file_location("tc10003_mig", mig)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    env = {**os.environ, "DATABASE_URL": os.environ["DATABASE_URL"]}

    def alembic(*args):
        r = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=api_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, r.stderr[-2000:]

    def cols(table):
        engine.dispose()
        return {c["name"] for c in inspect(engine).get_columns(table)}

    alembic("downgrade", mod.down_revision)
    try:
        assert "job_effects" not in inspect(engine).get_table_names()
        assert {"idempotency_key", "input_version"}.isdisjoint(cols("jobs"))
        assert "job_id" not in cols("export_records")
    finally:
        alembic("upgrade", "head")
    assert "job_effects" in inspect(engine).get_table_names()
    assert {"idempotency_key", "input_version"} <= cols("jobs")
    assert "job_id" in cols("export_records")


# ---------------------------------------------------------------------------------------------------------
# TC-10-003b: retryable enqueue conflict (a) and owner-token fencing of idempotency claims (b)
# ---------------------------------------------------------------------------------------------------------


def _owner_of(db, key: str):
    from app.core import idempotency

    return db.execute(
        idempotency.text("SELECT owner_token FROM idempotency_keys WHERE idempotency_key = :k"),
        {"k": key},
    ).scalar()


def _expire_claim(db, key: str) -> None:
    from app.core import idempotency

    db.execute(
        idempotency.text("UPDATE idempotency_keys SET expires_at = :t WHERE idempotency_key = :k"),
        {"t": datetime.now(timezone.utc) - timedelta(seconds=5), "k": key},
    )
    db.commit()


def test_enqueue_job_raises_typed_conflict_when_retry_also_loses(db):
    """(a) unit: both inserts hit the unique QUEUED slot and the winner is never visible."""
    key = je.job_idempotency_key("export", WS, "tc10003b-unit", uuid.uuid4().hex)
    winner, created = je.enqueue_job(
        db, workspace_id=WS, kind="export", payload={"synthetic": 1}, idempotency_key=key
    )
    assert created
    with patch.object(je, "_queued_with_key", return_value=None):
        with pytest.raises(je.EnqueueConflictError) as exc_info:
            je.enqueue_job(
                db, workspace_id=WS, kind="export", payload={"synthetic": 2}, idempotency_key=key
            )
    from sqlalchemy.exc import IntegrityError

    assert isinstance(exc_info.value.__cause__, IntegrityError)
    # The session is left usable and no second QUEUED row exists.
    assert (
        db.query(func.count(Job.id))
        .filter(Job.workspace_id == WS, Job.kind == "export", Job.idempotency_key == key)
        .scalar()
        == 1
    )
    assert db.query(Job).filter(Job.id == winner.id).one().status == JobStatus.QUEUED.value


@pytest.mark.parametrize("route", ["export", "generate"])
def test_enqueue_conflict_after_retry_is_retryable_409_not_500(client: TestClient, db, route: str):
    """(a) regression: on master the escaping IntegrityError is a 500 (TestClient re-raises it)."""
    _login(client)
    qnr = _route_qnr(db)
    url = f"/api/exports/{route}/{qnr.id}?workspace_id=1"
    k = f"conflict-{route}-{uuid.uuid4().hex}"
    with patch("app.services.quota_service.check_quota", return_value=(True, 0, 100)):
        # An identical QUEUED job holds the unique slot ...
        first = client.post(url)
        assert first.status_code == 200, first.text
        jobs_before = db.query(func.count(Job.id)).scalar()
        # ... and the race-winner lookup never sees it, so both enqueue attempts raise IntegrityError.
        with patch.object(je, "_queued_with_key", return_value=None):
            r = client.post(url, headers={"Idempotency-Key": k})
        assert r.status_code == 409, r.text
        body = r.json()
        assert body["error"]["code"] == "idempotency_conflict"
        assert body["error"]["retryable"] is True
        assert body["detail"] == body["error"]["message"]
        assert body["error"]["request_id"] == r.headers["X-Request-ID"]
        assert r.headers["Retry-After"] == "1"
        assert "IntegrityError" not in r.text and "uq_jobs" not in r.text
        # Same envelope as the shared 400 idempotency error.
        bad = client.post(url, headers={"Idempotency-Key": "has space"})
        assert set(body) == set(bad.json()) == {"detail", "error"}
        assert set(body["error"]) <= set(bad.json()["error"])
        # Not cached and the claim was released: the retry with the same key runs and reuses the queued job.
        assert _idem_count(db, k) == 0
        db.expire_all()
        assert db.query(func.count(Job.id)).scalar() == jobs_before
        retry = client.post(url, headers={"Idempotency-Key": k})
    assert retry.status_code == 200 and retry.json()["job_id"] == first.json()["job_id"]


def test_claim_records_owner_token_and_rightful_owner_set_release_work(db):
    """(b) the claiming request's own token stores and releases normally."""
    from app.core import idempotency

    key = f"owner-ok-{uuid.uuid4().hex}"
    owner = idempotency.claim(db, key)
    assert owner and _owner_of(db, key) == owner
    assert idempotency.claim(db, key) is None  # unexpired: not claimable
    assert idempotency.release(db, key, owner=owner) is True
    assert _owner_of(db, key) is None and idempotency.get(db, key) is None
    owner2 = idempotency.claim(db, key)
    assert owner2 and owner2 != owner
    assert idempotency.set(db, key, 200, {"job_id": 1}, owner=owner2) is True
    assert idempotency.get(db, key) == (200, {"job_id": 1})


def test_stale_owner_release_and_set_are_noops_after_reclaim(db):
    """(b) a late finisher whose lease expired cannot free or overwrite the new owner's claim."""
    from app.core import idempotency

    key = f"owner-stale-{uuid.uuid4().hex}"
    stale = idempotency.claim(db, key)
    _expire_claim(db, key)
    fresh = idempotency.claim(db, key)  # ON CONFLICT DO UPDATE reclaim
    assert stale and fresh and stale != fresh
    assert _owner_of(db, key) == fresh

    assert idempotency.release(db, key, owner=stale) is False
    assert _owner_of(db, key) == fresh
    assert idempotency.set(db, key, 200, {"job_id": "stale"}, owner=stale) is False
    assert idempotency.get(db, key) is None  # still in progress for the new owner
    # A stale 5xx goes through release(): also fenced.
    assert idempotency.set(db, key, 503, {"detail": "Synthetic"}, owner=stale) is False
    assert _owner_of(db, key) == fresh

    assert idempotency.set(db, key, 200, {"job_id": "fresh"}, owner=fresh) is True
    assert idempotency.get(db, key) == (200, {"job_id": "fresh"})
    # After completion the stale owner still cannot overwrite it.
    assert idempotency.set(db, key, 400, {"detail": "stale"}, owner=stale) is False
    assert idempotency.get(db, key) == (200, {"job_id": "fresh"})


def test_legacy_owner_none_callers_keep_unconditional_behavior(db):
    """(b) try_claim + set/release without owner still behave as before TC-10-003b."""
    from app.core import idempotency

    key = f"owner-legacy-{uuid.uuid4().hex}"
    assert idempotency.try_claim(db, key) is True
    assert _owner_of(db, key)  # a token is still recorded
    assert idempotency.set(db, key, 200, {"ok": True}) is True
    assert idempotency.get(db, key) == (200, {"ok": True})


def test_route_late_finisher_does_not_overwrite_reclaimed_key(client: TestClient, db):
    """(b) route level: request A's lease expires mid-flight and B reclaims; A's set() must not land."""
    from app.core import idempotency
    from app.services import export_service

    _login(client)
    qnr = _route_qnr(db)
    k = f"late-{uuid.uuid4().hex}"
    scoped = idempotency.scoped_key(WS, "export", qnr.id, k)
    holder: dict[str, str | None] = {}
    real_enqueue = export_service.enqueue_export_job

    def slow_enqueue(*args, **kwargs):
        side = SessionLocal()
        try:
            _expire_claim(side, scoped)
            holder["b"] = idempotency.claim(side, scoped)
        finally:
            side.close()
        return real_enqueue(*args, **kwargs)

    with (
        patch("app.services.quota_service.check_quota", return_value=(True, 0, 100)),
        patch("app.api.routes.exports.enqueue_export_job", side_effect=slow_enqueue),
    ):
        r = client.post(
            f"/api/exports/export/{qnr.id}?workspace_id=1", headers={"Idempotency-Key": k}
        )
    assert r.status_code == 200
    assert holder["b"]
    db.expire_all()
    assert _owner_of(db, scoped) == holder["b"]
    assert idempotency.get(db, scoped) is None  # B's claim is intact and still in progress
    assert idempotency.set(db, scoped, 200, {"job_id": "b"}, owner=holder["b"]) is True


def test_concurrent_reclaim_has_single_owner_and_losers_are_fenced(_ensure_test_data):
    """(b) concurrency: many sessions race to reclaim one expired key; exactly one wins and nobody else
    (including the original, expired owner) can release or overwrite the winner's claim."""
    import threading

    if not _ensure_test_data:
        pytest.skip("Postgres test DB unavailable")
    from app.core import idempotency

    key = f"race-{uuid.uuid4().hex}"
    setup = SessionLocal()
    try:
        original = idempotency.claim(setup, key)
        assert original
        _expire_claim(setup, key)
    finally:
        setup.close()

    n = 12
    barrier = threading.Barrier(n)
    results: list[str | None] = [None] * n
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        s = SessionLocal()
        try:
            barrier.wait(timeout=10)
            results[i] = idempotency.claim(s, key)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)
        finally:
            s.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors
    winners = [t for t in results if t]
    assert len(winners) == 1
    winner = winners[0]

    # The stale original owner and the winner finish concurrently; only the winner's write lands.
    outcomes: dict[str, bool] = {}

    def finish(name: str, owner: str, body: dict) -> None:
        s = SessionLocal()
        try:
            outcomes[name] = idempotency.set(s, key, 200, body, owner=owner)
        finally:
            s.close()

    ts = [
        threading.Thread(target=finish, args=("stale", original, {"by": "stale"})),
        threading.Thread(target=finish, args=("winner", winner, {"by": "winner"})),
    ]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=30)
    assert outcomes == {"stale": False, "winner": True}
    check = SessionLocal()
    try:
        assert idempotency.get(check, key) == (200, {"by": "winner"})
        check.execute(
            idempotency.text("DELETE FROM idempotency_keys WHERE idempotency_key = :k"), {"k": key}
        )
        check.commit()
    finally:
        check.close()


def test_owner_token_migration_downgrade_and_upgrade_roundtrip(_ensure_test_data):
    if not _ensure_test_data:
        pytest.skip("Postgres test DB unavailable")
    import importlib.util

    api_dir = Path(__file__).resolve().parents[2]
    mig = api_dir / "alembic" / "versions" / "tc10003b_idempotency_owner_token.py"
    spec = importlib.util.spec_from_file_location("tc10003b_mig", mig)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    env = {**os.environ, "DATABASE_URL": os.environ["DATABASE_URL"]}

    def alembic(*args):
        r = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=api_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, r.stderr[-2000:]

    def cols():
        engine.dispose()
        return {c["name"] for c in inspect(engine).get_columns("idempotency_keys")}

    alembic("downgrade", mod.down_revision)
    try:
        assert "owner_token" not in cols()
    finally:
        alembic("upgrade", "head")
    assert "owner_token" in cols()
