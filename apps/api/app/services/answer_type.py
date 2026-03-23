"""Infer answer types (QNR-11)."""

import re
from enum import Enum


class AnswerType(str, Enum):
    YES_NO = "yes_no"
    FREE_TEXT = "free_text"
    NUMERIC = "numeric"
    DATE = "date"
    EVIDENCE = "evidence"


YES_NO_PATTERNS = [
    r"\b(?:yes|no|does|do|is|are|has|have|can|will|should)\b.*\?$",
    r"^(?:Does|Do|Is|Are|Has|Have|Can|Will|Should)\s",
]
NUMERIC_PATTERNS = [r"\b(?:how many|number of|count|percentage|%\s*\))\b", r"\d+\s*%"]
DATE_PATTERNS = [r"\b(?:when|date|as of|effective)\b", r"\d{4}-\d{2}-\d{2}"]


def infer_answer_type(text: str) -> str:
    """Infer answer type from question text."""
    if not text or len(text) < 5:
        return AnswerType.FREE_TEXT.value
    t = text.lower().strip()
    for pat in YES_NO_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            return AnswerType.YES_NO.value
    for pat in NUMERIC_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            return AnswerType.NUMERIC.value
    for pat in DATE_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            return AnswerType.DATE.value
    if "evidence" in t or "document" in t or "provide" in t:
        return AnswerType.EVIDENCE.value
    return AnswerType.FREE_TEXT.value
