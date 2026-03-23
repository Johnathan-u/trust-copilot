"""Per-questionnaire document scope for answer generation (retrieval + citations).

When ``answer_evidence_document_ids_json`` is set to a non-empty JSON array on the questionnaire,
retrieval and merged evidence are restricted to chunks from those documents only.
NULL or [] means use the full workspace (current default).
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.models import Questionnaire

logger = logging.getLogger(__name__)


def retrieval_cache_scope_suffix(document_ids: frozenset[int] | None) -> str:
    """Stable suffix for retrieval_cache keys when evidence is scoped to specific documents."""
    if not document_ids:
        return ""
    payload = json.dumps(sorted(document_ids), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def parse_answer_evidence_document_ids(qnr: Questionnaire) -> frozenset[int] | None:
    """Return allowed document ids for answer generation, or None if unrestricted."""
    raw = getattr(qnr, "answer_evidence_document_ids_json", None)
    if not raw or not str(raw).strip():
        return None
    try:
        ids = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("questionnaire %s: invalid answer_evidence_document_ids_json", getattr(qnr, "id", "?"))
        return None
    if not isinstance(ids, list) or len(ids) == 0:
        return None
    out: list[int] = []
    for x in ids:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    if not out:
        return None
    q_doc = getattr(qnr, "document_id", None)
    if q_doc is not None:
        out = [i for i in out if i != int(q_doc)]
    return frozenset(out)


def document_id_from_evidence_dict(e: dict) -> int | None:
    """Best-effort document id from a retrieval/control evidence chunk dict."""
    meta = e.get("metadata")
    if isinstance(meta, dict) and meta.get("document_id") is not None:
        try:
            return int(meta["document_id"])
        except (TypeError, ValueError):
            pass
    return None


def filter_evidence_to_document_scope(
    evidence: list[dict],
    allowed_document_ids: frozenset[int] | None,
) -> list[dict]:
    """Drop chunks whose document is outside the allowed set (when scope is active)."""
    if not allowed_document_ids or not evidence:
        return evidence
    out: list[dict] = []
    for e in evidence:
        did = document_id_from_evidence_dict(e)
        if did is not None and did in allowed_document_ids:
            out.append(e)
    return out


def validate_answer_evidence_document_ids(
    db: Session,
    workspace_id: int,
    questionnaire_id: int,
    requested: list[int],
) -> list[int]:
    """Keep only document IDs that belong to the workspace and are not the questionnaire source file."""
    from app.models import Document, Questionnaire

    qnr = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id == questionnaire_id,
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_(None),
        )
        .first()
    )
    if not qnr:
        return []
    q_doc_id = getattr(qnr, "document_id", None)
    uniq = []
    seen: set[int] = set()
    for x in requested:
        try:
            i = int(x)
        except (TypeError, ValueError):
            continue
        if i in seen:
            continue
        seen.add(i)
        if q_doc_id is not None and i == q_doc_id:
            continue
        doc = (
            db.query(Document)
            .filter(
                Document.id == i,
                Document.workspace_id == workspace_id,
                Document.deleted_at.is_(None),
            )
            .first()
        )
        if doc:
            uniq.append(i)
    return uniq
