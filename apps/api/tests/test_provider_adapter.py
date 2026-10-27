"""TC-11-001: typed model responses and failures (provider adapter contract).

Fakes/stubs only: no real or paid model calls, OPENAI_API_KEY stays empty in the environment,
and Python-level outbound sockets are blocked for every test in this module. Synthetic data only.
(Placed outside tests/release/ per Coordinator ruling Q3; that directory is owned by TC-02-001.)
"""

from __future__ import annotations

import contextlib
import json
import socket
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import openai
import pytest

try:  # openai>=3 ships its HTTP client as ``httpx2``
    import httpx2 as _httpx
except ImportError:  # pragma: no cover - older openai clients
    import httpx as _httpx

from app.core.api_errors import ApiError, job_error_payload, outcome_payload
from app.services import answer_generation as ag
from app.services.model_outcomes import (
    OUTCOME_CATALOG,
    ModelCallError,
    ModelFailure,
    ModelOutcomeCode,
    classify_provider_exception,
    completion_failure,
    failure_from_exception,
    read_completion,
)

# TC-02-001 scans assignments whose name contains "secret". This marker must never
# surface in any public message.
CANARY = "SYNTH-PROVIDER-BODY-7f3a9c"
FAKE_EMB = [0.1] * 1536
EVIDENCE = [
    {
        "id": 101,
        "text": "Synthetic policy: access reviews are performed quarterly.",
        "metadata": {"filename": "synthetic_policy.docx", "document_id": 9001},
        "score": 0.82,
    }
]
API_ERROR_KEYS = {"code", "message", "request_id", "retryable"}


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    """Fail loudly on any Python-level outbound connection (provider SDKs use Python sockets)."""

    def _blocked(*_a, **_k):
        raise AssertionError("network access is blocked in TC-11-001 tests")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(ag.time, "sleep", lambda *_a, **_k: None)
    yield


# ---------------------------------------------------------------------------
# Synthetic provider exceptions (real openai classes, fake HTTP objects, never sent)
# ---------------------------------------------------------------------------

_REQ = _httpx.Request("POST", "https://provider.invalid/v1/chat/completions")


def _status_error(cls, status: int, code: str | None = None):
    body = {"error": {"message": f"upstream detail {CANARY}", "code": code, "type": "synthetic"}}
    resp = _httpx.Response(status, request=_REQ, json=body)
    return cls(f"Error code: {status} - {CANARY}", response=resp, body=body["error"])


def _exc(kind: str) -> BaseException:
    return {
        "auth": lambda: _status_error(openai.AuthenticationError, 401),
        "forbidden": lambda: _status_error(openai.PermissionDeniedError, 403),
        "not_found": lambda: _status_error(openai.NotFoundError, 404),
        "rate": lambda: _status_error(openai.RateLimitError, 429, "rate_limit_exceeded"),
        "quota": lambda: _status_error(openai.RateLimitError, 429, "insufficient_quota"),
        "server": lambda: _status_error(openai.InternalServerError, 503),
        "bad_request": lambda: _status_error(openai.BadRequestError, 400),
        "timeout": lambda: openai.APITimeoutError(request=_REQ),
        "connection": lambda: openai.APIConnectionError(message=f"conn {CANARY}", request=_REQ),
        "runtime": lambda: RuntimeError(f"boom {CANARY}"),
    }[kind]()


def _completion(content=None, refusal=None, finish_reason="stop", choices=True):
    if not choices:
        return SimpleNamespace(choices=[])
    msg = SimpleNamespace(content=content, refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish_reason)])


