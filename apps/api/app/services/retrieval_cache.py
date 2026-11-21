"""Retrieval cache: workspace, question, corpus version, scope, and permission policy."""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.corpus_version import get_corpus_version
from app.services.active_sources import retrieval_rows_are_stale

logger = logging.getLogger(__name__)


def _cache_key(
    workspace_id: int,
    question_hash: str,
    corpus_version: str,
    scope_suffix: str = "",
    permission_fingerprint: str = "",
) -> str:
    import hashlib

    key = (
        f"{workspace_id}|{question_hash}|{corpus_version}|"
        f"{scope_suffix or 'all'}|{permission_fingerprint or ''}"
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:48]


def get(
    db: Session,
    workspace_id: int,
    question_normalized_hash: str,
    scope_suffix: str = "",
    permission_fingerprint: str = "",
) -> list[dict] | None:
    """Return cached retrieval rows when the corpus version still matches, else None.

    A stored version that is not the current version is a miss. Rows that cite
    an ineligible source are a miss even when the version still matches.
    """
    current_version = get_corpus_version(db, workspace_id)
    ck = _cache_key(
        workspace_id,
        question_normalized_hash,
        current_version,
        scope_suffix,
        permission_fingerprint,
    )
    row = db.execute(
        text(
            "SELECT result_json, corpus_version FROM retrieval_cache WHERE workspace_id = :ws AND cache_key = :ck"
        ),
        {"ws": workspace_id, "ck": ck},
    ).fetchone()
    if not row:
        return None
    if row[1] != current_version:
        return None
    try:
        parsed = json.loads(row[0])
    except Exception:
        return None
    if not isinstance(parsed, list):
        return None
    # A row written before the document was archived can still match the current
    # corpus version. Do not serve it; the caller searches again.
    if retrieval_rows_are_stale(db, workspace_id, parsed):
        return None
    return parsed


def set(
    db: Session,
    workspace_id: int,
    question_normalized_hash: str,
    corpus_version: str,
    result: list[dict],
    scope_suffix: str = "",
    permission_fingerprint: str = "",
) -> None:
    """Store retrieval result for this workspace, question, version, and policy."""
    ck = _cache_key(
        workspace_id,
        question_normalized_hash,
        corpus_version,
        scope_suffix,
        permission_fingerprint,
    )
    result_json = json.dumps(result)
    db.execute(
        text("""
            INSERT INTO retrieval_cache (workspace_id, cache_key, corpus_version, result_json, created_at)
            VALUES (:ws, :ck, :ver, :json, :now)
            ON CONFLICT (workspace_id, cache_key) DO UPDATE SET
                corpus_version = EXCLUDED.corpus_version,
                result_json = EXCLUDED.result_json,
                created_at = EXCLUDED.created_at
        """),
        {
            "ws": workspace_id,
            "ck": ck,
            "ver": corpus_version,
            "json": result_json,
            "now": datetime.now(timezone.utc),
        },
    )
    db.commit()


def invalidate_after_document_visibility_change(db: Session, workspace_id: int) -> None:
    """Bump the corpus version and drop this workspace's retrieval and answer caches.

    Call after a document is soft-deleted or restored. The retrieval cache key
    includes the corpus version. The answer cache does not, so it is cleared too.
    """
    from app.core.corpus_version import bump_corpus_version
    from app.services.answer_cache import invalidate_workspace as invalidate_answers

    bump_corpus_version(db, workspace_id)
    invalidate_workspace(db, workspace_id)
    invalidate_answers(db, workspace_id)


def invalidate_workspace(db: Session, workspace_id: int) -> int:
    """Delete all retrieval cache entries for workspace (e.g. after corpus version bump). Returns count deleted."""
    r = db.execute(
        text("DELETE FROM retrieval_cache WHERE workspace_id = :ws"), {"ws": workspace_id}
    )
    db.commit()
    return r.rowcount if hasattr(r, "rowcount") else 0
