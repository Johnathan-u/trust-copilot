"""Soft-deleted documents must not be retrieved or cited.

TC-08-004 gap 1 and TC-08-006 gap 2: keyword search, semantic search, rerank
inputs, citation resolution, and workspace-keyed caches still served chunks
whose document had ``deleted_at`` set. A live document in the same workspace
stays eligible. Another workspace's documents stay out of this tenant's results.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes.documents import bulk_delete_documents, delete_document, restore_document
from app.api.routes.tags import ChunkTagsBody, get_tags_by_chunks
from app.api.schemas import BulkDeleteBody
from app.core.corpus_version import get_corpus_version
from app.models import (
    Chunk,
    ControlEvidenceLink,
    Document,
    DocumentTag,
    EvidenceItem,
    Tag,
    Workspace,
    WorkspaceControl,
)
from app.services import citation_composer_service, evidence_search_service
from app.services.answer_cache import get as answer_cache_get
from app.services.answer_cache import set as answer_cache_set
from app.services.embedding_service import EMBEDDING_DIM
from app.services.question_normalizer import evidence_fingerprint_hash, question_cache_hash
from app.services.questionnaire_mapping_evidence import (
    batch_supporting_evidence_for_workspace_controls,
)
from app.services.retrieval import RetrievalService
from app.services.retrieval_cache import get as retrieval_cache_get
from app.services.retrieval_cache import set as retrieval_cache_set

_DIM = EMBEDDING_DIM


class _RetrievalSettings:
    def __init__(self, pgvector: bool) -> None:
        self.use_pgvector_index = pgvector
        self.retrieval_max_threads = 1


@dataclass
class Corpus:
    db: Session
    ws: int
    other_ws: int
    token: str
    query: str
    embedding: list[float]
    live_doc: int
    live_chunk: int
    deleted_doc: int
    deleted_chunk: int
    other_doc: int
    other_chunk: int
    orphan_chunk: int


def _embedding() -> list[float]:
    vector = [0.01] * _DIM
    vector[0] = 1.0
    return vector


def _use_pgvector(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    monkeypatch.setattr(
        "app.services.retrieval.get_settings",
        lambda: _RetrievalSettings(enabled),
    )


def _document_ids(results: list[dict]) -> set[int]:
    found: set[int] = set()
    for row in results:
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        document_id = meta.get("document_id")
        if type(document_id) is int:
            found.add(document_id)
    return found


def _citations(results: list[dict]) -> list[dict]:
    """Same citation records answer generation stores from retrieval results."""
    cited: list[dict] = []
    for row in results[:5]:
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        cited.append(
            {
                "chunk_id": row.get("id"),
                "snippet": (row.get("text") or "")[:200],
                "document_id": meta.get("document_id"),
                "filename": meta.get("filename"),
                "score": row.get("score"),
            }
        )
    return cited


def _retrieval_problems(corpus: Corpus, results: list[dict], *, orphan: bool) -> list[str]:
    documents = _document_ids(results)
    chunks = {row.get("id") for row in results}
    cited = _citations(results)
    cited_docs = {item["document_id"] for item in cited}
    problems: list[str] = []
    if corpus.live_doc not in documents or corpus.live_chunk not in chunks:
        problems.append("live document was not retrieved")
    if corpus.live_doc not in cited_docs:
        problems.append("live document was not cited")
    if corpus.deleted_doc in documents or corpus.deleted_chunk in chunks:
        problems.append("deleted document was retrieved")
    if corpus.deleted_doc in cited_docs:
        problems.append("deleted document was cited")
    if corpus.other_doc in documents or corpus.other_chunk in chunks:
        problems.append("other workspace document was retrieved")
    if orphan and corpus.orphan_chunk not in chunks:
        problems.append("chunk with no document was dropped")
    return problems


def _add_document(
    db: Session,
    workspace_id: int,
    token: str,
    role: str,
    *,
    deleted: bool,
) -> Document:
    document = Document(
        workspace_id=workspace_id,
        storage_key=f"synthetic/{token}/{role}.txt",
        filename=f"{role}-{token}.txt",
        status="indexed",
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )
    db.add(document)
    db.flush()
    return document


def _add_chunk(
    db: Session,
    workspace_id: int,
    document: Document | None,
    token: str,
    role: str,
    embedding: list[float],
) -> Chunk:
    filename = document.filename if document is not None else None
    metadata: dict = {"filename": filename} if filename else {}
    if document is not None:
        metadata["document_id"] = document.id
    chunk = Chunk(
        workspace_id=workspace_id,
        document_id=document.id if document is not None else None,
        text=f"Synthetic {token} designated policy for {role} evidence.",
        metadata_=metadata,
        embedding=embedding,
    )
    db.add(chunk)
    db.flush()
    return chunk


def _sync_sequences(db: Session) -> None:
    """Seed rows use explicit ids, so the serial sequences can sit behind MAX(id)."""
    for table in (
        "workspaces",
        "documents",
        "chunks",
        "evidence_items",
        "workspace_controls",
        "control_evidence_links",
        "tags",
        "document_tags",
        "audit_events",
    ):
        db.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"GREATEST((SELECT COALESCE(MAX(id), 0) FROM {table}), 1))"
            )
        )


@pytest.fixture
def corpus(db_session: Session, _ensure_test_data: bool):
    """Seed workspaces 1-3 exist first so this fixture never reuses or deletes them."""
    if _ensure_test_data is False:
        pytest.skip("database unavailable")
    _sync_sequences(db_session)
    token = uuid.uuid4().hex[:12]
    embedding = _embedding()
    own = Workspace(name=f"tc08004-{token}", slug=f"tc08004-{token}")
    other = Workspace(name=f"tc08004b-{token}", slug=f"tc08004b-{token}")
    db_session.add_all([own, other])
    db_session.flush()
    live = _add_document(db_session, own.id, token, "live", deleted=False)
    deleted = _add_document(db_session, own.id, token, "deleted", deleted=True)
    foreign = _add_document(db_session, other.id, token, "other", deleted=False)
    live_chunk = _add_chunk(db_session, own.id, live, token, "live", embedding)
    deleted_chunk = _add_chunk(db_session, own.id, deleted, token, "deleted", embedding)
    other_chunk = _add_chunk(db_session, other.id, foreign, token, "other", embedding)
    orphan_chunk = _add_chunk(db_session, own.id, None, token, "orphan", embedding)
    db_session.commit()
    built = Corpus(
        db=db_session,
        ws=own.id,
        other_ws=other.id,
        token=token,
        query=f"{token} designated",
        embedding=embedding,
        live_doc=live.id,
        live_chunk=live_chunk.id,
        deleted_doc=deleted.id,
        deleted_chunk=deleted_chunk.id,
        other_doc=foreign.id,
        other_chunk=other_chunk.id,
        orphan_chunk=orphan_chunk.id,
    )
    try:
        yield built
    finally:
        db_session.rollback()
        for workspace_id in (built.ws, built.other_ws):
            if workspace_id <= 3:
                raise RuntimeError(f"refusing to delete seed workspace {workspace_id}")
            db_session.execute(
                text("DELETE FROM audit_events WHERE workspace_id = :w"),
                {"w": workspace_id},
            )
            db_session.execute(
                text("DELETE FROM workspaces WHERE id = :w"),
                {"w": workspace_id},
            )
        db_session.commit()


def _session(workspace_id: int) -> dict:
    return {
        "workspace_id": workspace_id,
        "user_id": None,
        "email": "synthetic@example.com",
    }


def _extra_document(corpus: Corpus, role: str) -> tuple[int, int]:
    document = _add_document(corpus.db, corpus.ws, corpus.token, role, deleted=False)
    chunk = _add_chunk(corpus.db, corpus.ws, document, corpus.token, role, corpus.embedding)
    corpus.db.commit()
    return document.id, chunk.id


def test_pgvector_sql_excludes_soft_deleted_documents() -> None:
    """The vector query must drop soft-deleted documents before LIMIT."""
    session = MagicMock()
    executed: list[str] = []

    def capture(statement, params=None):  # noqa: ANN001
        executed.append(str(statement))
        return MagicMock(fetchall=MagicMock(return_value=[]))

    session.execute.side_effect = capture
    with patch("app.services.retrieval.get_settings") as settings:
        settings.return_value.use_pgvector_index = True
        RetrievalService(session).search(
            workspace_id=1,
            query="zephyrpolicy designated",
            query_embedding=[0.1] * _DIM,
            limit=5,
        )
    assert executed, "pgvector search did not execute SQL"
    sql = executed[0].lower()
    assert "deleted_at is null" in sql
    assert "c.workspace_id = :ws" in sql
    assert "cast(:vec as vector)" in sql
    assert ":vec::vector" not in sql


def test_keyword_search_excludes_deleted_and_keeps_live(corpus: Corpus) -> None:
    service = RetrievalService(corpus.db)
    own = service._keyword_search(corpus.ws, corpus.query, 10, None)
    assert _retrieval_problems(corpus, own, orphan=True) == []
    foreign = service._keyword_search(corpus.other_ws, corpus.query, 10, None)
    assert _document_ids(foreign) == {corpus.other_doc}


def test_semantic_pgvector_excludes_deleted_and_keeps_live(corpus: Corpus) -> None:
    service = RetrievalService(corpus.db)
    results = service._semantic_search_pgvector(corpus.ws, corpus.embedding, 10, 0.0, None)
    assert _retrieval_problems(corpus, results, orphan=True) == []


def test_semantic_fallback_excludes_deleted_and_keeps_live(corpus: Corpus) -> None:
    service = RetrievalService(corpus.db)
    results = service._semantic_search_fallback(corpus.ws, corpus.embedding, 10, 0.0, None)
    assert _retrieval_problems(corpus, results, orphan=True) == []


def test_search_rerank_citations_exclude_deleted(
    corpus: Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_pgvector(monkeypatch, True)
    results = RetrievalService(corpus.db).search(
        corpus.ws,
        corpus.query,
        limit=10,
        query_embedding=corpus.embedding,
    )
    assert _retrieval_problems(corpus, results, orphan=True) == []


def test_search_fallback_rerank_citations_exclude_deleted(
    corpus: Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_pgvector(monkeypatch, False)
    results = RetrievalService(corpus.db).search(
        corpus.ws,
        corpus.query,
        limit=10,
        query_embedding=corpus.embedding,
    )
    assert _retrieval_problems(corpus, results, orphan=True) == []


def test_batch_search_excludes_deleted(corpus: Corpus, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_pgvector(monkeypatch, True)
    batches = RetrievalService(corpus.db).batch_search(
        corpus.ws,
        [(corpus.query, corpus.embedding)],
        limit=10,
    )
    assert len(batches) == 1
    assert _retrieval_problems(corpus, batches[0], orphan=True) == []


def test_document_scope_still_drops_deleted_ids(corpus: Corpus) -> None:
    """An explicit document allow-list does not resurrect a soft-deleted id."""
    results = RetrievalService(corpus.db)._keyword_search(
        corpus.ws,
        corpus.query,
        10,
        frozenset({corpus.live_doc, corpus.deleted_doc}),
    )
    assert _retrieval_problems(corpus, results, orphan=False) == []


def test_retrieval_cache_does_not_serve_deleted_document(corpus: Corpus) -> None:
    version = get_corpus_version(corpus.db, corpus.ws)
    stale_hash = question_cache_hash(f"stale {corpus.token}")
    retrieval_cache_set(
        corpus.db,
        corpus.ws,
        stale_hash,
        version,
        [
            {
                "id": corpus.deleted_chunk,
                "text": "deleted evidence",
                "metadata": {"document_id": corpus.deleted_doc, "filename": "deleted.txt"},
                "score": 0.99,
            },
            {
                "id": corpus.live_chunk,
                "text": "live evidence",
                "metadata": {"document_id": corpus.live_doc, "filename": "live.txt"},
                "score": 0.4,
            },
        ],
    )
    assert retrieval_cache_get(corpus.db, corpus.ws, stale_hash) is None

    live_hash = question_cache_hash(f"live {corpus.token}")
    retrieval_cache_set(
        corpus.db,
        corpus.ws,
        live_hash,
        version,
        [
            {
                "id": corpus.live_chunk,
                "text": "live evidence",
                "metadata": {"document_id": corpus.live_doc, "filename": "live.txt"},
                "score": 0.9,
            }
        ],
    )
    kept = retrieval_cache_get(corpus.db, corpus.ws, live_hash)
    assert kept is not None
    assert [row["id"] for row in kept] == [corpus.live_chunk]


def test_answer_cache_does_not_serve_deleted_citation(corpus: Corpus) -> None:
    question_hash = question_cache_hash(f"answer {corpus.token}")
    deleted_fp = evidence_fingerprint_hash([corpus.deleted_chunk])
    answer_cache_set(
        corpus.db,
        corpus.ws,
        question_hash,
        "balanced",
        deleted_fp,
        "We follow the archived policy.",
        [
            {
                "chunk_id": corpus.deleted_chunk,
                "document_id": corpus.deleted_doc,
                "snippet": "deleted evidence",
                "filename": "deleted.txt",
            }
        ],
        80,
    )
    assert answer_cache_get(corpus.db, corpus.ws, question_hash, "balanced", deleted_fp) is None

    live_hash = question_cache_hash(f"answer-live {corpus.token}")
    live_fp = evidence_fingerprint_hash([corpus.live_chunk])
    answer_cache_set(
        corpus.db,
        corpus.ws,
        live_hash,
        "balanced",
        live_fp,
        "We follow the current policy.",
        [
            {
                "chunk_id": corpus.live_chunk,
                "document_id": corpus.live_doc,
                "snippet": "live evidence",
                "filename": "live.txt",
            }
        ],
        90,
    )
    kept = answer_cache_get(corpus.db, corpus.ws, live_hash, "balanced", live_fp)
    assert kept is not None
    assert kept["text"] == "We follow the current policy."
    assert kept["citations"][0]["document_id"] == corpus.live_doc


def test_soft_delete_bumps_corpus_and_drops_cached_citations(corpus: Corpus) -> None:
    document_id, chunk_id = _extra_document(corpus, "removable")
    version = get_corpus_version(corpus.db, corpus.ws)
    other_version = get_corpus_version(corpus.db, corpus.other_ws)
    question_hash = question_cache_hash(f"remove {corpus.token}")
    fingerprint = evidence_fingerprint_hash([chunk_id])
    retrieval_cache_set(
        corpus.db,
        corpus.ws,
        question_hash,
        version,
        [
            {
                "id": chunk_id,
                "text": "removable evidence",
                "metadata": {"document_id": document_id, "filename": "removable.txt"},
                "score": 0.95,
            }
        ],
    )
    answer_cache_set(
        corpus.db,
        corpus.ws,
        question_hash,
        "balanced",
        fingerprint,
        "Citation of a document that is about to be archived.",
        [{"chunk_id": chunk_id, "document_id": document_id, "snippet": "removable"}],
        70,
    )
    other_hash = question_cache_hash(f"other {corpus.token}")
    other_fp = evidence_fingerprint_hash([corpus.other_chunk])
    answer_cache_set(
        corpus.db,
        corpus.other_ws,
        other_hash,
        "balanced",
        other_fp,
        "Other tenant answer.",
        [{"chunk_id": corpus.other_chunk, "document_id": corpus.other_doc, "snippet": "other"}],
        70,
    )

    delete_document(document_id, corpus.ws, session=_session(corpus.ws), db=corpus.db)

    assert get_corpus_version(corpus.db, corpus.ws) != version
    assert get_corpus_version(corpus.db, corpus.other_ws) == other_version
    assert retrieval_cache_get(corpus.db, corpus.ws, question_hash) is None
    assert answer_cache_get(corpus.db, corpus.ws, question_hash, "balanced", fingerprint) is None
    kept_other = answer_cache_get(corpus.db, corpus.other_ws, other_hash, "balanced", other_fp)
    assert kept_other is not None
    assert kept_other["text"] == "Other tenant answer."

    results = RetrievalService(corpus.db)._keyword_search(corpus.ws, corpus.query, 10, None)
    documents = _document_ids(results)
    assert document_id not in documents
    assert corpus.live_doc in documents
    assert corpus.deleted_doc not in documents


def test_bulk_delete_excludes_documents_and_bumps_once(corpus: Corpus) -> None:
    first_doc, first_chunk = _extra_document(corpus, "bulk-a")
    second_doc, second_chunk = _extra_document(corpus, "bulk-b")
    version = get_corpus_version(corpus.db, corpus.ws)
    bulk_delete_documents(
        BulkDeleteBody(ids=[first_doc, second_doc]),
        corpus.ws,
        session=_session(corpus.ws),
        db=corpus.db,
    )
    assert get_corpus_version(corpus.db, corpus.ws) != version
    results = RetrievalService(corpus.db)._keyword_search(corpus.ws, corpus.query, 10, None)
    chunks = {row.get("id") for row in results}
    assert first_chunk not in chunks
    assert second_chunk not in chunks
    assert corpus.live_chunk in chunks


def test_restore_makes_document_retrievable_again(corpus: Corpus) -> None:
    document_id, chunk_id = _extra_document(corpus, "restored")
    delete_document(document_id, corpus.ws, session=_session(corpus.ws), db=corpus.db)
    hidden = RetrievalService(corpus.db)._keyword_search(corpus.ws, corpus.query, 10, None)
    assert chunk_id not in {row.get("id") for row in hidden}
    assert corpus.live_chunk in {row.get("id") for row in hidden}

    restore_document(document_id, corpus.ws, session=_session(corpus.ws), db=corpus.db)
    shown = RetrievalService(corpus.db)._keyword_search(corpus.ws, corpus.query, 10, None)
    assert chunk_id in {row.get("id") for row in shown}
    assert corpus.live_chunk in {row.get("id") for row in shown}


def test_evidence_search_excludes_deleted_document(corpus: Corpus) -> None:
    live = EvidenceItem(
        workspace_id=corpus.ws,
        document_id=corpus.live_doc,
        title=f"live evidence {corpus.token}",
        source_type="document",
    )
    deleted = EvidenceItem(
        workspace_id=corpus.ws,
        document_id=corpus.deleted_doc,
        title=f"deleted evidence {corpus.token}",
        source_type="document",
    )
    manual = EvidenceItem(
        workspace_id=corpus.ws,
        title=f"manual evidence {corpus.token}",
        source_type="manual",
    )
    corpus.db.add_all([live, deleted, manual])
    corpus.db.commit()
    found = evidence_search_service.search(corpus.db, corpus.ws, title_query=corpus.token, limit=20)
    titles = {item["title"] for item in found["items"]}
    assert live.title in titles
    assert manual.title in titles
    assert deleted.title not in titles

    control = WorkspaceControl(workspace_id=corpus.ws, custom_name=f"ctrl {corpus.token}")
    corpus.db.add(control)
    corpus.db.flush()
    corpus.db.add(
        ControlEvidenceLink(control_id=control.id, evidence_id=deleted.id, confidence_score=0.9)
    )
    corpus.db.add(
        ControlEvidenceLink(control_id=control.id, evidence_id=live.id, confidence_score=0.8)
    )
    corpus.db.commit()
    by_control = evidence_search_service.get_by_control(corpus.db, corpus.ws, control.id)
    control_titles = {item["title"] for item in by_control}
    assert live.title in control_titles
    assert deleted.title not in control_titles


def test_citation_composer_excludes_deleted_document(corpus: Corpus) -> None:
    control = WorkspaceControl(
        workspace_id=corpus.ws, custom_name=f"cite {corpus.token}", status="verified"
    )
    corpus.db.add(control)
    corpus.db.flush()
    live = EvidenceItem(
        workspace_id=corpus.ws,
        document_id=corpus.live_doc,
        title=f"live citation {corpus.token}",
        source_type="document",
        approval_status="approved",
    )
    deleted = EvidenceItem(
        workspace_id=corpus.ws,
        document_id=corpus.deleted_doc,
        title=f"deleted citation {corpus.token}",
        source_type="document",
        approval_status="approved",
    )
    corpus.db.add_all([live, deleted])
    corpus.db.flush()
    corpus.db.add_all(
        [
            ControlEvidenceLink(
                control_id=control.id, evidence_id=live.id, confidence_score=0.9, verified=True
            ),
            ControlEvidenceLink(
                control_id=control.id,
                evidence_id=deleted.id,
                confidence_score=0.95,
                verified=True,
            ),
        ]
    )
    corpus.db.commit()
    result = citation_composer_service.compose_citations(corpus.db, corpus.ws, control.id)
    titles = {item["title"] for item in result["approved_evidence"]}
    assert live.title in titles
    assert deleted.title not in titles


def test_mapping_evidence_excludes_deleted_document(corpus: Corpus) -> None:
    control = WorkspaceControl(workspace_id=corpus.ws, custom_name=f"map {corpus.token}")
    corpus.db.add(control)
    corpus.db.flush()
    live = EvidenceItem(
        workspace_id=corpus.ws,
        document_id=corpus.live_doc,
        title=f"live map {corpus.token}",
        source_type="document",
    )
    deleted = EvidenceItem(
        workspace_id=corpus.ws,
        document_id=corpus.deleted_doc,
        title=f"deleted map {corpus.token}",
        source_type="document",
    )
    corpus.db.add_all([live, deleted])
    corpus.db.flush()
    corpus.db.add_all(
        [
            ControlEvidenceLink(control_id=control.id, evidence_id=live.id, confidence_score=0.7),
            ControlEvidenceLink(
                control_id=control.id, evidence_id=deleted.id, confidence_score=0.99
            ),
        ]
    )
    corpus.db.commit()
    rows = batch_supporting_evidence_for_workspace_controls(corpus.db, corpus.ws, [control.id])
    document_ids = {row["document_id"] for row in rows[control.id]}
    assert corpus.live_doc in document_ids
    assert corpus.deleted_doc not in document_ids


def test_citation_chunk_resolution_skips_deleted_document(corpus: Corpus) -> None:
    live_tag = Tag(
        workspace_id=corpus.ws,
        category="custom",
        key=f"live-{corpus.token}",
        label=f"Live {corpus.token}",
    )
    deleted_tag = Tag(
        workspace_id=corpus.ws,
        category="custom",
        key=f"deleted-{corpus.token}",
        label=f"Deleted {corpus.token}",
    )
    corpus.db.add_all([live_tag, deleted_tag])
    corpus.db.flush()
    corpus.db.add_all(
        [
            DocumentTag(
                workspace_id=corpus.ws,
                document_id=corpus.live_doc,
                tag_id=live_tag.id,
                source="manual",
                approved=True,
            ),
            DocumentTag(
                workspace_id=corpus.ws,
                document_id=corpus.deleted_doc,
                tag_id=deleted_tag.id,
                source="manual",
                approved=True,
            ),
        ]
    )
    corpus.db.commit()
    resolved = get_tags_by_chunks(
        ChunkTagsBody(chunk_ids=[corpus.live_chunk, corpus.deleted_chunk, corpus.orphan_chunk]),
        session=_session(corpus.ws),
        db=corpus.db,
    )
    live_labels = {tag["label"] for tag in resolved[corpus.live_chunk]}
    deleted_labels = {tag["label"] for tag in resolved[corpus.deleted_chunk]}
    assert live_tag.label in live_labels
    assert deleted_labels == set()
    assert resolved[corpus.orphan_chunk] == []
