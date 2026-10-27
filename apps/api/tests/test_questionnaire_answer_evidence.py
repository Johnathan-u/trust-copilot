"""Tests for per-questionnaire answer evidence scoping (retrieval + API)."""

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models import Document, Questionnaire
from app.services.questionnaire_answer_evidence import (
    filter_evidence_to_document_scope,
    parse_answer_evidence_document_ids,
    retrieval_cache_scope_suffix,
    validate_answer_evidence_document_ids,
)
from app.services.retrieval import RetrievalService


def test_parse_answer_evidence_none_or_empty():
    q = Questionnaire()
    q.answer_evidence_document_ids_json = None
    assert parse_answer_evidence_document_ids(q) is None
    q.answer_evidence_document_ids_json = "[]"
    assert parse_answer_evidence_document_ids(q) is None


def test_parse_answer_evidence_excludes_questionnaire_document():
    q = Questionnaire()
    q.document_id = 100
    q.answer_evidence_document_ids_json = "[100, 2, 3]"
    assert parse_answer_evidence_document_ids(q) == frozenset({2, 3})


def test_retrieval_cache_scope_suffix_stable():
    assert retrieval_cache_scope_suffix(None) == ""
    assert retrieval_cache_scope_suffix(frozenset({1, 2})) == retrieval_cache_scope_suffix(
        frozenset({2, 1})
    )


def test_filter_evidence_to_document_scope():
    allowed = frozenset({10, 20})
    ev = [
        {"id": 1, "metadata": {"document_id": 10}, "score": 0.9},
        {"id": 2, "metadata": {"document_id": 99}, "score": 0.8},
    ]
    out = filter_evidence_to_document_scope(ev, allowed)
    assert len(out) == 1
    assert out[0]["id"] == 1


def test_filter_evidence_unscoped_passthrough():
    ev = [{"id": 1, "metadata": {"document_id": 99}}]
    assert filter_evidence_to_document_scope(ev, None) == ev


def test_retrieval_search_applies_document_scope_keyword():
    db = MagicMock()
    svc = RetrievalService(db)
    scope = frozenset({5, 6})
    rows = []
    mock_chunk = MagicMock()
    mock_chunk.id = 1
    mock_chunk.text = "password policy"
    mock_chunk.metadata_ = {"document_id": 5}
    mock_chunk.document_id = 5
    rows.append(mock_chunk)
    qmock = MagicMock()
    qmock.filter.return_value.limit.return_value.all.return_value = rows
    db.query.return_value = qmock
    out = svc._keyword_search(1, "password policy requirements", 10, scope)
    assert len(out) == 1
    assert out[0]["metadata"]["document_id"] == 5


@pytest.fixture
def synthetic_scope(db_session: Session):
    """Synthetic workspace-1 questionnaire (one question, with a source document) plus a separate
    evidence document. Avoids depending on whichever seeded rows an unordered query returns."""
    from app.models import Answer, Question, Workspace
    from app.models.evidence_gap import EvidenceGap

    if not db_session.query(Workspace).filter(Workspace.id == 1).first():
        pytest.skip("no workspace")
    src = Document(
        workspace_id=1,
        storage_key="synthetic/answer-evidence-source.xlsx",
        filename="answer-evidence-source.xlsx",
        status="indexed",
    )
    ev = Document(
        workspace_id=1,
        storage_key="synthetic/answer-evidence-scope.pdf",
        filename="answer-evidence-scope.pdf",
        status="indexed",
    )
    db_session.add_all([src, ev])
    db_session.flush()
    qnr = Questionnaire(
        workspace_id=1,
        filename="answer-evidence-scope.xlsx",
        status="parsed",
        document_id=src.id,
    )
    db_session.add(qnr)
    db_session.flush()
    qn = Question(questionnaire_id=qnr.id, text="Do you encrypt data at rest?", section="S")
    db_session.add(qn)
    db_session.commit()
    ids = {"qnr": qnr.id, "question": qn.id, "source_doc": src.id, "doc": ev.id}
    yield ids
    db_session.rollback()
    db_session.query(EvidenceGap).filter(EvidenceGap.questionnaire_id == ids["qnr"]).delete(
        synchronize_session=False
    )
    db_session.query(Answer).filter(Answer.question_id == ids["question"]).delete(
        synchronize_session=False
    )
    db_session.query(Question).filter(Question.id == ids["question"]).delete(
        synchronize_session=False
    )
    db_session.query(Questionnaire).filter(Questionnaire.id == ids["qnr"]).delete(
        synchronize_session=False
    )
    db_session.query(Document).filter(Document.id.in_([ids["source_doc"], ids["doc"]])).delete(
        synchronize_session=False
    )
    db_session.commit()


def test_validate_answer_evidence_rejects_other_workspace(db_session: Session, synthetic_scope):
    """Persisted validation keeps only workspace documents and drops questionnaire file."""
    ws_id = 1
    q_doc = synthetic_scope["source_doc"]
    other = synthetic_scope["doc"]
    raw = [other, 99999999, q_doc]
    cleaned = validate_answer_evidence_document_ids(db_session, ws_id, synthetic_scope["qnr"], raw)
    assert other in cleaned
    assert 99999999 not in cleaned
    assert q_doc not in cleaned


def test_patch_answer_evidence_api_contract(client, synthetic_scope):
    """PATCH persists; GET returns the same ids (API + UI contract)."""
    r0 = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert r0.status_code == 200, r0.text
    qnr_id, doc_id = synthetic_scope["qnr"], synthetic_scope["doc"]
    r = client.patch(
        f"/api/questionnaires/{qnr_id}/answer-evidence?workspace_id=1",
        json={"document_ids": [doc_id]},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert doc_id in (data.get("answer_evidence_document_ids") or [])
    r2 = client.get(f"/api/questionnaires/{qnr_id}?workspace_id=1")
    assert r2.status_code == 200
    det = r2.json()
    assert doc_id in (det.get("answer_evidence_document_ids") or [])


def test_generate_answers_passes_document_ids_to_retrieval(db_session: Session, synthetic_scope):
    """generate_answers_for_questionnaire passes scoped document_ids into retrieval.search."""
    from app.models import Questionnaire as Qnr
    from app.services.answer_generation import generate_answers_for_questionnaire

    qnr_id, doc_id = synthetic_scope["qnr"], synthetic_scope["doc"]
    qnr = db_session.query(Qnr).filter(Qnr.id == qnr_id).one()
    qnr.answer_evidence_document_ids_json = json.dumps([doc_id])
    db_session.commit()

    captured: dict = {}

    def fake_batch_search(*args, **kwargs):
        captured["document_ids"] = kwargs.get("document_ids")
        return [[]]

    with (
        patch("app.core.config.get_settings") as mock_settings,
        patch("app.services.answer_generation.embed_texts", return_value=[[0.1] * 1536]),
        patch("app.services.answer_generation.RetrievalService") as MockRetrieval,
        patch("app.services.answer_generation.get_corpus_version", return_value=""),
        patch("app.services.answer_generation.retrieval_cache_get", return_value=None),
        patch("app.services.answer_generation.answer_cache_get", return_value=None),
        patch("openai.OpenAI"),
    ):
        mock_settings.return_value.openai_api_key = "test-key"
        mock_settings.return_value.completion_model = "gpt-4o-mini"
        mock_settings.return_value.openai_temperature = 0.35
        MockRetrieval.return_value.batch_search = fake_batch_search

        try:
            generate_answers_for_questionnaire(db_session, qnr_id, workspace_id=1)
        except Exception:
            pass

    assert captured.get("document_ids") == [doc_id]
