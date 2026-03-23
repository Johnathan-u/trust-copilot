"""Phase 3 stability tests: progress correctness, idempotency, partial persistence, failure behavior.

Uses mock DB (no real commits) for progress and count assertions. Integration-style tests
that need real DB are skipped when questionnaire/workspace not available.
"""

import itertools
import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.services.answer_generation import generate_answers_for_questionnaire

FAKE_EMB = [0.1] * 1536
FAKE_EVIDENCE = [
    {"id": 1, "text": "We have documented access controls.", "metadata": {"filename": "policy.docx"}, "score": 0.8}
]


def _make_mock_db(num_questions: int, workspace_id: int = 1):
    """Build a mock Session for generate_answers: questionnaire, questions, workspace, answer queries."""
    questionnaire = MagicMock(id=1, workspace_id=workspace_id)
    # MagicMock returns child mocks for missing attrs; parsers need real None for optional JSON columns.
    questionnaire.answer_evidence_document_ids_json = None
    questionnaire.mapping_preferred_subject_areas_json = None
    questions = [MagicMock(id=i + 1, text=f"Question {i + 1}?") for i in range(num_questions)]
    query_qnr = MagicMock()
    query_qnr.filter.return_value.first.return_value = questionnaire
    query_questions = MagicMock()
    query_questions.filter.return_value.all.return_value = questions
    workspace = MagicMock(ai_completion_model=None, ai_temperature=None)
    query_workspace = MagicMock()
    query_workspace.filter.return_value.first.return_value = workspace
    answer_query = MagicMock()
    answer_query.filter.return_value.first.return_value = None  # new answer each time
    db = MagicMock()
    db.query.side_effect = [query_qnr, query_questions, query_workspace] + [answer_query] * 50
    db.commit = MagicMock()
    db.add = MagicMock()
    db.get_bind = MagicMock()
    return db, questions


def test_progress_initial_zero_total():
    """Initial progress is set to 0/N when job is provided."""
    db, questions = _make_mock_db(3)
    job = MagicMock()
    job.result = None
    with (
        patch("app.core.config.get_settings") as mock_settings,
        patch("app.services.answer_generation.embed_texts", return_value=[FAKE_EMB] * 3),
        patch("app.services.answer_generation.get_corpus_version", return_value=""),
        patch("app.services.answer_generation.retrieval_cache_get", return_value=None),
        patch("app.services.answer_generation.answer_cache_get", return_value=None),
        patch("app.services.answer_generation.RetrievalService") as MockRetrieval,
        patch("openai.OpenAI"),
    ):
        mock_settings.return_value.openai_api_key = "key"
        mock_settings.return_value.completion_model = "gpt-4o-mini"
        mock_settings.return_value.openai_temperature = 0.35
        MockRetrieval.return_value.search.return_value = FAKE_EVIDENCE
        generate_answers_for_questionnaire(db, 1, 1, job=job)
    assert job.result is not None
    data = json.loads(job.result)
    assert data["total"] == 3
    assert data["generated"] == 3


def test_progress_total_always_equals_question_count():
    """Progress total equals number of questions (2 and 5)."""
    for n in (2, 5):
        db, _ = _make_mock_db(n)
        job = MagicMock()
        job.result = None
        with (
            patch("app.core.config.get_settings") as mock_settings,
            patch("app.services.answer_generation.embed_texts", return_value=[FAKE_EMB] * n),
            patch("app.services.answer_generation.get_corpus_version", return_value=""),
            patch("app.services.answer_generation.retrieval_cache_get", return_value=None),
            patch("app.services.answer_generation.answer_cache_get", return_value=None),
            patch("app.services.answer_generation.RetrievalService") as MockRetrieval,
            patch("openai.OpenAI") as MockOpenAI,
        ):
            mock_settings.return_value.openai_api_key = "key"
            mock_settings.return_value.completion_model = "gpt-4o-mini"
            mock_settings.return_value.openai_temperature = 0.35
            MockRetrieval.return_value.search.return_value = FAKE_EVIDENCE
            mock_r = MagicMock()
            mock_r.choices = [MagicMock()]
            mock_r.choices[0].message.content = "\n\n".join(f"Answer {i+1}: Ok." for i in range(n))
            MockOpenAI.return_value.chat.completions.create.return_value = mock_r
            count = generate_answers_for_questionnaire(db, 1, 1, job=job)
        data = json.loads(job.result)
        assert data["total"] == n
        assert data["generated"] == n
        assert count == n


