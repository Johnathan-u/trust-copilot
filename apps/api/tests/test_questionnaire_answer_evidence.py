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
    assert retrieval_cache_scope_suffix(frozenset({1, 2})) == retrieval_cache_scope_suffix(frozenset({2, 1}))


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


def test_validate_answer_evidence_rejects_other_workspace(db_session: Session):
    """Persisted validation keeps only workspace documents and drops questionnaire file."""
    ws_id = 1
    qnr = (
        db_session.query(Questionnaire)
        .filter(Questionnaire.workspace_id == ws_id, Questionnaire.deleted_at.is_(None))
        .first()
    )
    if not qnr:
        pytest.skip("no questionnaire in test DB")
    q_doc = qnr.document_id
    # Pick any document in workspace that is not the questionnaire source
    other = (
        db_session.query(Document)
        .filter(Document.workspace_id == ws_id, Document.deleted_at.is_(None))
        .first()
    )
    if not other or (q_doc is not None and other.id == q_doc):
        pytest.skip("need a distinct workspace document")
    raw = [other.id, 99999999]
    if q_doc:
        raw.append(q_doc)
    cleaned = validate_answer_evidence_document_ids(db_session, ws_id, qnr.id, raw)
    assert other.id in cleaned
    assert 99999999 not in cleaned
    if q_doc:
        assert q_doc not in cleaned


def test_patch_answer_evidence_api_contract(client, db_session: Session):
    """PATCH persists; GET returns the same ids (API + UI contract)."""
    r0 = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    if r0.status_code != 200:
        pytest.skip("login failed")
    qnr = (
        db_session.query(Questionnaire)
        .filter(Questionnaire.workspace_id == 1, Questionnaire.deleted_at.is_(None))
        .first()
    )
    if not qnr:
        pytest.skip("no questionnaire")
    doc = (
        db_session.query(Document)
        .filter(Document.workspace_id == 1, Document.deleted_at.is_(None))
        .first()
    )
    if not doc or (qnr.document_id is not None and doc.id == qnr.document_id):
        pytest.skip("need a document distinct from questionnaire document_id")
    body = {"document_ids": [doc.id]}
    r = client.patch(
        f"/api/questionnaires/{qnr.id}/answer-evidence?workspace_id=1",
        json=body,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert doc.id in (data.get("answer_evidence_document_ids") or [])
    r2 = client.get(f"/api/questionnaires/{qnr.id}?workspace_id=1")
    assert r2.status_code == 200
    det = r2.json()
    assert doc.id in (det.get("answer_evidence_document_ids") or [])
    # Clear selection
    client.patch(
        f"/api/questionnaires/{qnr.id}/answer-evidence?workspace_id=1",
        json={"document_ids": []},
    )


def test_generate_answers_passes_document_ids_to_retrieval(db_session: Session):
    """generate_answers_for_questionnaire passes scoped document_ids into retrieval.search."""
    from app.models import Question, Workspace
    from app.services.answer_generation import generate_answers_for_questionnaire

    if not db_session.query(Workspace).filter(Workspace.id == 1).first():
        pytest.skip("no workspace")
    qnr = (
        db_session.query(Questionnaire)
        .filter(Questionnaire.workspace_id == 1, Questionnaire.deleted_at.is_(None))
        .first()
    )
    if not qnr:
        pytest.skip("no questionnaire")
    doc = (
        db_session.query(Document)
        .filter(Document.workspace_id == 1, Document.deleted_at.is_(None))
        .first()
    )
    if not doc:
        pytest.skip("no document")
    qn = db_session.query(Question).filter(Question.questionnaire_id == qnr.id).first()
    if not qn:
        pytest.skip("no questions")

    captured: dict = {}
    old_json = qnr.answer_evidence_document_ids_json
    qnr.answer_evidence_document_ids_json = json.dumps([doc.id])
    db_session.commit()

    def fake_search(*args, **kwargs):
        captured["document_ids"] = kwargs.get("document_ids")
        return []

    try:
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
            MockRetrieval.return_value.search = fake_search

            try:
                generate_answers_for_questionnaire(db_session, qnr.id, workspace_id=1)
            except Exception:
                pass
    finally:
        qnr.answer_evidence_document_ids_json = old_json
        db_session.commit()

    assert captured.get("document_ids") == [doc.id]
