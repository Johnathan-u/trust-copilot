"""Answer cache: keyed by workspace + normalized question + style + evidence fingerprint."""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _cache_key(workspace_id: int, question_hash: str, response_style: str, evidence_fp: str) -> str:
    import hashlib
    key = f"{workspace_id}|{question_hash}|{response_style}|{evidence_fp}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:48]


def get(
    db: Session,
    workspace_id: int,
    question_normalized_hash: str,
    response_style: str,
    evidence_fingerprint_hash: str,
) -> dict | None:
    """Return cached answer dict (text, citations, confidence) or None."""
    ck = _cache_key(workspace_id, question_normalized_hash, response_style, evidence_fingerprint_hash)
    row = db.execute(
        text("SELECT answer_text, citations, confidence FROM answer_cache WHERE workspace_id = :ws AND cache_key = :ck"),
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
) -> None:
    """Upsert one answer cache entry."""
    ck = _cache_key(workspace_id, question_normalized_hash, response_style, evidence_fingerprint_hash)
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