class FakeClient:
    """Records calls; returns scripted completions or raises scripted exceptions."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **_kwargs):
        self.calls += 1
        item = self.script[min(self.calls - 1, len(self.script) - 1)]
        if isinstance(item, BaseException):
            raise item
        return item


def _single(client, evidence=EVIDENCE):
    q = SimpleNamespace(id=1, text="Do you perform access reviews?")
    return ag._generate_single_question_answer(q, evidence, 1, 1, "gpt-4o-mini", 0.2, "sys", client)


def _outcome(client, evidence=EVIDENCE) -> ModelOutcomeCode:
    try:
        return _single(client, evidence).outcome
    except ModelCallError as err:
        return err.code


# ---------------------------------------------------------------------------
# AC1: distinct outcomes
# ---------------------------------------------------------------------------


def test_ac1_six_outcomes_are_distinct():
    grounded = _outcome(FakeClient(_completion("Yes. Access reviews are performed quarterly.")))
    no_evidence = _outcome(FakeClient(_completion("unused")), evidence=[])
    refusal = _outcome(FakeClient(_completion(None, refusal="I can't help with that.")))
    malformed = _outcome(FakeClient(_completion('{"answer": "yes"}')))
    unavailable = _outcome(FakeClient(_exc("not_found")))
    credentials = _outcome(FakeClient(_exc("auth")))
    got = [grounded, no_evidence, refusal, malformed, unavailable, credentials]
    assert got == [
        ModelOutcomeCode.GROUNDED,
        ModelOutcomeCode.NO_EVIDENCE,
        ModelOutcomeCode.MODEL_REFUSAL,
        ModelOutcomeCode.MODEL_MALFORMED_OUTPUT,
        ModelOutcomeCode.MODEL_UNAVAILABLE,
        ModelOutcomeCode.MODEL_CREDENTIALS_INVALID,
    ]
    assert len(set(got)) == 6
    # distinct public messages too (not all "Insufficient evidence.")
    assert len({OUTCOME_CATALOG[c].message for c in got}) == 6


def test_no_evidence_makes_no_model_call():
    client = FakeClient(_completion("unused"))
    assert _single(client, evidence=[]).outcome == ModelOutcomeCode.NO_EVIDENCE
    assert client.calls == 0


@pytest.mark.parametrize(
    "kind, code, fatal",
    [
        ("auth", ModelOutcomeCode.MODEL_CREDENTIALS_INVALID, True),
        ("forbidden", ModelOutcomeCode.MODEL_CREDENTIALS_INVALID, True),
        ("not_found", ModelOutcomeCode.MODEL_UNAVAILABLE, True),
        ("quota", ModelOutcomeCode.MODEL_QUOTA_EXHAUSTED, True),
        ("rate", ModelOutcomeCode.MODEL_RATE_LIMITED, False),
        ("server", ModelOutcomeCode.MODEL_SERVER_ERROR, False),
        ("timeout", ModelOutcomeCode.MODEL_TIMEOUT, False),
        ("connection", ModelOutcomeCode.MODEL_SERVER_ERROR, False),
        ("bad_request", ModelOutcomeCode.MODEL_REQUEST_REJECTED, False),
        ("runtime", ModelOutcomeCode.MODEL_ERROR, False),
    ],
)
def test_classify_provider_exceptions(kind, code, fatal):
    f = classify_provider_exception(_exc(kind))
    assert f.code == code
    assert f.fatal is fatal
    assert CANARY not in f.message
    assert CANARY not in f.log_summary()


def test_retryable_flags_follow_catalog():
    assert OUTCOME_CATALOG[ModelOutcomeCode.MODEL_TIMEOUT].retryable is True
    assert OUTCOME_CATALOG[ModelOutcomeCode.MODEL_RATE_LIMITED].retryable is True
    assert OUTCOME_CATALOG[ModelOutcomeCode.MODEL_CREDENTIALS_MISSING].retryable is False
    assert OUTCOME_CATALOG[ModelOutcomeCode.MODEL_CREDENTIALS_INVALID].retryable is False
    assert OUTCOME_CATALOG[ModelOutcomeCode.MODEL_UNAVAILABLE].retryable is False
    for code in ModelOutcomeCode:
        assert code in OUTCOME_CATALOG, code


def test_completion_envelope_checks():
    assert (
        completion_failure(read_completion(_completion(choices=False)))
        == ModelOutcomeCode.MODEL_MALFORMED_OUTPUT
    )
    assert (
        completion_failure(read_completion(_completion("   ")))
        == ModelOutcomeCode.MODEL_MALFORMED_OUTPUT
    )
    assert (
        completion_failure(read_completion(_completion("x", finish_reason="content_filter")))
        == ModelOutcomeCode.MODEL_REFUSAL
    )
    assert completion_failure(read_completion(_completion("Yes."))) is None
    # MagicMock responses (legacy tests) do not count as real refusals/finish reasons
    m = MagicMock()
    m.choices = [MagicMock()]
    m.choices[0].message.content = "Yes."
    assert completion_failure(read_completion(m)) is None


@pytest.mark.parametrize(
    "text, code",
    [
        ("Yes. Quarterly access reviews are documented.", ModelOutcomeCode.GROUNDED),
        ("Sorry, I cannot answer that.", ModelOutcomeCode.MODEL_REFUSAL),
        ("As an AI, I don't have access.", ModelOutcomeCode.MODEL_REFUSAL),
        ("Error: something", ModelOutcomeCode.MODEL_MALFORMED_OUTPUT),
        ("<html>", ModelOutcomeCode.MODEL_MALFORMED_OUTPUT),
        ("[1, 2]", ModelOutcomeCode.MODEL_MALFORMED_OUTPUT),
        ("", ModelOutcomeCode.MODEL_MALFORMED_OUTPUT),
    ],
)
def test_assess_answer_text(text, code):
    got, safe = ag.assess_answer_text(text)
    assert got == code
    assert (safe == "") == (
        code not in (ModelOutcomeCode.GROUNDED, ModelOutcomeCode.MODEL_ABSTAINED)
    )
    assert ag.validate_answer_text(text) == safe  # legacy behavior preserved


def test_model_abstained_is_not_no_evidence():
    got, safe = ag.assess_answer_text(ag.INSUFFICIENT_EVIDENCE_TEXT)
    assert got == ModelOutcomeCode.MODEL_ABSTAINED
    assert got != ModelOutcomeCode.NO_EVIDENCE


def test_transient_failure_is_typed_not_insufficient_evidence_success():
    r = _single(FakeClient(_exc("timeout")))
    assert r.answer_status == "insufficient_evidence"  # export-safe legacy status
    assert r.outcome == ModelOutcomeCode.MODEL_TIMEOUT
    assert r.failure is not None and r.failure.retryable


def test_fatal_single_failure_raises_typed_error_without_provider_text():
    with pytest.raises(ModelCallError) as ei:
        _single(FakeClient(_exc("auth")))
    assert ei.value.code == ModelOutcomeCode.MODEL_CREDENTIALS_INVALID
    assert CANARY not in str(ei.value)
    assert ei.value.__cause__ is None  # provider exception not chained


# ---------------------------------------------------------------------------
# Pipeline level (mock DB; fake client injected via openai.OpenAI patch)
# ---------------------------------------------------------------------------


def _mock_db(n: int):
    qnr = MagicMock(id=1, workspace_id=1)
    qnr.answer_evidence_document_ids_json = None
    qnr.mapping_preferred_subject_areas_json = None
    questions = [MagicMock(id=i + 1, text=f"Synthetic question {i + 1}?") for i in range(n)]
    q_qnr = MagicMock()
    q_qnr.filter.return_value.first.return_value = qnr
    q_qs = MagicMock()
    q_qs.filter.return_value.all.return_value = questions
    ws = MagicMock(ai_completion_model=None, ai_temperature=None)
    q_ws = MagicMock()
    q_ws.filter.return_value.first.return_value = ws
    q_ans = MagicMock()
    q_ans.filter.return_value.first.return_value = None
    q_ans.filter.return_value.all.return_value = []
    db = MagicMock()
    db.query.side_effect = [q_qnr, q_qs, q_ws] + [q_ans] * 200
    return db


def _run_pipeline(
    client, n=3, embed=None, key="synthetic-not-a-key", job=None, cache_get=None, upsert=None
):
    db = _mock_db(n)
    cache_get = cache_get or (lambda *_a, **_k: None)
    extra = [patch.object(ag, "_upsert_answer", side_effect=upsert)] if upsert else []
    embed = embed or (lambda texts, on_failure=None: [FAKE_EMB] * len(texts))
    with (
        patch("app.core.config.get_settings") as gs,
        patch("app.services.answer_generation.embed_texts", side_effect=embed),
        patch("app.services.answer_generation.get_corpus_version", return_value=""),
        patch("app.services.answer_generation.retrieval_cache_get", return_value=None),
        patch("app.services.answer_generation.answer_cache_get", side_effect=cache_get),
        patch("app.services.answer_generation.answer_cache_set"),
        patch("app.services.answer_generation.RetrievalService") as rs,
        contextlib.ExitStack() as stack,
        patch(
            "app.services.answer_generation.prioritize_evidence_for_answer",
            side_effect=lambda _db, ev, **_k: ev,
        ),
        patch("app.services.answer_generation.should_skip_llm", return_value=(False, None)),
        patch("openai.OpenAI", return_value=client),
    ):
        for cm in extra:
            stack.enter_context(cm)
        gs.return_value.openai_api_key = key
        gs.return_value.completion_model = "gpt-4o-mini"
        gs.return_value.openai_temperature = 0.2
        rs.return_value.search.return_value = EVIDENCE
        rs.return_value.batch_search.side_effect = lambda _ws, queries, **_k: [
            list(EVIDENCE) for _ in queries
        ]
        return ag.generate_answers_for_questionnaire(db, 1, 1, job=job)


def test_missing_credentials_is_typed_and_makes_no_call():
    client = FakeClient(_completion("unused"))
    with pytest.raises(ModelCallError) as ei:
        _run_pipeline(client, key="")
    assert ei.value.code == ModelOutcomeCode.MODEL_CREDENTIALS_MISSING
    assert isinstance(ei.value, ValueError)  # legacy callers still catch ValueError
    assert client.calls == 0


@pytest.mark.parametrize("kind", ["auth", "not_found", "quota"])
def test_fatal_failure_stops_job_with_bounded_calls(kind):
    client = FakeClient(_exc(kind))
    with pytest.raises(ModelCallError) as ei:
        _run_pipeline(client, n=3)
    assert ei.value.failure.fatal
    assert client.calls == 1  # no per-question fallback storm after a fatal failure
    assert CANARY not in str(ei.value)


def test_fatal_embedding_failure_stops_before_completion():
    client = FakeClient(_completion("unused"))

    def embed(texts, on_failure=None):
        on_failure(classify_provider_exception(_exc("auth")))
        return [None] * len(texts)

    with pytest.raises(ModelCallError) as ei:
        _run_pipeline(client, embed=embed)
    assert ei.value.code == ModelOutcomeCode.MODEL_CREDENTIALS_INVALID
    assert client.calls == 0


def test_transient_failures_record_outcome_counts():
    job = MagicMock()
    job.result = None
    count = _run_pipeline(FakeClient(_exc("runtime")), n=3, job=job)
    assert count == 3
    stats = json.loads(job.result)["stats"]
    assert stats["outcomes"].get("model_error") == 3
    assert CANARY not in job.result


def test_embedding_service_reports_typed_failure(monkeypatch, caplog):
    from app.services import embedding_service as es

    seen: list[ModelFailure] = []
    fake = MagicMock()
    fake.embeddings.create.side_effect = _exc("auth")
    monkeypatch.setattr(es.time, "sleep", lambda *_a, **_k: None)
    with (
        patch.object(es, "get_settings") as gs,
        patch("openai.OpenAI", return_value=fake),
    ):
        gs.return_value.openai_api_key = "synthetic-not-a-key"
        gs.return_value.embedding_model = "text-embedding-3-small"
        with caplog.at_level("WARNING"):
            out = es.embed_texts(["synthetic"], on_failure=seen.append)
    assert out == [None]
    assert [f.code for f in seen] == [ModelOutcomeCode.MODEL_CREDENTIALS_INVALID]
    assert "code=model_credentials_invalid" in caplog.text
    assert CANARY not in caplog.text


# ---------------------------------------------------------------------------
# AC2: shared ApiError schema, no provider payloads
# ---------------------------------------------------------------------------


def test_failure_from_exception_only_types_provider_errors():
    assert failure_from_exception(KeyError("x")) is None
    f = failure_from_exception(_exc("auth"))
    assert f is not None and f.code == ModelOutcomeCode.MODEL_CREDENTIALS_INVALID


def test_job_error_payload_schema_and_request_id():
    job = SimpleNamespace(
        status="failed",
        error_code="model_credentials_invalid",
        payload=json.dumps({"questionnaire_id": 1, "request_id": "req-origin-1"}),
    )
    p = job_error_payload(job, "req-poll-2")
    assert set(p) == API_ERROR_KEYS
    assert p["code"] == "model_credentials_invalid"
    assert p["request_id"] == "req-origin-1"
    assert p["retryable"] is False
    legacy = SimpleNamespace(status="failed", error_code=None, payload=None)
    lp = job_error_payload(legacy, "req-poll-3")
    assert lp["code"] == "job_failed" and lp["request_id"] == "req-poll-3"
    assert job_error_payload(SimpleNamespace(status="completed"), "r") is None
    ApiError(**p)  # validates


def test_answer_outcome_payload_schema():
    p = outcome_payload("model_timeout", "rid")
    assert set(p) == API_ERROR_KEYS and p["retryable"] is True
    assert outcome_payload(None, "rid") is None
    assert outcome_payload("not-a-code", "rid") is None


def test_generate_503_has_typed_error_and_request_id(client, db_session):
    from app.models import Question, Questionnaire

    qnr = Questionnaire(
        workspace_id=1, filename="tc11_synth.xlsx", status="parsed", storage_key="tc11-synth"
    )
    db_session.add(qnr)
    db_session.commit()
    db_session.add(Question(questionnaire_id=qnr.id, text="Synthetic TC-11 question?"))
    db_session.commit()
    try:
        with patch("app.api.routes.exports.get_settings") as gs:
            gs.return_value.openai_api_key = ""
            assert (
                client.post(
                    "/api/auth/login", json={"email": "demo@trust.local", "password": "j"}
                ).status_code
                == 200
            )
            r = client.post(f"/api/exports/generate/{qnr.id}?workspace_id=1", json={})
        assert r.status_code == 503
        body = r.json()
        assert "openai" in body["detail"].lower()  # legacy contract
        assert set(body["error"]) == API_ERROR_KEYS
        assert body["error"]["code"] == "model_credentials_missing"
        assert body["error"]["retryable"] is False
        assert r.headers.get("x-request-id") == body["error"]["request_id"]
    finally:
        db_session.query(Question).filter(Question.questionnaire_id == qnr.id).delete()
        db_session.delete(qnr)
        db_session.commit()


def test_worker_persists_safe_typed_job_error_and_jobs_api(client, db_session):
    """Worker failure path stores only the safe message + code; GET /jobs exposes ApiError."""
    from app import worker
    from app.models import Job

    job = Job(
        workspace_id=1,
        kind="generate_answers",
        status="running",
        payload=json.dumps(
            {"questionnaire_id": 999999, "workspace_id": 1, "request_id": "req-tc11"}
        ),
    )
    db_session.add(job)
    db_session.commit()
    job_id = job.id
    notified: list[str] = []

    def claim(session):
        return session.query(Job).filter(Job.id == job_id).first()

    def run(_job, _session):
        raise ModelCallError(classify_provider_exception(_exc("auth")))

    try:
        with (
            patch.object(worker, "claim_job", side_effect=claim),
            patch.object(worker, "run_job", side_effect=run),
            patch.object(
                worker, "notify_admins", side_effect=lambda *a, **k: notified.append(a[3])
            ),
            patch.object(worker, "process_compliance_webhook_outbox"),
        ):
            assert worker._process_one_job() is True
        db_session.expire_all()
        stored = db_session.query(Job).filter(Job.id == job_id).first()
        assert stored.status == "failed"
        assert stored.error_code == "model_credentials_invalid"
        assert CANARY not in (stored.error or "")
        assert notified and all(CANARY not in n for n in notified)

        assert (
            client.post(
                "/api/auth/login", json={"email": "demo@trust.local", "password": "j"}
            ).status_code
            == 200
        )
        r = client.get(f"/api/jobs/{job_id}?workspace_id=1")
        assert r.status_code == 200
        data = r.json()
        assert data["error_code"] == "model_credentials_invalid"
        assert set(data["error_detail"]) == API_ERROR_KEYS
        assert data["error_detail"]["request_id"] == "req-tc11"
        assert CANARY not in r.text
    finally:
        db_session.query(Job).filter(Job.id == job_id).delete()
        db_session.commit()


MIGRATION_REVISION = "tc11001_model_outcome_codes"


def _script_directory():
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    api_dir = Path(__file__).resolve().parents[1]
    cfg = Config(str(api_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_dir / "alembic"))
    return ScriptDirectory.from_config(cfg)


def _revises(script, revision: str, ancestor: str) -> bool:
    """True when revision is ancestor or a later revision in the same chain."""
    seen: set[str] = set()
    current: str | None = revision
    while current and current not in seen:
        if current == ancestor:
            return True
        seen.add(current)
        current = script.get_revision(current).down_revision
    return False


def test_migration_columns_present(db_session):
    from sqlalchemy import inspect, text

    insp = inspect(db_session.get_bind())
    assert "outcome_code" in {c["name"] for c in insp.get_columns("answers")}
    assert "error_code" in {c["name"] for c in insp.get_columns("jobs")}
    # A later ticket may re-parent onto this revision. The columns stay applied
    # as long as the database version is this revision or a descendant of it.
    script = _script_directory()
    version = db_session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert _revises(script, version, MIGRATION_REVISION)


def test_migration_has_unique_descriptive_revision_after_075():
    """Revision id stays descriptive. Parent is master's TC-21-001 head, not 075."""
    from pathlib import Path

    script = _script_directory()
    rev = script.get_revision(MIGRATION_REVISION)
    assert rev.down_revision == "tc21001_framework_catalog_rights"
    assert Path(rev.path).name == "076_tc11001_model_outcome_codes.py"
    assert "076" not in {r.revision for r in script.walk_revisions()}
    heads = script.get_heads()
    assert len(heads) == 1
    assert _revises(script, heads[0], MIGRATION_REVISION)