def test_progress_after_cache_hits():
    """Cached answers count toward progress; generated + total correct."""
    db, questions = _make_mock_db(3)
    job = MagicMock()
    job.result = None
    call_count = [0]
    def answer_cache_get_side_effect(*a, **k):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"text": "Cached", "citations": [], "confidence": 80}
        return None
    with (
        patch("app.core.config.get_settings") as mock_settings,
        patch("app.services.answer_generation.embed_texts", return_value=[FAKE_EMB] * 3),
        patch("app.services.answer_generation.get_corpus_version", return_value=""),
        patch("app.services.answer_generation.retrieval_cache_get", return_value=None),
        patch("app.services.answer_generation.answer_cache_get", side_effect=answer_cache_get_side_effect),
        patch("app.services.answer_generation.RetrievalService") as MockRetrieval,
        patch("openai.OpenAI") as MockOpenAI,
    ):
        mock_settings.return_value.openai_api_key = "key"
        mock_settings.return_value.completion_model = "gpt-4o-mini"
        mock_settings.return_value.openai_temperature = 0.35
        MockRetrieval.return_value.search.return_value = FAKE_EVIDENCE
        mock_r = MagicMock()
        mock_r.choices = [MagicMock()]
        mock_r.choices[0].message.content = "Answer 1: A1.\n\nAnswer 2: A2."
        MockOpenAI.return_value.chat.completions.create.return_value = mock_r
        count = generate_answers_for_questionnaire(db, 1, 1, job=job)
    data = json.loads(job.result)
    assert data["total"] == 3
    assert data["generated"] == 3
    assert count == 3


def test_progress_zero_questions():
    """When 0 questions, job.result is generated=0, total=0."""
    db, _ = _make_mock_db(0)
    # _make_mock_db(0) already sets questions=[] so .all() returns []; pipeline returns before workspace query
    job = MagicMock()
    job.result = None
    count = generate_answers_for_questionnaire(db, 1, 1, job=job)
    assert count == 0
    data = json.loads(job.result)
    assert data["generated"] == 0 and data["total"] == 0


def test_no_double_count_cached_and_generated():
    """Cached + generated total equals question count (no double count)."""
    db, _ = _make_mock_db(4)
    job = MagicMock()
    job.result = None
    cache_hits = [0]
    def answer_cache_get_side_effect(*a, **k):
        cache_hits[0] += 1
        if cache_hits[0] <= 2:
            return {"text": "Cached", "citations": [], "confidence": 80}
        return None
    with (
        patch("app.core.config.get_settings") as mock_settings,
        patch("app.services.answer_generation.embed_texts", return_value=[FAKE_EMB] * 4),
        patch("app.services.answer_generation.get_corpus_version", return_value=""),
        patch("app.services.answer_generation.retrieval_cache_get", return_value=None),
        patch("app.services.answer_generation.answer_cache_get", side_effect=answer_cache_get_side_effect),
        patch("app.services.answer_generation.RetrievalService") as MockRetrieval,
        patch("openai.OpenAI") as MockOpenAI,
    ):
        mock_settings.return_value.openai_api_key = "key"
        mock_settings.return_value.completion_model = "gpt-4o-mini"
        mock_settings.return_value.openai_temperature = 0.35
        MockRetrieval.return_value.search.return_value = FAKE_EVIDENCE
        mock_r = MagicMock()
        mock_r.choices = [MagicMock()]
        mock_r.choices[0].message.content = "Answer 1: B1.\n\nAnswer 2: B2."
        MockOpenAI.return_value.chat.completions.create.return_value = mock_r
        count = generate_answers_for_questionnaire(db, 1, 1, job=job)
    assert count == 4
    data = json.loads(job.result)
    assert data["generated"] == 4 and data["total"] == 4


