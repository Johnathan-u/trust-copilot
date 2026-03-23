"""Logging tests for per-question answer generation (enterprise path).

Covers: successful LLM rounds, gated skip (no evidence), OpenAI failures per question.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.services.answer_generation import generate_answers_for_questionnaire

FAKE_EMB = [0.1] * 1536

FAKE_EVIDENCE = [
    {
        "id": 1,
        "text": "We have documented access controls.",
        "metadata": {"filename": "policy.docx", "document_id": 1},
        "score": 0.8,
        "evidence_source": "retrieval",
    }
]


def _make_mock_db(num_questions: int = 3):
    questionnaire = MagicMock(id=1, workspace_id=1)
    questions = [MagicMock(id=i + 1, text=f"Question {i + 1}?") for i in range(num_questions)]

    query_ret_qnr = MagicMock()
    query_ret_qnr.filter.return_value.first.return_value = questionnaire

    query_ret_questions = MagicMock()
    query_ret_questions.filter.return_value.all.return_value = questions

    workspace = MagicMock(ai_completion_model=None, ai_temperature=None)
    query_ret_workspace = MagicMock()
    query_ret_workspace.filter.return_value.first.return_value = workspace

    answer_query = MagicMock()
    answer_query.filter.return_value.first.return_value = None

    db = MagicMock()
    db.query.side_effect = [query_ret_qnr, query_ret_questions, query_ret_workspace] + [answer_query] * 40
    return db


def _make_mock_openai_create(content: str):
    mock_create = MagicMock()
    mock_create.return_value.choices = [MagicMock()]
    mock_create.return_value.choices[0].message = MagicMock()
    mock_create.return_value.choices[0].message.content = content
    return mock_create


def test_per_question_success_logs_stats(caplog) -> None:
    """Each question gets its own LLM call; final log includes llm_calls and drafted counts."""
    with caplog.at_level("INFO"):
        db = _make_mock_db(3)
        mock_create = _make_mock_openai_create("We meet this requirement through documented controls.")
        with (
            patch("app.core.config.get_settings") as mock_settings,
            patch("app.services.answer_generation.embed_texts", return_value=[FAKE_EMB, FAKE_EMB, FAKE_EMB]),
            patch("app.services.answer_generation.RetrievalService") as MockRetrieval,
            patch("app.services.answer_generation.get_corpus_version", return_value=""),
            patch("app.services.answer_generation.retrieval_cache_get", return_value=None),
            patch("app.services.answer_generation.answer_cache_get", return_value=None),
            patch("app.services.answer_generation.prioritize_evidence_for_answer", side_effect=lambda db, ev: ev),
            patch("openai.OpenAI") as MockOpenAI,
        ):
            mock_settings.return_value.openai_api_key = "test-key"
            mock_settings.return_value.completion_model = "gpt-4o-mini"
            mock_settings.return_value.openai_temperature = 0.35
            MockRetrieval.return_value.search.return_value = list(FAKE_EVIDENCE)
            MockOpenAI.return_value.chat.completions.create = mock_create

            generate_answers_for_questionnaire(db, 1, workspace_id=1)

    log_text = " ".join(r.message for r in caplog.records)
    assert "WORKER: answer generated" in log_text
    assert "'llm_calls': 3" in log_text or "llm_calls': 3" in log_text


def test_gated_skip_no_evidence_no_llm(caplog) -> None:
    """No retrieval hits -> gated_skip, no OpenAI calls."""
    with caplog.at_level("INFO"):
        db = _make_mock_db(3)
        with (
            patch("app.core.config.get_settings") as mock_settings,
            patch("app.services.answer_generation.embed_texts", return_value=[FAKE_EMB, FAKE_EMB, FAKE_EMB]),
            patch("app.services.answer_generation.RetrievalService") as MockRetrieval,
            patch("app.services.answer_generation.get_corpus_version", return_value=""),
            patch("app.services.answer_generation.retrieval_cache_get", return_value=None),
            patch("app.services.answer_generation.answer_cache_get", return_value=None),
            patch("openai.OpenAI") as MockOpenAI,
        ):
            mock_settings.return_value.openai_api_key = "test-key"
            mock_settings.return_value.completion_model = "gpt-4o-mini"
            mock_settings.return_value.openai_temperature = 0.35
            MockRetrieval.return_value.search.return_value = []
            generate_answers_for_questionnaire(db, 1, workspace_id=1)
            MockOpenAI.return_value.chat.completions.create.assert_not_called()

    log_text = " ".join(r.message for r in caplog.records)
    assert "answer_generation gated_skip" in log_text
    assert "reason=no_evidence" in log_text


def test_llm_exception_logs_single_question(caplog) -> None:
    """OpenAI raises -> ALERT_OPENAI_FAILURE completion single question."""
    with caplog.at_level("WARNING"):
        db = _make_mock_db(3)
        with (
            patch("app.core.config.get_settings") as mock_settings,
            patch("app.services.answer_generation.embed_texts", return_value=[FAKE_EMB, FAKE_EMB, FAKE_EMB]),
            patch("app.services.answer_generation.RetrievalService") as MockRetrieval,
            patch("app.services.answer_generation.get_corpus_version", return_value=""),
            patch("app.services.answer_generation.retrieval_cache_get", return_value=None),
            patch("app.services.answer_generation.answer_cache_get", return_value=None),
            patch("app.services.answer_generation.prioritize_evidence_for_answer", side_effect=lambda db, ev: ev),
            patch("openai.OpenAI") as MockOpenAI,
        ):
            mock_settings.return_value.openai_api_key = "test-key"
            mock_settings.return_value.completion_model = "gpt-4o-mini"
            mock_settings.return_value.openai_temperature = 0.35
            MockRetrieval.return_value.search.return_value = list(FAKE_EVIDENCE)
            MockOpenAI.return_value.chat.completions.create.side_effect = RuntimeError("API error")

            generate_answers_for_questionnaire(db, 1, workspace_id=1)

    log_text = " ".join(r.message for r in caplog.records)
    assert "ALERT_OPENAI_FAILURE completion single question" in log_text