def test_request_ids_are_unique_per_request(client):
    a = client.get("/healthz").headers.get("x-request-id")
    b = client.get("/healthz").headers.get("x-request-id")
    assert a and b and a != b
    uuid.UUID(a)


# ---------------------------------------------------------------------------
# Review item 2: answer-cache hits are never "grounded" (no citation checks until TC-11-003)
# ---------------------------------------------------------------------------

CACHED = {
    "text": "Yes. Access reviews are performed quarterly.",
    "citations": [{"chunk_id": 101, "snippet": "Synthetic policy: access reviews are quarterly."}],
    "confidence": 88,
}


def test_grounded_unverified_catalog_entry():
    spec = OUTCOME_CATALOG[ModelOutcomeCode.GROUNDED_UNVERIFIED]
    assert ModelOutcomeCode.GROUNDED_UNVERIFIED.value == "grounded_unverified"
    assert ModelOutcomeCode.GROUNDED_UNVERIFIED != ModelOutcomeCode.GROUNDED
    assert spec.is_failure is False and spec.fatal is False and spec.http_status == 200
    assert spec.message != OUTCOME_CATALOG[ModelOutcomeCode.GROUNDED].message
    assert "not been re-checked" in spec.message
    p = outcome_payload("grounded_unverified", "rid")
    assert set(p) == API_ERROR_KEYS
    assert p["code"] == "grounded_unverified" and p["message"] == spec.message
    ApiError(**p)


