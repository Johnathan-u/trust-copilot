"""TC-10-002: classify job errors and apply bounded retries.

Synthetic data and in-process fakes only: provider/storage errors are fake exception classes that mimic the
shape of openai / httpx / botocore errors (status code, response headers, class name). No model, provider or
network call is made; the object store is an in-memory dict.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError

from app.core import job_errors as je

from app.core.database import SessionLocal, engine
from app.models import Answer, Document, Job, JobStatus, Question, Questionnaire
from app.models.audit_event import AuditEvent
from app.services.answer_generation import AnswerWriteGuard

WS = 1


# ---------------------------------------------------------------------------------------------------------
# Fake provider / storage errors (shape-compatible, no SDK call)
# ---------------------------------------------------------------------------------------------------------


class _Resp:
    def __init__(self, status: int, headers: dict | None = None):
        self.status_code = status
        self.headers = headers or {}


class APIStatusError(Exception):
    """Mimics openai.APIStatusError: ``status_code`` + ``response`` with headers; str() echoes the body."""

    def __init__(self, status: int, body: str = "", headers: dict | None = None):
        super().__init__(f"Error code: {status} - {body}")
        self.status_code = status
        self.response = _Resp(status, headers)


class RateLimitError(APIStatusError):
    def __init__(self, headers: dict | None = None):
        super().__init__(429, "{'error': 'synthetic rate limit body'}", headers)


class AuthenticationError(APIStatusError):
    def __init__(self):
        super().__init__(401, "{'error': 'synthetic invalid key body sk-SYNTHETIC'}")


class APIConnectionError(Exception):
    pass


class APITimeoutError(APIConnectionError):
    pass


class ClientError(Exception):
    """Mimics botocore.exceptions.ClientError (dict ``response``)."""

    def __init__(self, code: str, status: int):
        super().__init__(f"An error occurred ({code})")
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}


class EndpointConnectionError(Exception):
    pass


# ---------------------------------------------------------------------------------------------------------
# Classification (AC1)
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc, code, retryable",
    [
        (RateLimitError(), je.RATE_LIMITED, True),
        (APIStatusError(429), je.RATE_LIMITED, True),
        (APITimeoutError("synthetic"), je.TIMEOUT, True),
        (TimeoutError("synthetic"), je.TIMEOUT, True),
        (APIStatusError(408), je.TIMEOUT, True),
        (APIStatusError(504), je.TIMEOUT, True),
        (APIStatusError(500), je.UPSTREAM_UNAVAILABLE, True),
        (APIStatusError(502), je.UPSTREAM_UNAVAILABLE, True),
        (APIStatusError(503), je.UPSTREAM_UNAVAILABLE, True),
        (APIConnectionError("synthetic"), je.CONNECTION_ERROR, True),
        (ConnectionResetError("synthetic"), je.CONNECTION_ERROR, True),
        (EndpointConnectionError("synthetic"), je.CONNECTION_ERROR, True),
        (ClientError("SlowDown", 503), je.RATE_LIMITED, True),
        (ClientError("InternalError", 500), je.UPSTREAM_UNAVAILABLE, True),
        (OperationalError("SELECT 1", {}, Exception("synthetic")), je.DATABASE_UNAVAILABLE, True),
        (HTTPException(status_code=503, detail="x"), je.UPSTREAM_UNAVAILABLE, True),
        (HTTPException(status_code=429, detail="x"), je.RATE_LIMITED, True),
        # terminal
        (APIStatusError(400), je.BAD_INPUT, False),
        (APIStatusError(422), je.BAD_INPUT, False),
        (AuthenticationError(), je.AUTH_FAILED, False),
        (APIStatusError(403), je.PERMISSION_DENIED, False),
        (APIStatusError(404), je.NOT_FOUND, False),
        (ClientError("NoSuchKey", 404), je.NOT_FOUND, False),
        (ClientError("AccessDenied", 403), je.PERMISSION_DENIED, False),
        (ClientError("InvalidAccessKeyId", 403), je.AUTH_FAILED, False),
        (HTTPException(status_code=400, detail="bad file"), je.BAD_INPUT, False),
        (HTTPException(status_code=413, detail="too big"), je.BAD_INPUT, False),
        (ValueError("Questionnaire 1 not found"), je.BAD_INPUT, False),
        (KeyError("questionnaire_id"), je.BAD_INPUT, False),
        (je.JobConfigError("OPENAI_API_KEY is not set"), je.CONFIG_ERROR, False),
        (RuntimeError("unexplained"), je.INTERNAL_ERROR, False),
        (Exception("unexplained"), je.INTERNAL_ERROR, False),
    ],
)
def test_classifier_table(exc, code, retryable):
    assert je.classify(exc) == code
    assert je.is_retryable_code(code) is retryable


def test_typed_errors_keep_their_code_and_value_error_compat():
    err = je.JobConfigError("missing key")
    assert isinstance(err, ValueError) and not err.retryable and err.code == je.CONFIG_ERROR
    assert je.RetryableJobError(je.TIMEOUT).retryable
    with pytest.raises(ValueError):
        je.RetryableJobError(je.BAD_INPUT)
    with pytest.raises(ValueError):
        je.TerminalJobError(je.RATE_LIMITED)
    wrapped = je.job_error_from(RateLimitError({"retry-after": "7"}))
    assert isinstance(wrapped, je.RetryableJobError) and wrapped.retry_after == 7.0


def test_safe_error_message_never_contains_provider_body():
    for exc in (
        RateLimitError(),
        AuthenticationError(),
        APIStatusError(503, "secret upstream body"),
    ):
        msg = je.safe_error_message(exc)
        assert "body" not in msg and "sk-SYNTHETIC" not in msg
        assert str(exc.status_code) in msg
    assert je.safe_error_message(ValueError("Missing document_id")) == "Missing document_id"


def test_retry_after_parsing():
    assert je.retry_after_seconds(RateLimitError({"retry-after": "12"})) == 12.0
    assert je.retry_after_seconds(RateLimitError({"Retry-After": "nope"})) is None
    assert je.retry_after_seconds(ValueError("x")) is None


# ---------------------------------------------------------------------------------------------------------
# Backoff: bounded, exponential, jittered (AC1)
# ---------------------------------------------------------------------------------------------------------


def test_backoff_is_bounded_exponential_with_jitter():
    rng = random.Random(1234)
    for attempt in range(1, 30):
        d = min(600.0, 15.0 * 2 ** (attempt - 1))
        for _ in range(50):
            delay = je.backoff_delay(attempt, base=15.0, cap=600.0, rng=rng)
            assert d / 2 <= delay <= d <= 600.0
    samples = {round(je.backoff_delay(3, base=15.0, cap=600.0, rng=rng), 6) for _ in range(20)}
    assert len(samples) > 1  # jitter: concurrent failures do not retry in lockstep


def test_backoff_honours_retry_after_but_clamps_to_cap():
    rng = random.Random(7)
    assert je.backoff_delay(1, base=1.0, cap=60.0, retry_after=30.0, rng=rng) == 30.0
    assert je.backoff_delay(1, base=1.0, cap=60.0, retry_after=10_000.0, rng=rng) == 60.0
    assert je.backoff_delay(1, base=0.0, cap=0.0, rng=rng) == 0.0


def test_attempt_ceiling_and_env_config(monkeypatch):
    assert je.effective_max_attempts(None) == 3
    assert je.effective_max_attempts(0) == 1
    assert je.effective_max_attempts(1000) == je.MAX_ATTEMPTS_CEILING
    monkeypatch.setenv("JOB_RETRY_BASE_SECONDS", "2")
    monkeypatch.setenv("JOB_RETRY_MAX_SECONDS", "not-a-number")
    assert je.retry_base_seconds() == 2.0
    assert je.retry_max_seconds() == je.DEFAULT_RETRY_MAX_SECONDS
    monkeypatch.setenv("JOB_RETRY_MAX_SECONDS", "-5")
    assert je.retry_max_seconds() == 0.0


def test_inner_completion_retry_uses_jittered_bounded_backoff(monkeypatch):
    from app.services import answer_generation as ag

    sleeps: list[float] = []
    monkeypatch.setattr(ag.time, "sleep", lambda s: sleeps.append(s))
    calls = {"n": 0}

    class Completions:
        def create(self, **kw):
            calls["n"] += 1
            raise RateLimitError({"retry-after": "500"})

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    with pytest.raises(RateLimitError):
        ag._completion_create_with_retry(client, model="synthetic")
    assert calls["n"] == ag.COMPLETION_MAX_RETRIES + 1
    assert len(sleeps) == ag.COMPLETION_MAX_RETRIES
    assert all(0 <= s <= ag.COMPLETION_RETRY_MAX_SECONDS for s in sleeps)  # Retry-After clamped
    # Terminal errors are not retried in-call either.
    calls["n"] = 0
    Completions.create = lambda self, **kw: (_ for _ in ()).throw(AuthenticationError())
    with pytest.raises(AuthenticationError):
        ag._completion_create_with_retry(client, model="synthetic")


def test_embed_texts_records_last_error_for_classification(monkeypatch):
    from app.services import embedding_service as es

    class FailingEmbeddings:
        def create(self, **kw):
            raise APIStatusError(503, "synthetic body")

    monkeypatch.setattr(es.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        es, "_get_embed_client", lambda key: SimpleNamespace(embeddings=FailingEmbeddings())
    )
    monkeypatch.setattr(
        es, "get_settings", lambda: SimpleNamespace(openai_api_key="sk-test-placeholder")
    )
    es.reset_last_embed_error()
    assert es.embed_texts(["synthetic text"]) == [None]
    assert je.classify(es.last_embed_error()) == je.UPSTREAM_UNAVAILABLE


# ---------------------------------------------------------------------------------------------------------
# Worker failure path (DB)
# ---------------------------------------------------------------------------------------------------------


@pytest.fixture
def db(_ensure_test_data):
    if not _ensure_test_data:
        pytest.skip("Postgres test DB unavailable")
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture
def fast_backoff(monkeypatch):
    monkeypatch.setenv("JOB_RETRY_BASE_SECONDS", "20")
    monkeypatch.setenv("JOB_RETRY_MAX_SECONDS", "60")


def _running_job(db, kind="export", attempt=1, max_attempts=3, payload=None, key=None) -> Job:
    job = Job(
        workspace_id=WS,
        kind=kind,
        status=JobStatus.RUNNING.value,
        payload=json.dumps(payload or {"questionnaire_id": 0, "workspace_id": WS}),
        attempt=attempt,
        max_attempts=max_attempts,
        idempotency_key=key,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _fail(db, job, exc):
    from app import worker

    worker._handle_job_failure(db, job, json.loads(job.payload), exc, 1.0)
    db.expire_all()
    return db.get(Job, job.id)


def _audits(db, job_id, action):
    return (
        db.query(AuditEvent)
        .filter(
            AuditEvent.resource_type == "job",
            AuditEvent.resource_id == str(job_id),
            AuditEvent.action == action,
        )
        .all()
    )


def _claimable(db, job_id, now=None) -> bool:
    from app import worker

    return (
        db.query(Job.id).filter(worker.claimable_filter(now), Job.id == job_id).first() is not None
    )


def test_transient_failure_schedules_bounded_retry_and_is_not_claimable_early(db, fast_backoff):
    job = _running_job(db)
    before = datetime.utcnow()
    job = _fail(db, job, RateLimitError())
    assert job.status == JobStatus.QUEUED.value and job.status != JobStatus.COMPLETED.value
    assert job.error_code == je.RATE_LIMITED and job.completed_at is None
    assert job.next_attempt_at is not None
    delay = (job.next_attempt_at - before).total_seconds()
    assert 10 - 1 <= delay <= 20 + 1  # attempt 1: jitter in [base/2, base]
    assert "Attempt 1 of 3 failed (rate_limited)" in job.error and "Next attempt" in job.error
    assert "synthetic rate limit body" not in job.error  # raw provider body never stored
    # Not claimable until the backoff elapses; claimable afterwards.
    assert not _claimable(db, job.id)
    assert _claimable(db, job.id, now=job.next_attempt_at + timedelta(seconds=1))
    (audit,) = _audits(db, job.id, "job.retry_scheduled")
    details = json.loads(audit.details) if isinstance(audit.details, str) else audit.details
    assert details["error_code"] == je.RATE_LIMITED and details["attempt"] == 1
    assert details["max_attempts"] == 3 and details["next_attempt_at"]
    assert not _audits(db, job.id, "job.failed")


def test_claim_increments_attempt_and_clears_schedule(db, fast_backoff):
    from app import worker

    job = _running_job(db)
    job = _fail(db, job, APIStatusError(503))
    job.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    real_filter = worker.claimable_filter
    with patch.object(
        worker, "claimable_filter", lambda now=None: (real_filter(now)) & (Job.id == job.id)
    ):
        claimed = worker.claim_job(db)
    assert claimed is not None and claimed.id == job.id
    assert claimed.attempt == 2 and claimed.status == JobStatus.RUNNING.value
    assert claimed.next_attempt_at is None
    assert claimed.error_code == je.UPSTREAM_UNAVAILABLE  # last failure stays visible while running


def test_retry_exhaustion_fails_visibly_never_completed(db, fast_backoff):
    job = _running_job(db, attempt=3, max_attempts=3)
    job = _fail(db, job, APITimeoutError("synthetic"))
    assert job.status == JobStatus.FAILED.value
    assert job.error_code == je.TIMEOUT and job.next_attempt_at is None
    assert job.error.startswith("Retries exhausted after 3 attempt(s) (timeout)")
    (audit,) = _audits(db, job.id, "job.failed")
    details = json.loads(audit.details) if isinstance(audit.details, str) else audit.details
    assert details["retries_exhausted"] is True and details["error_code"] == je.TIMEOUT
    assert not _claimable(db, job.id, now=datetime.utcnow() + timedelta(days=1))


def test_hard_ceiling_bounds_attempts_even_if_max_attempts_is_large(db, fast_backoff):
    job = _running_job(db, attempt=je.MAX_ATTEMPTS_CEILING, max_attempts=50)
    job = _fail(db, job, APIStatusError(502))
    assert job.status == JobStatus.FAILED.value and job.error.startswith("Retries exhausted")


def test_claim_stops_at_ceiling_when_max_attempts_is_above_it(db):
    """A queued job whose max_attempts exceeds the ceiling is not claimed once attempt hits it."""
    from app import worker

    job_id = _queued_job(db, max_attempts=je.MAX_ATTEMPTS_CEILING + 40)
    job = db.get(Job, job_id)
    job.attempt = je.MAX_ATTEMPTS_CEILING
    db.commit()
    real_filter = worker.claimable_filter
    with patch.object(
        worker, "claimable_filter", lambda now=None: real_filter(now) & (Job.id == job_id)
    ):
        assert worker.claim_job(db) is None
    db.expire_all()
    job = db.get(Job, job_id)
    assert job.status == JobStatus.QUEUED.value and job.attempt == je.MAX_ATTEMPTS_CEILING
    assert not _claimable(db, job_id)
    job.attempt = je.MAX_ATTEMPTS_CEILING - 1
    db.commit()
    with patch.object(
        worker, "claimable_filter", lambda now=None: real_filter(now) & (Job.id == job_id)
    ):
        claimed = worker.claim_job(db)
    assert claimed is not None and claimed.id == job_id
    assert claimed.attempt == je.MAX_ATTEMPTS_CEILING


@pytest.mark.parametrize(
    "exc, code",
    [
        (ValueError("Missing questionnaire_id or workspace_id"), je.BAD_INPUT),
        (AuthenticationError(), je.AUTH_FAILED),
        (je.JobConfigError("OPENAI_API_KEY is not set or empty."), je.CONFIG_ERROR),
        (ClientError("NoSuchKey", 404), je.NOT_FOUND),
        (RuntimeError("unexplained"), je.INTERNAL_ERROR),
    ],
)
def test_terminal_errors_stop_on_first_attempt(db, fast_backoff, exc, code):
    job = _running_job(db, attempt=1, max_attempts=3)
    job = _fail(db, job, exc)
    assert job.status == JobStatus.FAILED.value and job.error_code == code
    assert not job.error.startswith("Retries exhausted") and job.next_attempt_at is None
    assert "sk-SYNTHETIC" not in job.error
    assert not _audits(db, job.id, "job.retry_scheduled")


def test_model_failures_keep_tc11001_codes_and_catalog_retryability(db, fast_backoff):
    """TC-11-001 x TC-10-002: one jobs.error_code column; model failures keep their model_* code."""
    from app.services.model_outcomes import ModelCallError, ModelFailure, ModelOutcomeCode

    transient = ModelCallError(
        ModelFailure(code=ModelOutcomeCode.MODEL_RATE_LIMITED, provider_status=429)
    )
    assert je.classify(transient) == "model_rate_limited" and je.is_retryable_code(
        "model_rate_limited"
    )
    job = _fail(db, _running_job(db), transient)
    assert job.status == JobStatus.QUEUED.value and job.error_code == "model_rate_limited"
    assert job.next_attempt_at is not None and transient.failure.message in job.error

    for code in (
        ModelOutcomeCode.MODEL_QUOTA_EXHAUSTED,
        ModelOutcomeCode.MODEL_CREDENTIALS_INVALID,
        ModelOutcomeCode.MODEL_REQUEST_REJECTED,
    ):
        exc = ModelCallError(ModelFailure(code=code))
        job = _fail(db, _running_job(db), exc)
        assert job.status == JobStatus.FAILED.value and job.error_code == code.value
        assert job.error == exc.failure.message and job.next_attempt_at is None
    assert je.is_fatal_code("model_quota_exhausted") and not je.is_retryable_code("model_error")
    assert not je.is_retryable_code("grounded")  # non-failure outcomes are not job error codes
    assert je.RetryableJobError("model_timeout").code == "model_timeout"
    with pytest.raises(ValueError):
        je.RetryableJobError("model_quota_exhausted")


def test_retry_not_requeued_when_identical_job_already_queued(db, fast_backoff):
    key = f"tc10002-{uuid.uuid4().hex}"
    job = _running_job(db, key=key)
    newer = Job(
        workspace_id=WS,
        kind="export",
        status=JobStatus.QUEUED.value,
        payload="{}",
        attempt=0,
        idempotency_key=key,
    )
    db.add(newer)
    db.commit()
    job = _fail(db, job, RateLimitError())
    assert job.status == JobStatus.FAILED.value and job.error_code == je.RATE_LIMITED
    assert f"identical queued job {newer.id}" in job.error


def test_index_retry_keeps_document_pending_and_terminal_marks_failed(db, fast_backoff):
    doc = Document(
        workspace_id=WS,
        storage_key=f"raw/{WS}/{uuid.uuid4().hex}.txt",
        filename="synthetic.txt",
        status="failed",  # index_service marks failed before raising
    )
    db.add(doc)
    db.commit()
    job = _running_job(db, kind="index_document", payload={"document_id": doc.id})
    _fail(db, job, APIStatusError(503))
    db.refresh(doc)
    assert doc.status == "uploaded" and "Attempt 1 of 3 failed" in doc.index_error
    job = db.get(Job, job.id)
    job.status, job.attempt = JobStatus.RUNNING.value, 3
    db.commit()
    _fail(db, job, APIStatusError(503))
    db.refresh(doc)
    assert doc.status == "failed" and doc.index_error.startswith("Retries exhausted")


def test_unreadable_pdf_is_terminal_and_marks_questionnaire_failed(db, fast_backoff):
    """Merged-master behaviour (TC-01-003a) kept inside the classified failure path."""
    from app.services.pdf_text import PdfNoTextError

    qnr = Questionnaire(
        workspace_id=WS,
        filename=f"synthetic-{uuid.uuid4().hex}.pdf",
        storage_key=f"raw/{WS}/{uuid.uuid4().hex}.pdf",
        status="uploaded",
    )
    db.add(qnr)
    db.commit()
    job = _running_job(db, kind="parse_questionnaire", payload={"questionnaire_id": qnr.id})
    job = _fail(db, job, PdfNoTextError())
    assert job.status == JobStatus.FAILED.value and job.error_code == je.BAD_INPUT
    assert not _audits(db, job.id, "job.retry_scheduled")
    db.refresh(qnr)
    assert qnr.status == "failed"
    assert json.loads(qnr.parse_metadata)["count"] == 0
    db.delete(qnr)
    db.commit()


def test_process_one_job_end_to_end_retry_then_success(db, fast_backoff, monkeypatch):
    """Drive the real worker loop body: attempt 1 fails transiently, attempt 2 succeeds and clears the error."""
    from app import worker

    job = Job(
        workspace_id=WS,
        kind="export",
        status=JobStatus.QUEUED.value,
        payload=json.dumps({"questionnaire_id": 0, "workspace_id": WS}),
        attempt=0,
        max_attempts=3,
    )
    db.add(job)
    db.commit()
    job_id = job.id
    monkeypatch.setattr(worker, "SessionFactory", SessionLocal)
    monkeypatch.setattr(worker, "last_compliance_webhook_run", time.time())
    monkeypatch.setattr(worker, "last_usage_cleanup_run", time.time())
    real_filter = worker.claimable_filter
    monkeypatch.setattr(
        worker, "claimable_filter", lambda now=None: real_filter(now) & (Job.id == job_id)
    )
    outcomes = iter([APIConnectionError("synthetic"), None])

    def fake_run(j, s):
        exc = next(outcomes)
        if exc:
            raise exc
        j.result = json.dumps({"export_record_id": None})

    monkeypatch.setattr(worker, "run_job", fake_run)
    monkeypatch.setattr(worker, "notify_workspace", lambda *a, **k: None)
    assert worker._process_one_job() is True
    db.expire_all()
    j = db.get(Job, job_id)
    assert (j.status, j.attempt, j.error_code) == ("queued", 1, je.CONNECTION_ERROR)
    assert worker._process_one_job() is False  # backoff not elapsed: nothing claimable
    j.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    assert worker._process_one_job() is True
    db.expire_all()
    j = db.get(Job, job_id)
    assert (j.status, j.attempt) == ("completed", 2)
    assert j.error is None and j.error_code is None and j.next_attempt_at is None


# A completed job may carry a non-fatal error_code (TC-02-BUG-015 will set evidence_gaps_failed). TC-10-002's
# success and failure paths must never overwrite it.
GAPS_CODE = "evidence_gaps_failed"


def _worker_loop_for(monkeypatch, job_id):
    from app import worker

    monkeypatch.setattr(worker, "SessionFactory", SessionLocal)
    monkeypatch.setattr(worker, "last_compliance_webhook_run", time.time())
    monkeypatch.setattr(worker, "last_usage_cleanup_run", time.time())
    real_filter = worker.claimable_filter
    monkeypatch.setattr(
        worker, "claimable_filter", lambda now=None: real_filter(now) & (Job.id == job_id)
    )
    monkeypatch.setattr(worker, "notify_workspace", lambda *a, **k: None)
    return worker


def _queued_job(db, max_attempts=3) -> int:
    job = Job(
        workspace_id=WS,
        kind="export",
        status=JobStatus.QUEUED.value,
        payload=json.dumps({"questionnaire_id": 0, "workspace_id": WS}),
        attempt=0,
        max_attempts=max_attempts,
    )
    db.add(job)
    db.commit()
    return job.id


def test_success_keeps_error_code_the_handler_set_on_a_completed_job(db, fast_backoff, monkeypatch):
    job_id = _queued_job(db)
    worker = _worker_loop_for(monkeypatch, job_id)

    def fake_run(j, s):
        j.error_code = GAPS_CODE
        j.error = "Evidence gap generation failed (answers were saved)."

    monkeypatch.setattr(worker, "run_job", fake_run)
    assert worker._process_one_job() is True
    db.expire_all()
    j = db.get(Job, job_id)
    assert (j.status, j.error_code) == ("completed", GAPS_CODE)
    assert j.error == "Evidence gap generation failed (answers were saved)."


def test_retry_then_success_clears_only_the_stale_attempt_error(db, fast_backoff, monkeypatch):
    job_id = _queued_job(db)
    worker = _worker_loop_for(monkeypatch, job_id)
    outcomes = iter([APIConnectionError("synthetic"), None])

    def fake_run(j, s):
        exc = next(outcomes)
        if exc:
            raise exc
        j.error_code = GAPS_CODE  # set by this (successful) run, not left over from attempt 1

    monkeypatch.setattr(worker, "run_job", fake_run)
    assert worker._process_one_job() is True
    j = db.get(Job, job_id)
    assert (j.status, j.error_code) == ("queued", je.CONNECTION_ERROR)
    j.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    assert worker._process_one_job() is True
    db.expire_all()
    j = db.get(Job, job_id)
    assert (j.status, j.attempt, j.error_code) == ("completed", 2, GAPS_CODE)
    assert j.error is None  # attempt 1's "Attempt 1 of 3 failed ..." no longer describes the job


@pytest.mark.parametrize(
    "exc", [APIConnectionError("synthetic"), RuntimeError("boom"), AuthenticationError()]
)
def test_failure_handler_never_overwrites_a_committed_completion(db, fast_backoff, exc):
    job = _running_job(db, attempt=1, max_attempts=3)
    job.status = JobStatus.COMPLETED.value
    job.error_code = GAPS_CODE
    job.completed_at = datetime.utcnow()
    db.commit()
    j = _fail(db, job, exc)
    assert (j.status, j.error_code, j.next_attempt_at) == ("completed", GAPS_CODE, None)
    assert not _audits(db, job.id, "job.failed")
    assert not _audits(db, job.id, "job.retry_scheduled")


def test_post_commit_exception_in_worker_loop_keeps_completed_error_code(
    db, fast_backoff, monkeypatch
):
    """A handler that commits the completion (with a non-fatal code) and then raises stays completed."""
    job_id = _queued_job(db)
    worker = _worker_loop_for(monkeypatch, job_id)

    def fake_run(j, s):
        j.status = JobStatus.COMPLETED.value
        j.error_code = GAPS_CODE
        s.commit()
        raise APIConnectionError("synthetic: raised after the completion was committed")

    monkeypatch.setattr(worker, "run_job", fake_run)
    assert worker._process_one_job() is True
    db.expire_all()
    j = db.get(Job, job_id)
    assert (j.status, j.attempt, j.error_code, j.next_attempt_at) == (
        "completed",
        1,
        GAPS_CODE,
        None,
    )


# ---------------------------------------------------------------------------------------------------------
# Jobs API (AC2)
# ---------------------------------------------------------------------------------------------------------


def _login(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert r.status_code == 200, r.text


def test_jobs_api_exposes_retry_state(client: TestClient, db, fast_backoff):
    _login(client)
    job = _fail(db, _running_job(db), RateLimitError())
    body = client.get(f"/api/jobs/{job.id}?workspace_id=1").json()
    assert body["status"] == "queued" and body["retry_scheduled"] is True
    assert body["error_code"] == "rate_limited" and body["retryable"] is True
    assert body["next_attempt_at"] and body["attempt"] == 1 and body["max_attempts"] == 3
    assert body["retries_exhausted"] is False

    exhausted = _fail(db, _running_job(db, attempt=3), APIStatusError(503))
    body = client.get(f"/api/jobs/{exhausted.id}?workspace_id=1").json()
    assert body["status"] == "failed" and body["retries_exhausted"] is True
    assert body["retry_scheduled"] is False and body["error"].startswith("Retries exhausted")

    terminal = _fail(db, _running_job(db), ValueError("Missing questionnaire_id"))
    body = client.get(f"/api/jobs/{terminal.id}?workspace_id=1").json()
    assert body["status"] == "failed" and body["retryable"] is False
    assert body["retries_exhausted"] is False and body["error_code"] == "bad_input"


# ---------------------------------------------------------------------------------------------------------
# Generate: per-question provider errors are never reported as success
# ---------------------------------------------------------------------------------------------------------


@pytest.fixture
def fake_gen(monkeypatch):
    """Evidence for every question, fake embeddings; the batched LLM call is replaced by ``fake_gen.impl``."""
    from app.core.config import get_settings

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-placeholder-not-a-real-key")
    get_settings.cache_clear()
    evidence = [
        {"id": 1, "text": "Synthetic: data is encrypted at rest.", "metadata": {}, "score": 0.9}
    ]
    state = SimpleNamespace(impl=None, calls=0)

    def batched(batch, *a, **kw):
        state.calls += 1
        return state.impl(batch)

    with (
        patch(
            "app.services.answer_generation.embed_texts",
            lambda texts, **_kw: [[0.001] * 1536 for _ in texts],
        ),
        patch(
            "app.services.answer_generation.RetrievalService.batch_search",
            lambda self, ws, queries, **kw: [list(evidence) for _ in queries],
        ),
        patch("app.services.answer_generation._generate_batched_answers", batched),
        patch("app.services.answer_generation.retrieval_cache_get", return_value=None),
        patch("app.services.answer_generation.answer_cache_get", return_value=None),
        patch("app.services.answer_generation.answer_cache_set", return_value=None),
        patch(
            "app.services.evidence_gap_service.generate_gaps_for_questionnaire",
            return_value={"generated": 0},
            create=True,
        ),
        patch("openai.OpenAI", lambda **kw: SimpleNamespace()),
    ):
        yield state
    get_settings.cache_clear()


def _gen_job(db, n=3):
    qnr = Questionnaire(workspace_id=WS, storage_key=None, filename="gen.xlsx", status="parsed")
    db.add(qnr)
    db.commit()
    tag = uuid.uuid4().hex
    qs = [Question(questionnaire_id=qnr.id, text=f"Synthetic Q{i} {tag}?") for i in range(n)]
    db.add_all(qs)
    db.commit()
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
    return job, qs


def _answers(db, qs):
    db.expire_all()
    return {
        a.question_id: a
        for a in db.query(Answer).filter(Answer.question_id.in_([q.id for q in qs]))
    }


def _drafts(batch):
    from app.services.answer_generation import GeneratedAnswer
    from app.services.model_outcomes import ModelOutcomeCode

    return [
        GeneratedAnswer(
            q.id,
            f"Synthetic draft for {q.id}.",
            [{"chunk_id": 1}],
            80,
            "draft",
            ModelOutcomeCode.GROUNDED,
        )
        for q, _ev in batch
    ]


def test_generate_transient_llm_errors_retry_only_failed_questions(db, fake_gen, fast_backoff):
    from app import worker

    job, qs = _gen_job(db)
    fake_gen.impl = lambda batch: (_ for _ in ()).throw(RateLimitError())
    with pytest.raises(je.RetryableJobError) as ei:
        worker.run_generate_answers(job, db, json.loads(job.payload))
    assert ei.value.code == je.RATE_LIMITED
    stats = json.loads(db.get(Job, job.id).result)["stats"]
    assert (
        stats["llm_errors_retryable"] == 3 and stats["llm_error_code_retryable"] == "rate_limited"
    )
    worker._handle_job_failure(db, job, json.loads(job.payload), ei.value, 1.0)
    db.expire_all()
    job = db.get(Job, job.id)
    assert job.status == "queued" and job.error_code == je.RATE_LIMITED  # not "completed"
    assert {a.insufficient_reason for a in _answers(db, qs).values()} == {"llm_error"}

    # Attempt 2: provider recovers; llm_error placeholders are regenerated (guard does not protect them).
    job.status, job.attempt = "running", 2
    db.commit()
    fake_gen.impl = _drafts
    worker.run_generate_answers(job, db, json.loads(job.payload))
    answers = _answers(db, qs)
    assert all(a.status == "draft" and a.insufficient_reason is None for a in answers.values())
    assert json.loads(job.result)["stats"].get("llm_errors", 0) == 0


def test_generate_auth_error_stops_explicitly(db, fake_gen, fast_backoff):
    """A 401 is TC-11-001's fatal model_credentials_invalid: the run stops and the job is never retried."""
    from app import worker
    from app.services.model_outcomes import ModelCallError

    job, _qs = _gen_job(db)
    fake_gen.impl = lambda batch: (_ for _ in ()).throw(AuthenticationError())
    with pytest.raises(ModelCallError) as ei:
        worker.run_generate_answers(job, db, json.loads(job.payload))
    assert je.classify(ei.value) == "model_credentials_invalid"
    job = _fail(db, job, ei.value)
    assert job.status == "failed" and job.error_code == "model_credentials_invalid"
    assert job.next_attempt_at is None and not job.error.startswith("Retries exhausted")
    assert "sk-SYNTHETIC" not in job.error and "synthetic invalid key body" not in job.error


