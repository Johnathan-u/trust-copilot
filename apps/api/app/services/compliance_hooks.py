"""Compliance mapping hooks: keyword matching, control suggestion, and mapping timing.

Provides heuristic question->control mapping and optional perf timing for the
generate-mappings pipeline. LLM re-rank is handled by mapping_llm_rerank module.
"""

import logging
import os
import re
import time
import threading
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mapping timing (dev/perf instrumentation — gated behind env flag)
# ---------------------------------------------------------------------------

_TIMING_ENABLED = os.getenv("MAPPING_TIMING", "0").lower() in ("1", "true", "yes")
_timing_lock = threading.Lock()
_timing_data: dict[str, float] = {
    "heuristic_ms": 0.0,
    "rerank_ms": 0.0,
    "wc_lookup_ms": 0.0,
    "rows_fc_hits": 0,
}


def mapping_timing_enabled() -> bool:
    return _TIMING_ENABLED


def reset_mapping_timing() -> None:
    with _timing_lock:
        _timing_data.update({
            "heuristic_ms": 0.0,
            "rerank_ms": 0.0,
            "wc_lookup_ms": 0.0,
            "rows_fc_hits": 0,
        })


def get_mapping_timing_snapshot() -> dict[str, float]:
    with _timing_lock:
        return dict(_timing_data)


def record_mapping_timing(key: str, value: float) -> None:
    with _timing_lock:
        if key in _timing_data:
            _timing_data[key] = _timing_data[key] + value


# ---------------------------------------------------------------------------
# Keyword matching for explainability
# ---------------------------------------------------------------------------

_COMMON_SECURITY_KEYWORDS = {
    "access", "control", "encrypt", "encryption", "audit", "log", "monitor",
    "incident", "response", "backup", "firewall", "mfa", "authentication",
    "authorization", "vulnerability", "patch", "compliance", "policy",
    "training", "awareness", "risk", "assessment", "recovery", "disaster",
    "continuity", "network", "segmentation", "role", "privilege", "rbac",
    "siem", "alert", "notification", "breach", "phi", "pii", "hipaa",
    "soc", "iso", "nist", "fedramp",
}


def match_keywords_for_mapping_row(
    question_text: str,
    workspace_control: Any | None = None,
    framework_control: Any | None = None,
    framework_name: str | None = None,
) -> list[str]:
    """Return keywords that overlap between the question and the control/framework context."""
    q_words = set(re.findall(r"\b\w{3,}\b", (question_text or "").lower()))
    context_words: set[str] = set()

    if workspace_control:
        title = getattr(workspace_control, "title", "") or ""
        desc = getattr(workspace_control, "description", "") or ""
        context_words.update(re.findall(r"\b\w{3,}\b", title.lower()))
        context_words.update(re.findall(r"\b\w{3,}\b", desc.lower()))

    if framework_control:
        fc_title = getattr(framework_control, "title", "") or ""
        fc_ref = getattr(framework_control, "reference_id", "") or ""
        context_words.update(re.findall(r"\b\w{3,}\b", fc_title.lower()))
        context_words.update(re.findall(r"\b\w{3,}\b", fc_ref.lower()))

    if framework_name:
        context_words.update(re.findall(r"\b\w{3,}\b", framework_name.lower()))

    overlap = q_words & context_words & _COMMON_SECURITY_KEYWORDS
    if not overlap:
        overlap = q_words & context_words
        overlap = {w for w in overlap if len(w) >= 4}

    return sorted(overlap)[:10]


# ---------------------------------------------------------------------------
# question_to_controls: heuristic control suggestion
# ---------------------------------------------------------------------------

def question_to_controls(
    question: str,
    workspace_id: int,
    db: Session,
) -> tuple[list[int], float]:
    """Suggest workspace control IDs for a question using keyword heuristics.

    Returns (control_ids, confidence). Confidence is 0.0-1.0.
    """
    from app.models import WorkspaceControl, FrameworkControl

    q_words = set(re.findall(r"\b\w{3,}\b", (question or "").lower()))
    if not q_words:
        return [], 0.0

    wcs = db.query(WorkspaceControl).filter(
        WorkspaceControl.workspace_id == workspace_id
    ).all()

    if not wcs:
        return [], 0.0

    scored: list[tuple[int, float]] = []
    for wc in wcs:
        title_words = set(re.findall(r"\b\w{3,}\b", (wc.title or "").lower()))
        desc_words = set(re.findall(r"\b\w{3,}\b", (wc.description or "").lower()))
        control_words = title_words | desc_words

        if wc.framework_control_id:
            fc = db.query(FrameworkControl).filter(
                FrameworkControl.id == wc.framework_control_id
            ).first()
            if fc:
                control_words.update(re.findall(r"\b\w{3,}\b", (fc.title or "").lower()))

        overlap = q_words & control_words
        meaningful = overlap & _COMMON_SECURITY_KEYWORDS
        if meaningful:
            score = min(1.0, len(meaningful) * 0.25)
            scored.append((wc.id, score))
        elif len(overlap) >= 2:
            score = min(0.5, len(overlap) * 0.1)
            scored.append((wc.id, score))

    if not scored:
        return [], 0.0

    scored.sort(key=lambda x: x[1], reverse=True)
    best_score = scored[0][1]
    ids = [cid for cid, s in scored if s >= best_score * 0.7][:5]
    return ids, round(best_score, 2)


def maybe_rerank_framework_controls_with_llm(
    db: Session,
    workspace_id: int,
    question_text: str,
    candidate_control_ids: list[int],
    **kwargs: Any,
) -> list[int]:
    """Optional LLM re-rank of candidate controls. Falls back to input order on failure."""
    try:
        from app.services.mapping_llm_rerank import rerank_controls
        return rerank_controls(db, workspace_id, question_text, candidate_control_ids, **kwargs)
    except Exception:
        logger.debug("LLM rerank failed, returning original order", exc_info=True)
        return candidate_control_ids