def test_cache_hit_is_grounded_unverified_never_grounded():
    stored: dict[int, str] = {}

    def upsert(_db, q_id, *_a, outcome_code=None, **_k):
        stored[q_id] = outcome_code

    job = MagicMock()
    job.result = None
    client = FakeClient(_completion("unused"))
    count = _run_pipeline(
        client, n=3, job=job, cache_get=lambda *_a, **_k: dict(CACHED), upsert=upsert
    )
    assert count == 3
    assert client.calls == 0  # every question served from the answer cache
    assert stored == {i: ModelOutcomeCode.GROUNDED_UNVERIFIED for i in (1, 2, 3)}
    assert ModelOutcomeCode.GROUNDED not in stored.values()
    outcomes = json.loads(job.result)["stats"]["outcomes"]
    assert outcomes == {"grounded_unverified": 3}
    assert "grounded" not in outcomes


def test_cache_hit_and_fresh_generation_are_distinguished():
    stored: dict[int, str] = {}
    hits = iter([dict(CACHED), None])

    def upsert(_db, q_id, *_a, outcome_code=None, **_k):
        stored[q_id] = outcome_code

    job = MagicMock()
    job.result = None
    client = FakeClient(_completion("Yes. Access reviews are performed quarterly."))
    _run_pipeline(client, n=2, job=job, cache_get=lambda *_a, **_k: next(hits), upsert=upsert)
    assert stored[1] == ModelOutcomeCode.GROUNDED_UNVERIFIED  # cache hit
    assert stored[2] == ModelOutcomeCode.GROUNDED  # freshly generated this run
    assert client.calls >= 1  # the uncached question went to the (fake) model
    outcomes = json.loads(job.result)["stats"]["outcomes"]
    assert outcomes == {"grounded_unverified": 1, "grounded": 1}