def test_generate_bad_request_question_stays_visible_placeholder(db, fake_gen):
    from app import worker

    job, qs = _gen_job(db, n=1)
    fake_gen.impl = lambda batch: (_ for _ in ()).throw(APIStatusError(400, "synthetic"))
    worker.run_generate_answers(job, db, json.loads(job.payload))  # not a job failure
    stats = json.loads(job.result)["stats"]
    assert stats["llm_errors"] == 1 and stats["llm_errors_other"] == 1
    assert _answers(db, qs)[qs[0].id].insufficient_reason == "llm_error"


def test_generate_missing_api_key_is_terminal_config_error(db, monkeypatch):
    """TC-11-001 raises ModelCallError(model_credentials_missing); TC-10-002 keeps that code and never retries it."""
    from app import worker
    from app.core.config import get_settings
    from app.services.model_outcomes import ModelCallError

    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    try:
        job, _qs = _gen_job(db, n=1)
        with (
            patch(
                "app.services.answer_generation.embed_texts",
                lambda texts, **_kw: [[0.001] * 1536 for _ in texts],
            ),
            pytest.raises(ModelCallError) as ei,
        ):
            worker.run_generate_answers(job, db, json.loads(job.payload))
        assert je.classify(ei.value) == "model_credentials_missing"
        failed = _fail(db, job, ei.value)
        assert failed.status == "failed" and failed.error_code == "model_credentials_missing"
        assert failed.next_attempt_at is None and not failed.error.startswith("Retries exhausted")
        assert failed.error == ei.value.failure.message  # TC-11-001 catalog text, unchanged
    finally:
        get_settings.cache_clear()


