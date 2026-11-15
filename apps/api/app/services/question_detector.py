"""Detect question rows and section headers in XLSX (QNR-04)."""

import re
from typing import Any  # noqa: F401

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


_COLUMN_ROLES = {
    "question": "question",
    "questions": "question",
    "question text": "question",
    "inquiry": "question",
    "requirement": "question",
    "owner": "owner",
    "owners": "owner",
    "assigned to": "owner",
    "assignee": "owner",
    "responsible": "owner",
    "responsible party": "owner",
    "answer": "answer",
    "answers": "answer",
    "response": "answer",
    "responses": "answer",
    "reply": "answer",
    "vendor response": "answer",
    "vendor answer": "answer",
    "answer text": "answer",
}


def column_role(text: str | None) -> str | None:
    """Return question, owner or answer when the cell is exactly that column header."""
    if not text or not isinstance(text, str):
        return None
    label = re.sub(r"\s+", " ", text.strip().lower())
    label = re.sub(r"[:*]+$", "", label).strip()
    return _COLUMN_ROLES.get(label)


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