def test_sweep_relabels_uncited_cached_answer():
    """A cached draft without citations is swept to no_evidence, like a fresh grounded one."""
    a = SimpleNamespace(
        text="Yes. Access reviews are performed quarterly.",
        citations="[]",
        primary_categories_json=None,
        status="draft",
        insufficient_reason=None,
        outcome_code=ModelOutcomeCode.GROUNDED_UNVERIFIED.value,
        confidence=80,
    )
    db = MagicMock()
    db.query.return_value.join.return_value.filter.return_value.all.return_value = [a]
    assert ag._sweep_draft_insufficient_narratives(db, 1) == 1
    assert a.status == "insufficient_evidence"
    assert a.outcome_code == ModelOutcomeCode.NO_EVIDENCE.value


def test_questionnaire_api_reports_grounded_unverified(client, db_session):
    from app.models import Answer, Question, Questionnaire

    qnr = Questionnaire(
        workspace_id=1, filename="tc11_cache_synth.xlsx", status="parsed", storage_key="tc11-cache"
    )
    db_session.add(qnr)
    db_session.commit()
    q = Question(questionnaire_id=qnr.id, text="Synthetic cached question?")
    db_session.add(q)
    db_session.commit()
    db_session.add(
        Answer(
            question_id=q.id,
            text=CACHED["text"],
            status="draft",
            citations=json.dumps(CACHED["citations"]),
            outcome_code="grounded_unverified",
        )
    )
    db_session.commit()
    try:
        assert (
            client.post(
                "/api/auth/login", json={"email": "demo@trust.local", "password": "j"}
            ).status_code
            == 200
        )
        r = client.get(f"/api/questionnaires/{qnr.id}?workspace_id=1")
        assert r.status_code == 200
        ans = r.json()["questions"][0]["answer"]
        assert ans["outcome_code"] == "grounded_unverified"
        assert ans["outcome"]["code"] == "grounded_unverified"
        assert ans["outcome"]["message"] == (
            OUTCOME_CATALOG[ModelOutcomeCode.GROUNDED_UNVERIFIED].message
        )
        assert ans["status"] == "draft"  # legacy status/text unchanged
    finally:
        db_session.query(Answer).filter(Answer.question_id == q.id).delete()
        db_session.query(Question).filter(Question.questionnaire_id == qnr.id).delete()
        db_session.delete(qnr)
        db_session.commit()


def test_review_page_shows_badge_for_everything_but_verified_grounded():
    """The review page hides the outcome badge only for 'grounded' (never for cache hits)."""
    from pathlib import Path

    page = Path(__file__).resolve().parents[3] / "apps/web/app/dashboard/review/[id]/page.tsx"
    if not page.exists():
        pytest.skip("web app not mounted")
    src = page.read_text()
    # Collapse whitespace so master's prettier wrapping still matches the badge condition.
    compact = "".join(src.split())
    assert "const VERIFIED_GROUNDED_OUTCOME = 'grounded'" in src
    assert "q.answer.outcome.code!==VERIFIED_GROUNDED_OUTCOME?" in compact
    # no code path special-cases the cache-hit outcome as if it were grounded
    assert "=== 'grounded_unverified'" not in src
    assert src.count("!== 'grounded'") == 0 and src.count("=== 'grounded'") == 0
