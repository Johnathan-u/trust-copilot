"""LLM re-ranking for mapping candidates.

Post-heuristic step: takes top-N candidate controls and optionally re-ranks
them with an LLM call for higher-quality mapping. Falls back to heuristic order on failure.
"""

import logging
import threading
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_perf_lock = threading.Lock()
_perf_data: dict[str, float | int] = {
    "rows_will_call_llm": 0,
    "candidate_sum": 0.0,
    "llm_http_calls": 0,
    "total_rerank_ms": 0.0,
}


def reset_rerank_perf_stats() -> None:
    with _perf_lock:
        _perf_data.update({
            "rows_will_call_llm": 0,
            "candidate_sum": 0.0,
            "llm_http_calls": 0,
            "total_rerank_ms": 0.0,
        })


def get_rerank_perf_snapshot() -> dict[str, float | int]:
    with _perf_lock:
        return dict(_perf_data)


def rerank_controls(
    db: Session,
    workspace_id: int,
    question_text: str,
    candidate_control_ids: list[int],
    **kwargs: Any,
) -> list[int]:
    """Re-rank controls for a question. Returns sorted control IDs.
    Currently returns input order; LLM call is optional and controlled by settings.
    """
    from app.core.config import get_settings
    settings = get_settings()
    if not settings.mapping_llm_rerank_enabled:
        return candidate_control_ids
    return candidate_control_ids
