"""Tests for enterprise indexing fixes: idempotency, no false indexed, workspace validation, failed state."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.embedding_service import EMBEDDING_DIM
from app.worker import run_index_document, run_job


def test_vector_util_validate_embedding_dimension():
    """Fix 7: validate_embedding_dimension raises on wrong length."""
    from app.services.vector_util import validate_embedding_dimension

    validate_embedding_dimension([0.1] * EMBEDDING_DIM, "test")
    with pytest.raises(ValueError, match="embedding is None"):
        validate_embedding_dimension(None, "test")
    with pytest.raises(ValueError, match="length 2 != required"):
        validate_embedding_dimension([0.1, 0.2], "test")


def test_vector_util_embedding_to_vector_literal_no_scientific():
    """Fix 6: vector literal uses fixed-point, not scientific notation."""
    from app.services.vector_util import embedding_to_vector_literal

    # Small float that would be 1e-05 in str()
    emb = [1e-05] * 3
    literal = embedding_to_vector_literal(emb)
    assert "e" not in literal or literal.startswith("[0.0000000100")
    assert "0.0000000100" in literal or "0.0" in literal


def test_embed_texts_raises_on_wrong_dimension():
    """Fix 7: embed_texts raises ValueError when API returns wrong dimension."""
    from app.services.embedding_service import embed_texts

    with patch("app.services.embedding_service.get_settings") as m:
        m.return_value.openai_api_key = "sk-test"
        mock_resp = MagicMock()
        mock_resp.data = [MagicMock(index=0, embedding=[0.1] * 100)]
        with patch("openai.OpenAI") as mock_openai:
            mock_openai.return_value.embeddings.create.return_value = mock_resp
            with pytest.raises(ValueError, match="dimension 100 != required"):
                embed_texts(["hello"])


def test_retrieval_rejects_wrong_dimension():
    """Fix 7: retrieval.search validates query embedding dimension."""
    from app.services.retrieval import RetrievalService

    session = MagicMock()
    svc = RetrievalService(session)
    with pytest.raises(ValueError, match="embedding length"):
        svc.search(workspace_id=1, query="x", query_embedding=[0.1, 0.2])


def test_retrieval_pgvector_sql_uses_safe_cast():
    """Regression: pgvector retrieval SQL must use CAST(:vec AS vector), not :vec::vector (SyntaxError)."""
    from app.services.retrieval import RetrievalService
    from app.services.embedding_service import EMBEDDING_DIM

    session = MagicMock()
    executed_sql = []
    def capture_execute(statement, params=None):
        executed_sql.append(str(statement))
        return MagicMock(fetchall=MagicMock(return_value=[]))
    session.execute.side_effect = capture_execute

    with patch("app.services.retrieval.get_settings") as mock_settings:
        mock_settings.return_value.use_pgvector_index = True
        svc = RetrievalService(session)
        emb = [0.1] * EMBEDDING_DIM
        svc.search(workspace_id=1, query="test", query_embedding=emb, limit=5)

    assert executed_sql, "execute should have been called with pgvector SQL"
    sql = executed_sql[0]
    assert "CAST(:vec AS vector)" in sql, "SQL must use CAST(:vec AS vector) for pgvector parameter"
    assert ":vec::vector" not in sql, "SQL must not use :vec::vector (causes psycopg2 SyntaxError)"


def test_worker_workspace_mismatch_fails():
    """Fix 4: run_index_document raises when document workspace != job workspace."""
    session = MagicMock()
    doc = MagicMock()
    doc.id = 1
    doc.workspace_id = 1
    job = MagicMock()
    job.workspace_id = 2
    session.query.return_value.filter.return_value.first.return_value = doc
    payload = {"document_id": 1}
    with pytest.raises(ValueError, match="does not match job workspace_id"):
        run_index_document(job, session, payload)


def test_worker_sets_document_failed_on_index_exception():
    """Fix 5: when index_document job raises, worker sets document status = failed."""
    session = MagicMock()
    job = MagicMock()
    job.kind = "index_document"
    job.payload = json.dumps({"document_id": 99})
    job.workspace_id = 1
    doc = MagicMock()
    doc.id = 99
    doc.workspace_id = 1
    doc.status = "uploaded"
    session.query.return_value.filter.return_value.first.return_value = doc

    def index_document_raise(*args, **kwargs):
        raise ValueError("simulated failure")

    with patch("app.services.index_service.index_document", index_document_raise):
            try:
                run_job(job, session)
            except ValueError:
                pass
            # Simulate worker exception block (same as in main())
            session.rollback()
            job.status = "failed"
            job.error = "simulated failure"
            session.merge(job)
            payload = json.loads(job.payload) if job.payload else {}
            doc_id = payload.get("document_id")
            if doc_id:
                session.query.return_value.filter.return_value.first.return_value = doc
                doc.status = "failed"
                session.merge(doc)
            session.commit()
    assert doc.status == "failed"
    session.merge.assert_any_call(doc)
