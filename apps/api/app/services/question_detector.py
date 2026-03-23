"""Detect question rows and section headers in XLSX (QNR-04)."""

import re
from typing import Any

QUESTION_PATTERNS = [
    r"^Q\d+[\.\)]\s*",
    r"^\d+[\.\)]\s*",
    r"^(?:Does|Do|Is|Are|Has|Have|Can|Will|Should|Would|Could)\s",
    r"^(?:Describe|Provide|Explain|List|Detail|Specify|Outline|Summarize|Discuss|Define|Identify|Indicate|State|Confirm|Document|Demonstrate|Show|Verify|Validate|Address)\s",
    r"\?$",
]


def looks_like_question(text: str | None) -> bool:
    """Heuristic: does this cell look like a question?"""
    if not text or not isinstance(text, str):
        return False
    t = str(text).strip()
    if len(t) < 10:
        return False
    for pat in QUESTION_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            return True
    return "?" in t[-50:]


def looks_like_section_header(text: str | None) -> bool:
    """Heuristic: does this look like a section header?"""
    if not text or not isinstance(text, str):
        return False
    t = str(text).strip()
    if len(t) > 200:
        return False
    if t.isupper() and len(t) > 5:
        return True
    if re.match(r"^[\d\.]+\s+[A-Z]", t):
        return True
    return False