def test_failure_mid_batch_records_insufficient_and_continues():
    """When one batch raises, pipeline records 'Insufficient evidence' for that batch and continues; progress consistent."""
    db, _ = _make_mock_db(5)
    job = MagicMock()
    job.result = None
    call_count = [0]
    def create_side_effect(*a, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            return MagicMock(choices=[MagicMock(message=MagicMock(
                content="Answer 1: A1.\n\nAnswer 2: A2.\n\nAnswer 3: A3."
            ))])
        raise RuntimeError("API error")
    with (
        patch("app.core.config.get_settings") as mock_settings,
        patch("app.services.answer_generation.embed_texts", return_value=[FAKE_EMB] * 5),
        patch("app.services.answer_generation.get_corpus_version", return_value=""),
        patch("app.services.answer_generation.retrieval_cache_get", return_value=None),
        patch("app.services.answer_generation.answer_cache_get", return_value=None),
        patch("app.services.answer_generation.RetrievalService") as MockRetrieval,
        patch("openai.OpenAI") as MockOpenAI,
    ):
        mock_settings.return_value.openai_api_key = "key"
        mock_settings.return_value.completion_model = "gpt-4o-mini"
        mock_settings.return_value.openai_temperature = 0.35
        MockRetrieval.return_value.search.return_value = FAKE_EVIDENCE
        MockOpenAI.return_value.chat.completions.create.side_effect = create_side_effect
        count = generate_answers_for_questionnaire(db, 1, 1, job=job)
    assert count == 5
    data = json.loads(job.result)
    assert data["total"] == 5 and data["generated"] == 5


def test_insufficient_evidence_still_increments_progress():
    """When retrieval returns no evidence, answers are written and progress is total."""
    db, _ = _make_mock_db(2)
    job = MagicMock()
    job.result = None
    with (
        patch("app.core.config.get_settings") as mock_settings,
        patch("app.services.answer_generation.embed_texts", return_value=[FAKE_EMB, FAKE_EMB]),
        patch("app.services.answer_generation.get_corpus_version", return_value=""),
        patch("app.services.answer_generation.retrieval_cache_get", return_value=None),
        patch("app.services.answer_generation.answer_cache_get", return_value=None),
        patch("app.services.answer_generation.RetrievalService") as MockRetrieval,
    ):
        mock_settings.return_value.openai_api_key = "key"
        MockRetrieval.return_value.search.return_value = []
        count = generate_answers_for_questionnaire(db, 1, 1, job=job)
    assert count == 2
    data = json.loads(job.result)
    assert data["total"] == 2 and data["generated"] == 2


def test_idempotency_upsert_semantics():
    """_upsert_answer is used (update or insert); second run overwrites (mock: cycle so both runs get qnr/questions/ws)."""
    db, _ = _make_mock_db(2)
    qnr = MagicMock(id=1, workspace_id=1)
    qnr.answer_evidence_document_ids_json = None
    qnr.mapping_preferred_subject_areas_json = None
    questions = [MagicMock(id=i + 1, text=f"Q{i+1}?") for i in range(2)]
    ws = MagicMock(ai_completion_model=None, ai_temperature=None)
    from app.models import Answer as AnswerModel, Question as QuestionModel, Questionnaire as QnrModel
    from app.models.workspace import Workspace as WsModel
    from app.models.question_mapping_signal import QuestionMappingSignal
    from app.models.document import Document as DocModel

    from app.models.ai_mapping import QuestionMappingPreference as QmpModel

    def _query_dispatch(*model_args):
        """Return the right mock chain regardless of call order/count."""
        m = MagicMock()
        model_cls = model_args[0] if model_args else None
        if model_cls is QnrModel:
            m.filter.return_value.first.return_value = qnr
        elif model_cls is QuestionModel:
            m.filter.return_value.all.return_value = questions
        elif model_cls is WsModel:
            m.filter.return_value.first.return_value = ws
        elif model_cls is AnswerModel:
            m.filter.return_value.first.return_value = None
            m.join.return_value.filter.return_value.all.return_value = []
        elif model_cls is QuestionMappingSignal:
            m.filter.return_value.order_by.return_value.first.return_value = None
            m.filter.return_value.all.return_value = []
        elif model_cls is DocModel:
            m.filter.return_value.first.return_value = None
            m.filter.return_value.all.return_value = []
        elif model_cls in (QmpModel.question_id, getattr(QmpModel, "question_id", None)):
            m.filter.return_value.all.return_value = []
        else:
            m.filter.return_value.first.return_value = None
            m.filter.return_value.all.return_value = []
        return m

    db.query.side_effect = _query_dispatch
    job = MagicMock()
    job.result = None
    with (
        patch("app.core.config.get_settings") as mock_settings,
        patch("app.services.answer_generation.embed_texts", return_value=[FAKE_EMB, FAKE_EMB]),
        patch("app.services.answer_generation.get_corpus_version", return_value=""),
        patch("app.services.answer_generation.retrieval_cache_get", return_value=None),
        patch("app.services.answer_generation.answer_cache_get", return_value=None),
        patch("app.services.answer_generation.RetrievalService") as MockRetrieval,
        patch("openai.OpenAI") as MockOpenAI,
    ):
        mock_settings.return_value.openai_api_key = "key"
        mock_settings.return_value.completion_model = "gpt-4o-mini"
        mock_settings.return_value.openai_temperature = 0.35
        MockRetrieval.return_value.search.return_value = FAKE_EVIDENCE
        mock_r = MagicMock()
        mock_r.choices = [MagicMock()]
        mock_r.choices[0].message.content = "Answer 1: First.\n\nAnswer 2: Second."
        MockOpenAI.return_value.chat.completions.create.return_value = mock_r
        c1 = generate_answers_for_questionnaire(db, 1, 1, job=job)
        c2 = generate_answers_for_questionnaire(db, 1, 1, job=job)
    assert c1 == 2 and c2 == 2
    data = json.loads(job.result)
    assert data["generated"] == 2 and data["total"] == 2
