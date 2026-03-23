"""Evidence rerank, deduplication, and compression for prompt token budget."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Approximate chars per token for English
CHARS_PER_TOKEN = 4
# Max tokens for evidence block in one prompt (leave room for question + instructions)
DEFAULT_EVIDENCE_TOKEN_BUDGET = 2500
# Max snippet length per chunk after trim
MAX_CHUNK_CHARS = 600


def deduplicate_by_chunk_id(evidence: list[dict]) -> list[dict]:
    """Keep first occurrence of each chunk id; preserve order."""
    seen: set[int] = set()
    out: list[dict] = []
    for e in evidence:
        cid = e.get("id")
        if cid is not None and cid not in seen:
            seen.add(cid)
            out.append(e)
    return out


def rerank_by_score(evidence: list[dict]) -> list[dict]:
    """Sort by score descending; already often sorted from retrieval."""
    return sorted(evidence, key=lambda x: float(x.get("score") or 0), reverse=True)


def compress_to_token_budget(
    evidence: list[dict],
    token_budget: int = DEFAULT_EVIDENCE_TOKEN_BUDGET,
    max_chunk_chars: int = MAX_CHUNK_CHARS,
) -> list[dict]:
    """Trim each chunk text and drop lowest-scoring until within token_budget."""
    char_budget = token_budget * CHARS_PER_TOKEN
    # First trim each chunk
    trimmed: list[dict] = []
    for e in evidence:
        d = dict(e)
        text = (d.get("text") or "").strip()
        if len(text) > max_chunk_chars:
            d["text"] = text[:max_chunk_chars] + "..."
        trimmed.append(d)
    # Sort by score desc so we keep best first
    trimmed = rerank_by_score(trimmed)
    total = 0
    out: list[dict] = []
    for e in trimmed:
        text = e.get("text") or ""
        total += len(text) // CHARS_PER_TOKEN + 1
        if total > token_budget:
            break
        out.append(e)
    return out


def process_evidence(
    evidence: list[dict],
    token_budget: int = DEFAULT_EVIDENCE_TOKEN_BUDGET,
) -> list[dict]:
    """Rerank, deduplicate, then compress to fit token budget. Returns list of chunk dicts."""
    if not evidence:
        return []
    deduped = deduplicate_by_chunk_id(evidence)
    reranked = rerank_by_score(deduped)
    return compress_to_token_budget(reranked, token_budget=token_budget)
