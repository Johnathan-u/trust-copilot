"""Tests for per-questionnaire answer evidence scoping (retrieval + API)."""

import json
import uuid
from types import SimpleNamespace
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
def owned_qnr(db_session: Session):
    """A questionnaire this test owns: its own source document, one question and a distinct evidence document.

    TC-02-BUG-005 follow-up: these tests used to pick ``.first()`` questionnaire/document in workspace 1, so the
    result depended on what earlier tests had committed (they failed or skipped depending on order). Every row
    here is created fresh with a unique tag and removed afterwards, so the tests pass alone, in any order and
    after the full suite.

    TC-10-003 (#28) needs the same isolation: one unprotected question (no pre-existing answer) so the write
    guard does not skip it, and a single question so the one-vector embed stub matches. This fixture is the
    only one; tests from both changes use it.
    """
    from app.models import Question

    ws_id = 1
    tag = uuid.uuid4().hex[:12]
    source = Document(
        workspace_id=ws_id,
        storage_key=f"raw/{ws_id}/qae-src-{tag}.xlsx",
        filename=f"qae-source-{tag}.xlsx",
        status="uploaded",
    )
    evidence = Document(
        workspace_id=ws_id,
        storage_key=f"raw/{ws_id}/qae-ev-{tag}.txt",
        filename=f"qae-evidence-{tag}.txt",
        status="indexed",
    )
    db_session.add_all([source, evidence])
    db_session.flush()
    qnr = Questionnaire(
        workspace_id=ws_id,
        document_id=source.id,
        storage_key=source.storage_key,
        filename=source.filename,
        status="parsed",
    )
    db_session.add(qnr)
    db_session.flush()
    question = Question(
        questionnaire_id=qnr.id, text=f"Synthetic: is data encrypted at rest? {tag}"
    )
    db_session.add(question)
    db_session.commit()
    ids = SimpleNamespace(
        ws_id=ws_id,
        qnr_id=qnr.id,
        source_doc_id=source.id,
        evidence_doc_id=evidence.id,
        question_id=question.id,
    )
    try:
        yield ids
    finally:
        db_session.rollback()
        # Bulk SQL deletes: questions/answers/mapping rows go via ON DELETE CASCADE, references via SET NULL.
        db_session.query(Questionnaire).filter(Questionnaire.id == ids.qnr_id).delete(
            synchronize_session=False
        )
        db_session.query(Document).filter(
            Document.id.in_([ids.source_doc_id, ids.evidence_doc_id])
        ).delete(synchronize_session=False)
        db_session.commit()


def test_validate_answer_evidence_rejects_other_workspace(db_session: Session, owned_qnr):
    """Persisted validation keeps only workspace documents and drops questionnaire file."""
    raw = [owned_qnr.evidence_doc_id, 99999999, owned_qnr.source_doc_id]
    cleaned = validate_answer_evidence_document_ids(
        db_session, owned_qnr.ws_id, owned_qnr.qnr_id, raw
    )
    assert owned_qnr.evidence_doc_id in cleaned
    assert 99999999 not in cleaned
    assert owned_qnr.source_doc_id not in cleaned


def test_patch_answer_evidence_api_contract(client, owned_qnr):
    """PATCH persists; GET returns the same ids (API + UI contract)."""
    r0 = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert r0.status_code == 200, r0.text
    qnr_id, doc_id = owned_qnr.qnr_id, owned_qnr.evidence_doc_id
    r = client.patch(
        f"/api/questionnaires/{qnr_id}/answer-evidence?workspace_id=1",
        json={"document_ids": [doc_id]},
    )
    assert r.status_code == 200, r.text
    assert (r.json().get("answer_evidence_document_ids") or []) == [doc_id]
    r2 = client.get(f"/api/questionnaires/{qnr_id}?workspace_id=1")
    assert r2.status_code == 200
    assert (r2.json().get("answer_evidence_document_ids") or []) == [doc_id]
    # Clear selection
    r3 = client.patch(
        f"/api/questionnaires/{qnr_id}/answer-evidence?workspace_id=1",
        json={"document_ids": []},
    )
    assert r3.status_code == 200
    assert not r3.json().get("answer_evidence_document_ids")


def test_generate_answers_passes_document_ids_to_retrieval(db_session: Session, owned_qnr):
    """generate_answers_for_questionnaire passes scoped document_ids into retrieval batch_search.

    Uses the single ``owned_qnr`` fixture (one unprotected question). TC-10-003 skips approved answers,
    and an unordered ``.first()`` row may be fully approved or have several questions (the embed stub is
    one vector).
    """
    from app.services.answer_generation import generate_answers_for_questionnaire

    qnr = db_session.get(Questionnaire, owned_qnr.qnr_id)
    qnr.answer_evidence_document_ids_json = json.dumps([owned_qnr.evidence_doc_id])
    db_session.commit()

    captured: dict = {}

    def fake_batch_search(*args, **kwargs):
        captured["document_ids"] = kwargs.get("document_ids")
        queries = kwargs.get("queries") or (args[1] if len(args) > 1 else [None])
        return [[] for _ in queries]  # no evidence: every row is gated, no LLM call

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
        generate_answers_for_questionnaire(db_session, owned_qnr.qnr_id, workspace_id=1)

    assert captured.get("document_ids") == [owned_qnr.evidence_doc_id]
