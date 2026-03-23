"""Semantic and keyword retrieval (RET-01, RET-02, RET-03)."""

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import and_, or_, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.pipeline_logging import log_retrieval_failure, log_retrieval_start, log_retrieval_success
from app.core.metrics import RETRIEVAL_DURATION_SECONDS
from app.models import Chunk
from app.services.vector_util import embedding_to_vector_literal, validate_embedding_dimension

logger = logging.getLogger(__name__)

# Cap for semantic fallback to avoid OOM when pgvector is disabled or unavailable
FALLBACK_MAX_CHUNKS = 10_000

_STOPWORDS = frozenset(
    {"the", "and", "for", "are", "does", "is", "has", "can", "how", "who", "what",
     "when", "where", "which", "that", "this", "with", "from", "your", "have",
     "been", "there", "into", "than", "not", "but", "was", "were", "did", "do"}
)


def _extract_terms(query: str) -> list[str]:
    """Extract significant terms for keyword search (length >= 3, not stopwords)."""
    words = re.findall(r"\b\w{3,}\b", query.lower())
    return [w for w in words if w not in _STOPWORDS][:15]


def _cosine_sim(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class RetrievalService:
    """Hybrid retrieval: semantic + keyword, merge and rerank."""

    def __init__(self, db: Session):
        self._db = db

    @staticmethod
    def _normalize_document_scope(document_ids: list[int] | None) -> frozenset[int] | None:
        if not document_ids:
            return None
        try:
            s = frozenset(int(x) for x in document_ids)
        except (TypeError, ValueError):
            return None
        return s if len(s) > 0 else None

    def search(
        self,
        workspace_id: int,
        query: str,
        limit: int = 10,
        query_embedding: list[float] | None = None,
        min_score: float = 0.0,
        question_id: int | None = None,
        document_ids: list[int] | None = None,
    ) -> list[dict]:
        """Return relevant chunks with hybrid semantic + keyword search."""
        started = time.monotonic()
        log_retrieval_start(workspace_id)
        doc_scope = self._normalize_document_scope(document_ids)
        try:
            if query_embedding and len(query_embedding) > 0:
                validate_embedding_dimension(query_embedding, context="retrieval_query")
                results = self._semantic_search(workspace_id, query_embedding, limit, min_score, doc_scope)
            else:
                results = []
            keyword_results = self._keyword_search(workspace_id, query, limit * 2, doc_scope)
            out = self._merge_rerank(results, keyword_results, limit)
            out = self._apply_mapping_boosts(workspace_id, query, out, question_id)
            if doc_scope:
                out = self._filter_chunks_by_document_scope(out, doc_scope)
            duration_ms = (time.monotonic() - started) * 1000
            log_retrieval_success(workspace_id, len(out), duration_ms)
            RETRIEVAL_DURATION_SECONDS.observe(duration_ms / 1000)
            return out
        except Exception as e:
            duration_ms = (time.monotonic() - started) * 1000
            log_retrieval_failure(workspace_id, str(e), duration_ms)
            RETRIEVAL_DURATION_SECONDS.observe(duration_ms / 1000)
            raise

    def batch_search(
        self,
        workspace_id: int,
        queries: list[tuple[str, list[float] | None]],
        limit: int = 10,
        document_ids: list[int] | None = None,
    ) -> list[list[dict]]:
        """Batch search: parallel semantic queries for all questions at once."""
        doc_scope = self._normalize_document_scope(document_ids)
        results: list[list[dict]] = [[] for _ in queries]

        def _do_one(idx: int) -> None:
            q_text, q_emb = queries[idx]
            if q_emb and len(q_emb) > 0:
                validate_embedding_dimension(q_emb, context=f"batch_retrieval_{idx}")
                sem = self._semantic_search(workspace_id, q_emb, limit, 0.0, doc_scope)
            else:
                sem = []
            kw = self._keyword_search(workspace_id, q_text, limit * 2, doc_scope)
            merged = self._merge_rerank(sem, kw, limit)
            if doc_scope:
                merged = self._filter_chunks_by_document_scope(merged, doc_scope)
            results[idx] = merged

        max_threads = min(8, len(queries))
        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            list(executor.map(_do_one, range(len(queries))))

        return results

    @staticmethod
    def _metadata_with_document_id(metadata: dict | None, document_id: int | None) -> dict | None:
        if document_id is None:
            return metadata
        md = dict(metadata) if isinstance(metadata, dict) else {}
        md.setdefault("document_id", document_id)
        return md

    def _filter_chunks_by_document_scope(self, chunks: list[dict], doc_scope: frozenset[int]) -> list[dict]:
        """Keep only chunks whose resolved document_id is in doc_scope."""
        out: list[dict] = []
        for r in chunks:
            meta = r.get("metadata")
            did = None
            if isinstance(meta, dict) and meta.get("document_id") is not None:
                try:
                    did = int(meta["document_id"])
                except (TypeError, ValueError):
                    did = None
            if did is not None and did in doc_scope:
                out.append(r)
        return out

    def _keyword_search(
        self, workspace_id: int, query: str, limit: int, doc_scope: frozenset[int] | None
    ) -> list[dict]:
        """Keyword search (RET-02). Matches chunks; prioritizes rarer terms."""
        if not query.strip():
            return []
        terms = _extract_terms(query)
        if not terms:
            return []
        base = Chunk.workspace_id == workspace_id
        if doc_scope:
            base = and_(base, Chunk.document_id.in_(list(doc_scope)))
        all_cond = or_(*[Chunk.text.ilike(f"%{t}%") for t in terms])
        seen_ids = set()
        out = []
        rare = [t for t in terms if t in ("designated", "ciso", "training", "audit", "assess")]
        if rare:
            rows = (
                self._db.query(Chunk)
                .filter(base, or_(*[Chunk.text.ilike(f"%{t}%") for t in rare]))
                .limit(limit)
                .all()
            )
            for r in rows:
                if r.id not in seen_ids:
                    seen_ids.add(r.id)
                    md = self._metadata_with_document_id(
                        r.metadata_ if isinstance(r.metadata_, dict) else None, r.document_id
                    )
                    out.append({"id": r.id, "text": r.text, "metadata": md, "score": 0.85})
        rows = (
            self._db.query(Chunk)
            .filter(base, all_cond)
            .limit(limit)
            .all()
        )
        for r in rows:
            if r.id not in seen_ids:
                seen_ids.add(r.id)
                md = self._metadata_with_document_id(
                    r.metadata_ if isinstance(r.metadata_, dict) else None, r.document_id
                )
                out.append({"id": r.id, "text": r.text, "metadata": md, "score": 0.8})
        return out[:limit]

    def _semantic_search(
        self,
        workspace_id: int,
        embedding: list[float],
        limit: int,
        min_score: float = 0.0,
        doc_scope: frozenset[int] | None = None,
    ) -> list[dict]:
        """Semantic search (RET-01). Uses pgvector index when enabled, else in-memory cosine."""
        settings = get_settings()
        if settings.use_pgvector_index and embedding:
            return self._semantic_search_pgvector(workspace_id, embedding, limit, min_score, doc_scope)
        return self._semantic_search_fallback(workspace_id, embedding, limit, min_score, doc_scope)

    def _semantic_search_pgvector(
        self,
        workspace_id: int,
        embedding: list[float],
        limit: int,
        min_score: float,
        doc_scope: frozenset[int] | None,
    ) -> list[dict]:
        """Use pgvector index: ORDER BY embedding <=> query LIMIT. Cosine distance -> 1-distance for score."""
        vec_str = embedding_to_vector_literal(embedding)
        scope_sql = ""
        params: dict = {"vec": vec_str, "ws": workspace_id, "lim": limit * 2}
        if doc_scope:
            ids = sorted(doc_scope)
            placeholders = ", ".join(f":d{i}" for i in range(len(ids)))
            scope_sql = f" AND document_id IN ({placeholders})"
            for i, did in enumerate(ids):
                params[f"d{i}"] = did
        rows = self._db.execute(
            text(f"""
                SELECT id, text, metadata_, document_id,
                       1 - (embedding <=> CAST(:vec AS vector)) AS score
                FROM chunks
                WHERE workspace_id = :ws AND embedding IS NOT NULL
                {scope_sql}
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :lim
            """),
            params,
        ).fetchall()
        scored = []
        for r in rows:
            sc = float(r[4])
            if sc < min_score:
                continue
            md = r[2]
            md = self._metadata_with_document_id(md if isinstance(md, dict) else None, r[3])
            scored.append({"id": r[0], "text": r[1], "metadata": md, "score": sc})
        return scored[:limit]

    def _semantic_search_fallback(
        self,
        workspace_id: int,
        embedding: list[float],
        limit: int,
        min_score: float,
        doc_scope: frozenset[int] | None,
    ) -> list[dict]:
        """Fallback: load chunks (capped) and compute cosine in Python. Use pgvector in production."""
        logger.warning(
            "retrieval using semantic fallback (pgvector disabled or unavailable) workspace_id=%s limit=%s",
            workspace_id, limit,
        )
        q = self._db.query(Chunk).filter(Chunk.workspace_id == workspace_id, Chunk.embedding.isnot(None))
        if doc_scope:
            q = q.filter(Chunk.document_id.in_(list(doc_scope)))
        rows = q.limit(FALLBACK_MAX_CHUNKS).all()
        if len(rows) >= FALLBACK_MAX_CHUNKS:
            logger.warning(
                "retrieval fallback hit cap workspace_id=%s cap=%s",
                workspace_id, FALLBACK_MAX_CHUNKS,
            )
        scored = [
            {
                "id": r.id,
                "text": r.text,
                "metadata": self._metadata_with_document_id(
                    r.metadata_ if isinstance(r.metadata_, dict) else None, r.document_id
                ),
                "score": _cosine_sim(r.embedding or [], embedding),
            }
            for r in rows
        ]
        scored = [r for r in scored if r["score"] >= min_score]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    def _merge_rerank(
        self, semantic: list[dict], keyword: list[dict], limit: int
    ) -> list[dict]:
        """Merge and rerank (RET-03) - interleave semantic and keyword for better coverage."""
        seen = set()
        out = []
        sem_idx, kw_idx = 0, 0
        while len(out) < limit and (sem_idx < len(semantic) or kw_idx < len(keyword)):
            if sem_idx < len(semantic):
                r = semantic[sem_idx]
                sem_idx += 1
                if r["id"] not in seen:
                    seen.add(r["id"])
                    out.append(r)
            if len(out) >= limit:
                break
            if kw_idx < len(keyword):
                r = keyword[kw_idx]
                kw_idx += 1
                if r["id"] not in seen:
                    seen.add(r["id"])
                    out.append(r)
        return out[:limit]

    def _apply_mapping_boosts(
        self, workspace_id: int, query: str, results: list[dict], question_id: int | None
    ) -> list[dict]:
        """Apply additive boosts from AI mapping governance. Safe no-op when no mappings exist."""
        if not results:
            return results
        try:
            from app.services.ai_mapping_service import compute_retrieval_adjustments
            adjustments = compute_retrieval_adjustments(
                self._db, workspace_id, query, results, question_id=question_id,
            )
            if not adjustments:
                return results
            for item in results:
                boost = adjustments.get(item.get("id"), 0.0)
                if boost > 0:
                    item["score"] = min(1.0, float(item.get("score") or 0) + boost)
            results.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
            return results
        except Exception:
            logger.debug("ai_mapping boost failed, returning unmodified results", exc_info=True)
            return results
