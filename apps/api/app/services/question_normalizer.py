"""Question normalization and complexity classification for cache keys and batching."""

import re
import hashlib

from app.services.question_classifier import classify_question

# Complexity: simple = short, single intent; complex = long or multi-part
COMPLEXITY_SIMPLE = "simple"
COMPLEXITY_COMPLEX = "complex"
MAX_SIMPLE_CHARS = 120
MULTI_PART_PATTERN = re.compile(r"\b(and|;|\.|\d+\.)\s+", re.IGNORECASE)


def normalize_question(text: str | None) -> str:
    """Canonical form for cache keys: lowercase, strip, collapse whitespace, no trailing punctuation."""
    if not text:
        return ""
    t = str(text).strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[.?;:]+\s*$", "", t)
    return t.strip()


def classify_complexity(text: str | None) -> str:
    """Return simple or complex for batching hints. Complex questions may get smaller batches."""
    norm = normalize_question(text)
    if len(norm) <= MAX_SIMPLE_CHARS and not MULTI_PART_PATTERN.search(norm):
        return COMPLEXITY_SIMPLE
    return COMPLEXITY_COMPLEX


def question_cache_hash(normalized_text: str) -> str:
    """Stable hash for normalized question (for cache keys)."""
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:32]


def evidence_fingerprint_hash(chunk_ids: list[int]) -> str:
    """Stable hash for evidence set (sorted chunk ids)."""
    key = "|".join(str(x) for x in sorted(chunk_ids))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
