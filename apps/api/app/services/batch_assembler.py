"""Token-budgeted batch assembly for answer generation."""

import logging
from typing import Any

# Approximate tokens: question ~50-200 each, evidence shared ~2000-3000
CHARS_PER_TOKEN = 4
# Max tokens per completion request (model limit minus safety)
MAX_OUTPUT_TOKENS_PER_REQUEST = 4000
# Reserve for evidence block (shared)
EVIDENCE_BUDGET = 3000
# Per-question input + output estimate
TOKENS_PER_QUESTION_ESTIMATE = 400


def estimate_tokens(text: str) -> int:
    """Rough token count from character length."""
    return max(1, len((text or "").strip()) // CHARS_PER_TOKEN)


def assemble_batches(
    questions: list[Any],
    evidence_token_estimate: int = EVIDENCE_BUDGET,
    max_total_tokens: int = 12000,
) -> list[list[Any]]:
    """Pack questions into batches so that (evidence + sum(question + answer)) <= max_total_tokens.
    questions: list of objects with .text attribute.
    Returns list of batches (each batch is a list of question objects).
    """
    batches: list[list[Any]] = []
    current: list[Any] = []
    current_tokens = evidence_token_estimate
    for q in questions:
        q_tokens = estimate_tokens(getattr(q, "text", "") or "") + TOKENS_PER_QUESTION_ESTIMATE
        if current and current_tokens + q_tokens > max_total_tokens:
            batches.append(current)
            current = []
            current_tokens = evidence_token_estimate
        current.append(q)
        current_tokens += q_tokens
    if current:
        batches.append(current)
    return batches
