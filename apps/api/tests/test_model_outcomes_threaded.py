"""TC-11-001 on the TC-08-005 threaded path.

Forces retrieval.batch_search onto worker threads (several questions, RETRIEVAL_MAX_THREADS>1,
NullPool engine) and the isolated gap-generation thread. Fakes only: no model calls, no network.

Asserts three things:
- A ModelCallError raised on a retrieval worker or the gap thread propagates as that same
  typed error and code. A provider exception raised on the generation worker propagates as
  ModelCallError with the same code, not a generic wrapper.
- NO_EVIDENCE and grounded_unverified are stored on answers whose retrieval ran on workers.
- Raw provider text from a worker exception never lands in job.error.
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.models import Job
from app.models.answer import Answer
from app.services import answer_generation as ag
from app.services.embedding_service import EMBEDDING_DIM
from app.services.model_outcomes import (
    OUTCOME_CATALOG,
    ModelCallError,
    ModelOutcomeCode,
    classify_provider_exception,
)
from app.services.question_normalizer import normalize_question, question_cache_hash
from app.services.retrieval import RetrievalService

# TC-02-001 scans assignments whose name contains "secret".
CANARY = "SYNTH-THREAD-BODY-7f3a9c"
FAKE_EMB = [0.02] * EMBEDDING_DIM
EVIDENCE = [
    {
        "id": 101,
        "text": "Synthetic policy: access reviews are performed quarterly.",
        "metadata": {"filename": "synthetic_policy.docx"},
        "score": 0.82,
    }
]
CACHED = {
    "text": "Yes. Access reviews are performed quarterly.",
    "citations": [{"chunk_id": 101, "snippet": "Synthetic policy: access reviews are quarterly."}],
    "confidence": 88,
}

pytestmark = pytest.mark.unit


class _Quiet:
    def __enter__(self):
        return None

    def __exit__(self, *_args):
        return False


class _Fixed:
    def __init__(self, value, many=False):
        self._value = value
        self._many = many

    def filter(self, *_a, **_k):
        return self

    def order_by(self, *_a, **_k):
        return self

    def join(self, *_a, **_k):
        return self

    def first(self):
        if self._many:
            return self._value[0] if self._value else None
        return self._value

    def all(self):
        return list(self._value) if self._many else [self._value]


class _AnswerQuery:
    def __init__(self, db):
        self._db = db
        self._qids: set[int] | None = None
        self._status: str | None = None

    def filter(self, *criteria):
        for clause in criteria:
            key = getattr(getattr(clause, "left", None), "key", None)
            value = getattr(getattr(clause, "right", None), "value", None)
            if key == "question_id" and isinstance(value, (list, tuple, set)):
                self._qids = {int(v) for v in value}
            elif key == "question_id" and isinstance(value, int):
                self._qids = {int(value)}
            elif key == "status" and isinstance(value, str):
                self._status = value
        return self

    def join(self, *_a, **_k):
        return self

    def order_by(self, *_a, **_k):
        return self

    def _rows(self):
        rows = list(self._db.answers.values())
        if self._qids is not None:
            rows = [row for row in rows if row.question_id in self._qids]
        if self._status is not None:
            rows = [row for row in rows if row.status == self._status]
        return rows

    def first(self):
        rows = self._rows()
        return rows[0] if rows else None

    def all(self):
        return self._rows()


class FakeDB:
    """Caller session whose bind is a real pooled engine, so batch_search uses threads."""

    def __init__(self, bind, qnr, questions, workspace):
        self._bind = bind
        self.qnr = qnr
        self.questions = questions
        self.workspace = workspace
        self.answers: dict[int, Answer] = {}

    def get_bind(self):
        return self._bind

    @property
    def no_autoflush(self):
        return _Quiet()

    def commit(self):
        return None

    def add(self, obj):
        qid = getattr(obj, "question_id", None)
        if qid is not None and hasattr(obj, "outcome_code"):
            self.answers[qid] = obj

    def query(self, model):
        name = getattr(model, "__name__", type(model).__name__)
        if name == "Questionnaire":
            return _Fixed(self.qnr)
        if name == "Question":
            return _Fixed(self.questions, many=True)
        if name == "Workspace":
            return _Fixed(self.workspace)
        if name == "Answer":
            return _AnswerQuery(self)
        if name in {"QuestionMappingSignal", "Document"}:
            return _Fixed([], many=True)
        raise AssertionError(f"unexpected query {model!r}")


class _FakeClient:
    def __init__(self, exc, tids):
        self.exc = exc
        self.tids = tids
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **_kwargs):
        self.calls += 1
        self.tids.append(threading.get_ident())
        raise self.exc


def _auth_error():
    import openai

    try:
        import httpx2 as httpx
    except ImportError:  # pragma: no cover - older openai clients
        import httpx

    request = httpx.Request("POST", "https://provider.invalid/v1/chat/completions")
    body = {"error": {"message": f"upstream detail {CANARY}", "type": "synthetic"}}
    response = httpx.Response(401, request=request, json=body)
    return openai.AuthenticationError(
        f"Error code: 401 - {CANARY}", response=response, body=body["error"]
    )


def _assert_off_main(tids, main_tid):
    assert tids, "threaded work did not run"
    assert all(tid != main_tid for tid in tids)


def _assert_safe_job(job, notified):
    spec = OUTCOME_CATALOG[ModelOutcomeCode.MODEL_CREDENTIALS_INVALID]
    assert job.status == "failed"
    assert job.error_code == spec.code.value
    assert job.error == spec.message
    blob = (job.error or "") + (job.result or "") + "".join(notified)
    assert CANARY not in blob


def test_threaded_workers_keep_typed_outcomes_and_hide_raw_errors(monkeypatch):
    engine = create_engine("sqlite://", poolclass=NullPool)
    # Touch the pool type the production guard checks; no shared SQLite connection.
    assert isinstance(engine.pool, NullPool)
    questions = [
        SimpleNamespace(id=1, text="Synthetic no-evidence question one?"),
        SimpleNamespace(id=2, text="Synthetic no-evidence question two?"),
        SimpleNamespace(id=3, text="Synthetic cached question three?"),
        SimpleNamespace(id=4, text="Synthetic cached question four?"),
    ]
    qnr = SimpleNamespace(
        id=1,
        workspace_id=1,
        answer_evidence_document_ids_json=None,
        mapping_preferred_subject_areas_json=None,
    )
    workspace = SimpleNamespace(id=1, ai_completion_model=None, ai_temperature=None)
    db = FakeDB(engine, qnr, questions, workspace)
    main_tid = threading.get_ident()
    retrieval_tids: list[int] = []
    gen_tids: list[int] = []
    gap_tids: list[int] = []
    gap_names: list[str] = []
    state = {"mode": "mixed", "exc": None}
    auth = _auth_error()
    assert CANARY in str(auth)
    cached_hashes = {
        question_cache_hash(normalize_question(q.text)) for q in questions if q.id in (3, 4)
    }
    client = _FakeClient(auth, gen_tids)
    # Import before get_settings is patched; the worker builds its engine at import.
    from app import worker

    settings = SimpleNamespace(
        openai_api_key="synthetic-not-a-key",
        completion_model="gpt-4o-mini",
        openai_temperature=0.2,
        retrieval_max_threads=4,
        use_adaptive_concurrency=False,
    )

    def _settings():
        return settings

    def _semantic(self, workspace_id, embedding, limit, min_score=0.0, doc_scope=None):
        retrieval_tids.append(threading.get_ident())
        if state["mode"] in {"model_error", "auth"}:
            raise state["exc"]
        return []

    def _keyword(self, workspace_id, query, limit, doc_scope):
        retrieval_tids.append(threading.get_ident())
        if state["mode"] == "evidence":
            return [dict(EVIDENCE[0])]
        if "no-evidence" in (query or ""):
            return []
        return [dict(EVIDENCE[0])]

    def _cache_get(_db, _ws, q_hash, _style, _fp):
        if state["mode"] != "mixed":
            return None
        if q_hash in cached_hashes:
            return dict(CACHED)
        return None

    def _gaps(*_a, **_k):
        gap_tids.append(threading.get_ident())
        gap_names.append(threading.current_thread().name)
        exc = state.get("gap_exc")
        if exc is not None:
            raise exc
        return {"generated": 0}

    monkeypatch.setattr("app.core.config.get_settings", _settings)
    monkeypatch.setattr("app.services.retrieval.get_settings", _settings)
    monkeypatch.setattr(
        ag, "embed_texts", lambda texts, on_failure=None: [list(FAKE_EMB)] * len(texts)
    )
    monkeypatch.setattr(ag, "get_corpus_version", lambda *_a, **_k: "")
    monkeypatch.setattr(ag, "answer_cache_get", _cache_get)
    monkeypatch.setattr(ag, "answer_cache_set", lambda *_a, **_k: None)
    monkeypatch.setattr(ag.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(RetrievalService, "_semantic_search", _semantic)
    monkeypatch.setattr(RetrievalService, "_keyword_search", _keyword)
    monkeypatch.setattr("openai.OpenAI", lambda *_a, **_k: client)
    import app.services.evidence_gap_service as gaps

    monkeypatch.setattr(gaps, "generate_gaps_for_questionnaire", _gaps, raising=False)

    # --- per-question codes after retrieval on worker threads, gap thread included ---
    progress = SimpleNamespace(result=None)
    count = ag.generate_answers_for_questionnaire(db, 1, 1, job=progress)
    assert count == 4
    _assert_off_main(retrieval_tids, main_tid)
    _assert_off_main(gap_tids, main_tid)
    assert gap_names == ["gap-generation"]
    assert db.answers[1].outcome_code == ModelOutcomeCode.NO_EVIDENCE.value
    assert db.answers[2].outcome_code == ModelOutcomeCode.NO_EVIDENCE.value
    assert db.answers[3].outcome_code == ModelOutcomeCode.GROUNDED_UNVERIFIED.value
    assert db.answers[4].outcome_code == ModelOutcomeCode.GROUNDED_UNVERIFIED.value
    assert ModelOutcomeCode.GROUNDED.value not in {a.outcome_code for a in db.answers.values()}
    stats = json.loads(progress.result)["stats"]["outcomes"]
    assert stats == {"no_evidence": 2, "grounded_unverified": 2}
    assert client.calls == 0

    # --- ModelCallError raised inside batch_search stays that instance and code ---
    typed = ModelCallError(classify_provider_exception(auth))
    state["mode"] = "model_error"
    state["exc"] = typed
    retrieval_tids.clear()
    with pytest.raises(ModelCallError) as raised:
        RetrievalService(db).batch_search(1, [(q.text, list(FAKE_EMB)) for q in questions], limit=5)
    assert raised.value is typed
    assert raised.value.code == ModelOutcomeCode.MODEL_CREDENTIALS_INVALID
    assert CANARY not in str(raised.value)
    _assert_off_main(retrieval_tids, main_tid)
    retrieval_tids.clear()
    with pytest.raises(ModelCallError) as raised_gen:
        ag.generate_answers_for_questionnaire(db, 1, 1)
    assert raised_gen.value is typed
    assert raised_gen.value.code == ModelOutcomeCode.MODEL_CREDENTIALS_INVALID

    # --- gap-generation thread: same ModelCallError, codes from the retrieval workers remain ---
    db.answers.clear()
    retrieval_tids.clear()
    gap_tids.clear()
    gap_names.clear()
    state["mode"] = "mixed"
    state["exc"] = None
    state["gap_exc"] = typed
    with pytest.raises(ModelCallError) as raised_gap:
        ag.generate_answers_for_questionnaire(db, 1, 1)
    assert raised_gap.value is typed
    assert raised_gap.value.code == ModelOutcomeCode.MODEL_CREDENTIALS_INVALID
    assert CANARY not in str(raised_gap.value)
    _assert_off_main(retrieval_tids, main_tid)
    _assert_off_main(gap_tids, main_tid)
    assert gap_names == ["gap-generation"]
    assert db.answers[1].outcome_code == ModelOutcomeCode.NO_EVIDENCE.value
    assert db.answers[3].outcome_code == ModelOutcomeCode.GROUNDED_UNVERIFIED.value

    def _run_job(mode):
        job = Job(
            workspace_id=1,
            kind="generate_answers",
            status="running",
            payload=json.dumps(
                {"questionnaire_id": 1, "workspace_id": 1, "request_id": "req-thread"}
            ),
        )
        job.id = 11
        captured: list[BaseException] = []
        notified: list[str] = []
        db.answers.clear()
        retrieval_tids.clear()
        state["mode"] = mode
        state["gap_exc"] = None

        def _run(_job, _session):
            try:
                ag.generate_answers_for_questionnaire(db, 1, 1, job=_job)
            except BaseException as exc:
                captured.append(exc)
                raise

        saved = (worker.last_usage_cleanup_run, worker.last_compliance_webhook_run)
        worker.last_usage_cleanup_run = ag.time.time()
        worker.last_compliance_webhook_run = ag.time.time()
        try:
            with (
                patch.object(worker, "SessionFactory", return_value=MagicMock()),
                patch.object(worker, "claim_job", return_value=job),
                patch.object(worker, "run_job", side_effect=_run),
                patch.object(
                    worker,
                    "notify_admins",
                    side_effect=lambda *a, **_k: notified.append(a[3] if len(a) > 3 else ""),
                ),
                patch.object(worker, "process_compliance_webhook_outbox"),
            ):
                assert worker._process_one_job() is True
        finally:
            worker.last_usage_cleanup_run, worker.last_compliance_webhook_run = saved
        return job, captured, notified

    # --- retrieval worker: raw provider text does not become job.error; code is kept ---
    state["exc"] = auth
    job, captured, notified = _run_job("auth")
    assert captured and captured[0] is auth
    assert type(captured[0]).__name__ == "AuthenticationError"
    _assert_off_main(retrieval_tids, main_tid)
    _assert_safe_job(job, notified)

    # --- generation worker: provider error surfaces as ModelCallError, not raw text ---
    gen_tids.clear()
    job, captured, notified = _run_job("evidence")
    assert captured and isinstance(captured[0], ModelCallError)
    assert not isinstance(captured[0], type(auth))
    assert captured[0].code == ModelOutcomeCode.MODEL_CREDENTIALS_INVALID
    assert CANARY not in str(captured[0])
    _assert_off_main(retrieval_tids, main_tid)
    _assert_off_main(gen_tids, main_tid)
    assert client.calls >= 1
    assert db.answers
    assert {a.outcome_code for a in db.answers.values()} == {
        ModelOutcomeCode.MODEL_CREDENTIALS_INVALID.value
    }
    assert all(CANARY not in (a.text or "") for a in db.answers.values())
    _assert_safe_job(job, notified)