def test_write_guard_does_not_protect_llm_error_placeholders():
    cutoff = datetime.utcnow() - timedelta(hours=1)
    guard = AnswerWriteGuard(cutoff)
    newer = datetime.utcnow()
    placeholder = SimpleNamespace(
        status="insufficient_evidence", insufficient_reason="llm_error", updated_at=newer
    )
    declined = SimpleNamespace(
        status="insufficient_evidence", insufficient_reason="llm_declined", updated_at=newer
    )
    approved = SimpleNamespace(status="approved", insufficient_reason="llm_error", updated_at=newer)
    assert guard.is_protected(placeholder) is False
    assert guard.is_protected(declined) is True
    assert guard.is_protected(approved) is True


# ---------------------------------------------------------------------------------------------------------
# Index: provider errors propagate classified (no longer a generic ValueError)
# ---------------------------------------------------------------------------------------------------------


def test_index_no_embeddings_raises_classified_errors(monkeypatch):
    from app.services import index_service

    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(openai_api_key="sk-test-placeholder"),
    )
    with pytest.raises(je.RetryableJobError) as ei:
        index_service._raise_no_embeddings(RateLimitError())
    assert ei.value.code == je.RATE_LIMITED and "body" not in str(ei.value)
    with pytest.raises(je.TerminalJobError) as ei:
        index_service._raise_no_embeddings(AuthenticationError())
    assert ei.value.code == je.AUTH_FAILED
    with pytest.raises(ValueError):
        index_service._raise_no_embeddings(None)
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(openai_api_key=""))
    with pytest.raises(je.JobConfigError) as ei:
        index_service._raise_no_embeddings(RateLimitError())
    assert str(ei.value) == "AI provider is not configured"
    assert "OPENAI_API_KEY" not in str(ei.value)


