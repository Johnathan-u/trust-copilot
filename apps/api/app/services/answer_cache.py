"""Answer cache.

The key is workspace, normalized question, response style, evidence fingerprint,
current corpus version, prompt version, model id, and permission-policy
fingerprint. A lookup uses the corpus version now stored for the workspace, so
a row written before a bump is not a hit. A hit whose citations name an
ineligible source returns None.
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.corpus_version import get_corpus_version
from app.services.active_sources import citations_are_stale
from app.services.prompt_builder import ANSWER_PROMPT_VERSION

logger = logging.getLogger(__name__)

# Same default ``resolve_model`` returns when the caller does not name a model.
DEFAULT_ANSWER_MODEL_ID = "gpt-4o-mini"


def _model_id(model_id: str | None) -> str:
    text_id = (model_id or "").strip()
    return text_id or DEFAULT_ANSWER_MODEL_ID


def _prompt_version(prompt_version: str | None) -> str:
    if prompt_version is None:
        return ANSWER_PROMPT_VERSION
    return prompt_version


def _cache_key(
    workspace_id: int,
    question_hash: str,
    response_style: str,
    evidence_fp: str,
    corpus_version: str,
    prompt_version: str,
    model_id: str,
    permission_fingerprint: str,
) -> str:
    import hashlib

    key = "|".join(
        (
            str(workspace_id),
            question_hash,
            response_style,
            evidence_fp,
            corpus_version,
            prompt_version,
            model_id,
            permission_fingerprint or "",
        )
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:48]


def get(
    db: Session,
    workspace_id: int,
    question_normalized_hash: str,
    response_style: str,
    evidence_fingerprint_hash: str,
    *,
    model_id: str | None = None,
    prompt_version: str | None = None,
    permission_fingerprint: str = "",
) -> dict | None:
    """Return cached answer dict (text, citations, confidence) or None.

    The corpus version is the workspace's current version, not a version the
    caller passes. A row stored under an older version is a miss.
    """
    corpus_version = get_corpus_version(db, workspace_id)
    ck = _cache_key(
        workspace_id,
        question_normalized_hash,
        response_style,
        evidence_fingerprint_hash,
        corpus_version,
        _prompt_version(prompt_version),
        _model_id(model_id),
        permission_fingerprint,
    )
    row = db.execute(
        text(
            "SELECT answer_text, citations, confidence FROM answer_cache WHERE workspace_id = :ws AND cache_key = :ck"
        ),
        {"ws": workspace_id, "ck": ck},
    ).fetchone()
    if not row:
        return None
    citations = []
    if row[1]:
        try:
            citations = json.loads(row[1])
        except Exception:
            pass
    if citations_are_stale(db, workspace_id, citations):
        return None
    return {"text": row[0] or "", "citations": citations, "confidence": row[2] or 0}


def set(
    db: Session,
    workspace_id: int,
    question_normalized_hash: str,
    response_style: str,
    evidence_fingerprint_hash: str,
    answer_text: str,
    citations: list,
    confidence: int,
    *,
    model_id: str | None = None,
    prompt_version: str | None = None,
    permission_fingerprint: str = "",
) -> None:
    """Upsert one answer cache entry under the current corpus version."""
    corpus_version = get_corpus_version(db, workspace_id)
    ck = _cache_key(
        workspace_id,
        question_normalized_hash,
        response_style,
        evidence_fingerprint_hash,
        corpus_version,
        _prompt_version(prompt_version),
        _model_id(model_id),
        permission_fingerprint,
    )
    citations_json = json.dumps(citations) if citations else "[]"
    db.execute(
        text("""
            INSERT INTO answer_cache (workspace_id, cache_key, response_style, evidence_fingerprint, answer_text, citations, confidence, created_at)
            VALUES (:ws, :ck, :style, :efp, :text, :citations, :conf, :now)
            ON CONFLICT (workspace_id, cache_key) DO UPDATE SET
                answer_text = EXCLUDED.answer_text,
                citations = EXCLUDED.citations,
                confidence = EXCLUDED.confidence,
                created_at = EXCLUDED.created_at
        """),
        {
            "ws": workspace_id,
            "ck": ck,
            "style": response_style,
            "efp": evidence_fingerprint_hash,
            "text": answer_text,
            "citations": citations_json,
            "conf": confidence,
            "now": datetime.now(timezone.utc),
        },
    )
    db.commit()


def invalidate_workspace(db: Session, workspace_id: int) -> int:
    """Delete all answer cache entries for workspace. Returns count deleted."""
    r = db.execute(text("DELETE FROM answer_cache WHERE workspace_id = :ws"), {"ws": workspace_id})
    db.commit()
    return r.rowcount if hasattr(r, "rowcount") else 0
