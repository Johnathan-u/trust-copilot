"""TC-08-004: retrieval and caches stay on eligible sources for one caller.

The same question in two workspaces must not share citations or cache rows.
A corpus bump makes both the retrieval cache and the answer cache miss.
Keyword and semantic search drop soft-deleted, not-indexed, and superseded
chunks. A caller whose permission policy cannot read a document does not
receive that document, even when it is in their workspace.

Fixtures are synthetic. No customer document and no credential material.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes.documents import delete_document, restore_document
from app.core.corpus_version import bump_corpus_version, get_corpus_version
from app.models import Chunk, CustomRole, Document, Workspace
from app.services.answer_cache import get as answer_cache_get
from app.services.answer_cache import set as answer_cache_set
from app.services.embedding_service import EMBEDDING_DIM
from app.services.question_normalizer import evidence_fingerprint_hash, question_cache_hash
from app.services.retrieval import RetrievalService
from app.services.retrieval_cache import get as retrieval_cache_get
from app.services.retrieval_cache import set as retrieval_cache_set

_DIM = EMBEDDING_DIM


class _RetrievalSettings:
    def __init__(self, pgvector: bool) -> None:
        self.use_pgvector_index = pgvector
        self.retrieval_max_threads = 1


def _embedding() -> list[float]:
    vector = [0.01] * _DIM
    vector[0] = 1.0
    return vector


def _use_pgvector(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    monkeypatch.setattr(
        "app.services.retrieval.get_settings",
        lambda: _RetrievalSettings(enabled),
    )


def _sync_sequences(db: Session) -> None:
    for table in ("workspaces", "documents", "chunks", "custom_roles", "audit_events"):
        db.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"GREATEST((SELECT COALESCE(MAX(id), 0) FROM {table}), 1))"
            )
        )


def _workspace(db: Session, token: str, label: str) -> Workspace:
    row = Workspace(name=f"tc08004-{label}-{token}", slug=f"tc08004-{label}-{token}")
    db.add(row)
    db.flush()
    return row


def _document(
    db: Session,
    workspace_id: int,
    token: str,
    role: str,
    *,
    status: str = "indexed",
    deleted: bool = False,
    storage_key: str | None = None,
) -> Document:
    document = Document(
        workspace_id=workspace_id,
        storage_key=storage_key or f"synthetic/{token}/{role}.txt",
        filename=f"{role}-{token}.txt",
        status=status,
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )
    db.add(document)
    db.flush()
    return document


def _chunk(
    db: Session,
    workspace_id: int,
    document: Document | None,
    token: str,
    role: str,
    embedding: list[float],
    *,
    source_version: str | None = None,
) -> Chunk:
    metadata: dict = {}
    if document is not None:
        metadata["document_id"] = document.id
        metadata["filename"] = document.filename
        if source_version is not None:
            metadata["source_version"] = source_version
    chunk = Chunk(
        workspace_id=workspace_id,
        document_id=document.id if document is not None else None,
        text=f"Synthetic {token} designated policy for {role}.",
        metadata_=metadata or None,
        embedding=embedding,
    )
    db.add(chunk)
    db.flush()
    return chunk


def _document_ids(results: list[dict]) -> set[int]:
    found: set[int] = set()
    for row in results:
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        document_id = meta.get("document_id")
        if type(document_id) is int:
            found.add(document_id)
    return found


def _chunk_ids(results: list[dict]) -> set[int]:
    return {row.get("id") for row in results}


def _citations(results: list[dict]) -> list[dict]:
    cited: list[dict] = []
    for row in results[:5]:
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        cited.append(
            {
                "chunk_id": row.get("id"),
                "document_id": meta.get("document_id"),
                "filename": meta.get("filename"),
                "snippet": (row.get("text") or "")[:80],
            }
        )
    return cited


def _session(workspace_id: int) -> dict:
    return {"workspace_id": workspace_id, "user_id": None, "email": "synthetic@example.com"}


def _cleanup(db: Session, workspace_ids: list[int]) -> None:
    db.rollback()
    for workspace_id in workspace_ids:
        if workspace_id <= 3:
            raise RuntimeError(f"refusing to delete seed workspace {workspace_id}")
        db.execute(text("DELETE FROM audit_events WHERE workspace_id = :w"), {"w": workspace_id})
        db.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": workspace_id})
    db.commit()


@pytest.fixture
def isolation(db_session: Session, _ensure_test_data: bool):
    if _ensure_test_data is False:
        pytest.skip("database unavailable")
    _sync_sequences(db_session)
    token = uuid.uuid4().hex[:12]
    embedding = _embedding()
    query = f"How does {token} designated control access?"
    own = _workspace(db_session, token, "a")
    other = _workspace(db_session, token, "b")
    live = _document(db_session, own.id, token, "live", storage_key=f"synthetic/{token}/live.txt")
    deleted = _document(db_session, own.id, token, "deleted", deleted=True)
    pending = _document(db_session, own.id, token, "pending", status="uploaded")
    replaced = _document(
        db_session, own.id, token, "replaced", storage_key=f"synthetic/{token}/replaced-v2.txt"
    )
    hidden = _document(db_session, own.id, token, "hidden")
    foreign = _document(db_session, other.id, token, "foreign")
    rows = {
        "live": _chunk(
            db_session,
            own.id,
            live,
            token,
            "live",
            embedding,
            source_version=live.storage_key,
        ),
        "deleted": _chunk(db_session, own.id, deleted, token, "deleted", embedding),
        "pending": _chunk(db_session, own.id, pending, token, "pending", embedding),
        "replaced": _chunk(
            db_session,
            own.id,
            replaced,
            token,
            "replaced",
            embedding,
            source_version=f"synthetic/{token}/replaced-v1.txt",
        ),
        "hidden": _chunk(db_session, own.id, hidden, token, "hidden", embedding),
        "foreign": _chunk(db_session, other.id, foreign, token, "foreign", embedding),
        "orphan": _chunk(db_session, own.id, None, token, "orphan", embedding),
    }
    db_session.commit()
    built = {
        "db": db_session,
        "token": token,
        "query": query,
        "embedding": embedding,
        "own": own.id,
        "other": other.id,
        "docs": {
            "live": live.id,
            "deleted": deleted.id,
            "pending": pending.id,
            "replaced": replaced.id,
            "hidden": hidden.id,
            "foreign": foreign.id,
        },
        "chunks": {name: row.id for name, row in rows.items()},
    }
    try:
        yield built
    finally:
        _cleanup(db_session, [built["own"], built["other"]])


def test_same_question_citations_do_not_cross_workspaces(
    isolation: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_pgvector(monkeypatch, True)
    service = RetrievalService(isolation["db"])
    own = service.search(
        isolation["own"],
        isolation["query"],
        limit=20,
        query_embedding=isolation["embedding"],
    )
    foreign = service.search(
        isolation["other"],
        isolation["query"],
        limit=20,
        query_embedding=isolation["embedding"],
    )
    own_ids = _chunk_ids(own)
    foreign_ids = _chunk_ids(foreign)
    assert isolation["chunks"]["live"] in own_ids
    assert isolation["chunks"]["foreign"] in foreign_ids
    assert own_ids.isdisjoint(foreign_ids)
    assert isolation["docs"]["foreign"] not in _document_ids(own)
    assert isolation["docs"]["live"] not in _document_ids(foreign)
    own_cited = {item["chunk_id"] for item in _citations(own)}
    foreign_cited = {item["chunk_id"] for item in _citations(foreign)}
    assert own_cited.isdisjoint(foreign_cited)
    assert isolation["chunks"]["foreign"] not in own_cited


def test_cache_rows_do_not_cross_workspaces(isolation: dict) -> None:
    question_hash = question_cache_hash(isolation["query"])
    own_version = get_corpus_version(isolation["db"], isolation["own"])
    other_version = get_corpus_version(isolation["db"], isolation["other"])
    own_fp = evidence_fingerprint_hash([isolation["chunks"]["live"]])
    other_fp = evidence_fingerprint_hash([isolation["chunks"]["foreign"]])
    retrieval_cache_set(
        isolation["db"],
        isolation["own"],
        question_hash,
        own_version,
        [
            {
                "id": isolation["chunks"]["live"],
                "text": "own evidence",
                "metadata": {"document_id": isolation["docs"]["live"]},
                "score": 0.9,
            }
        ],
    )
    retrieval_cache_set(
        isolation["db"],
        isolation["other"],
        question_hash,
        other_version,
        [
            {
                "id": isolation["chunks"]["foreign"],
                "text": "other evidence",
                "metadata": {"document_id": isolation["docs"]["foreign"]},
                "score": 0.9,
            }
        ],
    )
    answer_cache_set(
        isolation["db"],
        isolation["own"],
        question_hash,
        "balanced",
        own_fp,
        "We follow the own-workspace policy.",
        [{"chunk_id": isolation["chunks"]["live"], "document_id": isolation["docs"]["live"]}],
        80,
    )
    answer_cache_set(
        isolation["db"],
        isolation["other"],
        question_hash,
        "balanced",
        other_fp,
        "We follow the other-workspace policy.",
        [
            {
                "chunk_id": isolation["chunks"]["foreign"],
                "document_id": isolation["docs"]["foreign"],
            }
        ],
        70,
    )
    own_retrieval = retrieval_cache_get(isolation["db"], isolation["own"], question_hash)
    other_retrieval = retrieval_cache_get(isolation["db"], isolation["other"], question_hash)
    assert own_retrieval is not None and other_retrieval is not None
    assert [row["id"] for row in own_retrieval] == [isolation["chunks"]["live"]]
    assert [row["id"] for row in other_retrieval] == [isolation["chunks"]["foreign"]]
    assert (
        retrieval_cache_get(isolation["db"], isolation["other"], question_hash)[0]["id"]
        != (isolation["chunks"]["live"])
    )
    own_answer = answer_cache_get(
        isolation["db"], isolation["own"], question_hash, "balanced", own_fp
    )
    other_answer = answer_cache_get(
        isolation["db"], isolation["other"], question_hash, "balanced", other_fp
    )
    assert own_answer is not None and other_answer is not None
    assert own_answer["text"] != other_answer["text"]
    assert own_answer["citations"][0]["document_id"] == isolation["docs"]["live"]
    assert other_answer["citations"][0]["document_id"] == isolation["docs"]["foreign"]
    assert (
        answer_cache_get(isolation["db"], isolation["other"], question_hash, "balanced", own_fp)
        is None
    )


def test_corpus_bump_misses_retrieval_and_answer_caches(isolation: dict) -> None:
    question_hash = question_cache_hash(f"bump {isolation['token']}")
    own_version = get_corpus_version(isolation["db"], isolation["own"])
    other_version = get_corpus_version(isolation["db"], isolation["other"])
    fingerprint = evidence_fingerprint_hash([isolation["chunks"]["live"]])
    other_fp = evidence_fingerprint_hash([isolation["chunks"]["foreign"]])
    retrieval_cache_set(
        isolation["db"],
        isolation["own"],
        question_hash,
        own_version,
        [{"id": isolation["chunks"]["live"], "text": "own", "score": 0.9}],
    )
    retrieval_cache_set(
        isolation["db"],
        isolation["other"],
        question_hash,
        other_version,
        [{"id": isolation["chunks"]["foreign"], "text": "other", "score": 0.9}],
    )
    answer_cache_set(
        isolation["db"],
        isolation["own"],
        question_hash,
        "balanced",
        fingerprint,
        "Cached own answer.",
        [{"chunk_id": isolation["chunks"]["live"], "document_id": isolation["docs"]["live"]}],
        81,
    )
    answer_cache_set(
        isolation["db"],
        isolation["other"],
        question_hash,
        "balanced",
        other_fp,
        "Cached other answer.",
        [
            {
                "chunk_id": isolation["chunks"]["foreign"],
                "document_id": isolation["docs"]["foreign"],
            }
        ],
        71,
    )
    bump_corpus_version(isolation["db"], isolation["own"])
    assert get_corpus_version(isolation["db"], isolation["own"]) != own_version
    assert retrieval_cache_get(isolation["db"], isolation["own"], question_hash) is None
    assert (
        answer_cache_get(isolation["db"], isolation["own"], question_hash, "balanced", fingerprint)
        is None
    )
    assert retrieval_cache_get(isolation["db"], isolation["other"], question_hash) is not None
    assert (
        answer_cache_get(isolation["db"], isolation["other"], question_hash, "balanced", other_fp)
        is not None
    )
    bump_corpus_version(isolation["db"], isolation["other"])
    assert retrieval_cache_get(isolation["db"], isolation["other"], question_hash) is None
    assert (
        answer_cache_get(isolation["db"], isolation["other"], question_hash, "balanced", other_fp)
        is None
    )


def test_keyword_excludes_soft_deleted_not_indexed_and_superseded(isolation: dict) -> None:
    results = RetrievalService(isolation["db"])._keyword_search(
        isolation["own"], isolation["query"], 20, None
    )
    found = _chunk_ids(results)
    assert isolation["chunks"]["live"] in found
    assert isolation["chunks"]["orphan"] in found
    assert isolation["chunks"]["deleted"] not in found
    assert isolation["chunks"]["pending"] not in found
    assert isolation["chunks"]["replaced"] not in found
    assert isolation["chunks"]["foreign"] not in found


def test_semantic_pgvector_excludes_ineligible_sources(isolation: dict) -> None:
    results = RetrievalService(isolation["db"])._semantic_search_pgvector(
        isolation["own"], isolation["embedding"], 20, 0.0, None
    )
    found = _chunk_ids(results)
    assert isolation["chunks"]["live"] in found
    assert isolation["chunks"]["orphan"] in found
    assert isolation["chunks"]["deleted"] not in found
    assert isolation["chunks"]["pending"] not in found
    assert isolation["chunks"]["replaced"] not in found


def test_semantic_fallback_excludes_ineligible_sources(
    isolation: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_pgvector(monkeypatch, False)
    results = RetrievalService(isolation["db"]).search(
        isolation["own"],
        isolation["query"],
        limit=20,
        query_embedding=isolation["embedding"],
    )
    found = _chunk_ids(results)
    assert isolation["chunks"]["live"] in found
    assert isolation["chunks"]["pending"] not in found
    assert isolation["chunks"]["replaced"] not in found
    assert isolation["chunks"]["deleted"] not in found
    for row in results:
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        assert "source_version" not in meta
        assert "synthetic/" not in str(meta)


def test_permission_policy_hides_unreadable_document_in_workspace(
    isolation: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    try:
        from app.services.retrieval_permissions import policy_for_role
    except ImportError:
        pytest.fail("search does not apply the caller's permission policy")
    _use_pgvector(monkeypatch, True)
    service = RetrievalService(isolation["db"])
    try:
        limited = policy_for_role("reviewer", document_ids=frozenset({isolation["docs"]["live"]}))
        denied_role = CustomRole(
            workspace_id=isolation["own"],
            name=f"no-read-{isolation['token']}",
            can_edit=False,
            can_review=False,
            can_export=False,
            can_admin=False,
        )
        isolation["db"].add(denied_role)
        isolation["db"].commit()
        denied = policy_for_role(
            denied_role.name, db=isolation["db"], workspace_id=isolation["own"]
        )
        admin = policy_for_role("admin")
        limited_results = service.search(
            isolation["own"],
            isolation["query"],
            limit=20,
            query_embedding=isolation["embedding"],
            permission_policy=limited,
        )
        denied_results = service.search(
            isolation["own"],
            isolation["query"],
            limit=20,
            query_embedding=isolation["embedding"],
            permission_policy=denied,
        )
        admin_results = service.search(
            isolation["own"],
            isolation["query"],
            limit=20,
            query_embedding=isolation["embedding"],
            permission_policy=admin,
        )
    except TypeError:
        pytest.fail("search does not accept the caller's permission policy")
    limited_docs = _document_ids(limited_results)
    assert isolation["docs"]["live"] in limited_docs
    assert isolation["docs"]["hidden"] not in limited_docs
    assert denied_results == []
    admin_docs = _document_ids(admin_results)
    assert isolation["docs"]["live"] in admin_docs
    assert isolation["docs"]["hidden"] in admin_docs
    question_hash = question_cache_hash(f"policy {isolation['token']}")
    version = get_corpus_version(isolation["db"], isolation["own"])
    try:
        retrieval_cache_set(
            isolation["db"],
            isolation["own"],
            question_hash,
            version,
            [{"id": isolation["chunks"]["hidden"], "text": "hidden", "score": 0.5}],
            permission_fingerprint=limited.fingerprint(),
        )
        answer_cache_set(
            isolation["db"],
            isolation["own"],
            question_hash,
            "balanced",
            evidence_fingerprint_hash([isolation["chunks"]["live"]]),
            "Limited policy answer.",
            [{"chunk_id": isolation["chunks"]["live"], "document_id": isolation["docs"]["live"]}],
            60,
            permission_fingerprint=limited.fingerprint(),
        )
    except TypeError:
        pytest.fail("cache keys do not include the permission policy")
    assert (
        retrieval_cache_get(
            isolation["db"],
            isolation["own"],
            question_hash,
            permission_fingerprint=admin.fingerprint(),
        )
        is None
    )
    assert (
        retrieval_cache_get(
            isolation["db"],
            isolation["own"],
            question_hash,
            permission_fingerprint=limited.fingerprint(),
        )
        is not None
    )
    fingerprint = evidence_fingerprint_hash([isolation["chunks"]["live"]])
    assert (
        answer_cache_get(
            isolation["db"],
            isolation["own"],
            question_hash,
            "balanced",
            fingerprint,
            permission_fingerprint=admin.fingerprint(),
        )
        is None
    )


def test_answer_cache_key_includes_prompt_version_and_model(isolation: dict) -> None:
    try:
        from app.services.prompt_builder import ANSWER_PROMPT_VERSION
    except ImportError:
        pytest.fail("answer cache key does not include a prompt version")
    question_hash = question_cache_hash(f"model {isolation['token']}")
    fingerprint = evidence_fingerprint_hash([isolation["chunks"]["live"]])
    citations = [
        {"chunk_id": isolation["chunks"]["live"], "document_id": isolation["docs"]["live"]}
    ]
    try:
        answer_cache_set(
            isolation["db"],
            isolation["own"],
            question_hash,
            "balanced",
            fingerprint,
            "Answer for gpt-4o.",
            citations,
            77,
            model_id="gpt-4o",
            prompt_version=ANSWER_PROMPT_VERSION,
        )
    except TypeError:
        pytest.fail("answer cache key does not include the prompt version and model id")
    assert (
        answer_cache_get(
            isolation["db"],
            isolation["own"],
            question_hash,
            "balanced",
            fingerprint,
            model_id="gpt-4o",
            prompt_version=ANSWER_PROMPT_VERSION,
        )
        is not None
    )
    assert (
        answer_cache_get(
            isolation["db"],
            isolation["own"],
            question_hash,
            "balanced",
            fingerprint,
            model_id="gpt-4o-mini",
            prompt_version=ANSWER_PROMPT_VERSION,
        )
        is None
    )
    assert (
        answer_cache_get(
            isolation["db"],
            isolation["own"],
            question_hash,
            "balanced",
            fingerprint,
            model_id="gpt-4o",
            prompt_version=f"{ANSWER_PROMPT_VERSION}-next",
        )
        is None
    )


def test_replaced_source_is_a_cache_miss_without_waiting_for_empty_list(isolation: dict) -> None:
    question_hash = question_cache_hash(f"stale-source {isolation['token']}")
    version = get_corpus_version(isolation["db"], isolation["own"])
    fingerprint = evidence_fingerprint_hash([isolation["chunks"]["replaced"]])
    retrieval_cache_set(
        isolation["db"],
        isolation["own"],
        question_hash,
        version,
        [
            {
                "id": isolation["chunks"]["replaced"],
                "text": "old version",
                "metadata": {"document_id": isolation["docs"]["replaced"]},
                "score": 0.95,
            }
        ],
    )
    answer_cache_set(
        isolation["db"],
        isolation["own"],
        question_hash,
        "balanced",
        fingerprint,
        "Answer citing a replaced source.",
        [
            {
                "chunk_id": isolation["chunks"]["replaced"],
                "document_id": isolation["docs"]["replaced"],
            }
        ],
        66,
    )
    assert retrieval_cache_get(isolation["db"], isolation["own"], question_hash) is None
    assert (
        answer_cache_get(isolation["db"], isolation["own"], question_hash, "balanced", fingerprint)
        is None
    )


def test_soft_delete_tombstones_chunks_and_bumps_corpus(isolation: dict) -> None:
    version = get_corpus_version(isolation["db"], isolation["own"])
    delete_document(
        isolation["docs"]["hidden"],
        isolation["own"],
        session=_session(isolation["own"]),
        db=isolation["db"],
    )
    chunk = isolation["db"].get(Chunk, isolation["chunks"]["hidden"])
    assert chunk is not None
    assert (chunk.metadata_ or {}).get("retrieval_tombstone") == "soft_deleted"
    assert get_corpus_version(isolation["db"], isolation["own"]) != version
    hidden = RetrievalService(isolation["db"])._keyword_search(
        isolation["own"], isolation["query"], 20, None
    )
    assert isolation["chunks"]["hidden"] not in _chunk_ids(hidden)
    restore_document(
        isolation["docs"]["hidden"],
        isolation["own"],
        session=_session(isolation["own"]),
        db=isolation["db"],
    )
    restored = isolation["db"].get(Chunk, isolation["chunks"]["hidden"])
    assert restored is not None
    assert "retrieval_tombstone" not in (restored.metadata_ or {})
    shown = RetrievalService(isolation["db"])._keyword_search(
        isolation["own"], isolation["query"], 20, None
    )
    assert isolation["chunks"]["hidden"] in _chunk_ids(shown)
