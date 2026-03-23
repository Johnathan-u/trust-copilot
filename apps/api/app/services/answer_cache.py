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


def batch_get(
    db: Session,
    keys: list[tuple[int, str, str, str]],
) -> dict[str, dict | None]:
    """Batch lookup: keys are (workspace_id, question_hash, response_style, evidence_fp).
    Returns {cache_key: {text, citations, confidence} or None}."""
    if not keys:
        return {}
    cache_keys = {}
    for ws, qh, style, efp in keys:
        ck = _cache_key(ws, qh, style, efp)
        cache_keys[ck] = (ws, qh, style, efp)

    ck_list = list(cache_keys.keys())
    placeholders = ", ".join(f":ck{i}" for i in range(len(ck_list)))
    params = {f"ck{i}": ck for i, ck in enumerate(ck_list)}
    rows = db.execute(
        text(f"SELECT cache_key, answer_text, citations, confidence FROM answer_cache WHERE cache_key IN ({placeholders})"),
        params,
    ).fetchall()

    result: dict[str, dict | None] = {}
    for row in rows:
        ck = row[0]
        citations = []
        if row[2]:
            try:
                citations = json.loads(row[2])
            except Exception:
                pass
        result[ck] = {"text": row[1] or "", "citations": citations, "confidence": row[3] or 0}

    return result


def batch_set(
    db: Session,
    entries: list[tuple[int, str, str, str, str, list, int]],
) -> None:
    """Batch upsert cache entries. Each tuple: (workspace_id, q_hash, style, evidence_fp, text, citations, confidence).
    Single commit at the end."""
    if not entries:
        return
    for ws, qh, style, efp, answer_text, citations, confidence in entries:
        ck = _cache_key(ws, qh, style, efp)
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
                "ws": ws, "ck": ck, "style": style, "efp": efp,
                "text": answer_text, "citations": citations_json, "conf": confidence,
                "now": datetime.now(timezone.utc),
            },
        )


def invalidate_workspace(db: Session, workspace_id: int) -> int:
    """Delete all answer cache entries for workspace. Returns count deleted."""
    r = db.execute(text("DELETE FROM answer_cache WHERE workspace_id = :ws"), {"ws": workspace_id})
    db.commit()
    return r.rowcount if hasattr(r, "rowcount") else 0
