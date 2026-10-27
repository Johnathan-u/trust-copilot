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
from datetime import datetime, timedelta
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
FIXTURE_XLSX = Path(__file__).parent / "fixtures" / "questionnaires" / "simple_soc2.xlsx"


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

    def __call__(self, texts):
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


def test_export_route_without_key_reuses_identical_queued_job(client: TestClient, db):
    _login(client)
    qnr = _route_qnr(db)
    r1 = client.post(f"/api/exports/export/{qnr.id}?workspace_id=1")
    r2 = client.post(f"/api/exports/export/{qnr.id}?workspace_id=1")
    r3 = client.post(f"/api/exports/export/{qnr.id}?workspace_id=1", json={"format": "docx"})
    assert r1.json()["job_id"] == r2.json()["job_id"] != r3.json()["job_id"]


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

    api_dir = Path(__file__).resolve().parents[1]
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