def test_missing_provider_config_stores_neutral_message_not_the_env_var(db, caplog, monkeypatch):
    """The stored job and document errors name no environment variable. The log line does."""
    import logging

    from app.services import index_service

    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(openai_api_key=""),
    )
    doc = Document(
        workspace_id=WS,
        storage_key="synthetic/not-configured.bin",
        filename="synthetic.bin",
        status="uploaded",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    with caplog.at_level(logging.WARNING, logger="app.services.index_service"):
        with pytest.raises(je.JobConfigError) as ei:
            index_service._raise_no_embeddings(None)
    assert str(ei.value) == "AI provider is not configured"
    assert "OPENAI_API_KEY" not in str(ei.value)
    assert any("OPENAI_API_KEY" in record.message for record in caplog.records)
    job = _running_job(
        db,
        kind="index_document",
        payload={"document_id": doc.id, "workspace_id": WS},
    )
    failed = _fail(db, job, ei.value)
    assert failed.error_code == je.CONFIG_ERROR
    assert "AI provider is not configured" in (failed.error or "")
    assert "OPENAI_API_KEY" not in (failed.error or "")
    db.expire_all()
    stored = db.get(Document, doc.id)
    assert stored.status == "failed"
    assert "AI provider is not configured" in (stored.index_error or "")
    assert "OPENAI_API_KEY" not in (stored.index_error or "")


# ---------------------------------------------------------------------------------------------------------
# Migration rollback
# ---------------------------------------------------------------------------------------------------------


def test_migration_downgrade_and_upgrade_roundtrip(_ensure_test_data):
    if not _ensure_test_data:
        pytest.skip("Postgres test DB unavailable")
    import importlib.util

    api_dir = Path(__file__).resolve().parents[2]
    mig = api_dir / "alembic" / "versions" / "078_tc10002_job_retries.py"
    spec = importlib.util.spec_from_file_location("tc10002_mig", mig)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "tc10002_job_retries"
    # Re-parented onto master's head after #25 (tc25005_case_study_consent).
    assert mod.down_revision == "tc25005_case_study_consent"
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
        return r.stdout

    def cols():
        engine.dispose()
        return {c["name"] for c in inspect(engine).get_columns("jobs")}

    alembic("downgrade", mod.down_revision)
    try:
        assert "next_attempt_at" not in cols()
        assert "idempotency_key" in cols()  # TC-10-003 columns untouched
        assert "error_code" in cols()  # TC-11-001's column is not owned by this revision
    finally:
        alembic("upgrade", "head")
    assert {"error_code", "next_attempt_at"} <= cols()
    heads = alembic("heads")
    # A later revision (tc24001_stripe_webhook_events) may be the single head.
    # next_attempt_at above is what proves this revision was reapplied.
    assert len(heads.strip().splitlines()) == 1
    assert "(head)" in heads
