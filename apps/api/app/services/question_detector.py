"""Detect question rows and section headers in XLSX (QNR-04)."""

import re
import unicodedata
from typing import Any  # noqa: F401

QUESTION_PATTERNS = [
    r"^Q\d+[\.\)]\s*",
    r"^\d+[\.\)]\s*",
    r"^(?:Does|Do|Is|Are|Has|Have|Can|Will|Should|Would|Could)\s",
    r"^(?:Describe|Provide|Explain|List|Detail|Specify|Outline|Summarize|Discuss|Define|Identify|Indicate|State|Confirm|Document|Demonstrate|Show|Verify|Validate|Address)\s",
    r"\?$",
]

# A leading "Q12.", "1." or "4.1" is a label. It does not by itself decide question vs heading.
_LEADING_LABEL = re.compile(r"^(?:Q\d+[\.\)]\s+|\d+(?:\.\d+)*[\.)]?\s+)", re.IGNORECASE)
_INTERROGATIVE = re.compile(
    r"^(?:Does|Do|Is|Are|Has|Have|Can|Will|Should|Would|Could|"
    r"How|What|When|Where|Why|Who|Which)\b",
    re.IGNORECASE,
)
_IMPERATIVE = re.compile(
    r"^(?:Describe|Provide|Explain|List|Detail|Specify|Outline|Summarize|Discuss|"
    r"Define|Identify|Indicate|State|Confirm|Document|Demonstrate|Show|Verify|"
    r"Validate|Address)\b",
    re.IGNORECASE,
)


def _has_question_mark(text: str) -> bool:
    """True for ?, ¿, ？, ؟, the Greek question mark, and the other Unicode marks."""
    return any("QUESTION MARK" in unicodedata.name(ch, "") for ch in text)


def _real_question(text: str) -> bool:
    """A question, including one that is numbered or written in capitals.

    An interrogative (Does, Is, How, and the rest) is a question. An imperative
    such as Document, List or State is a question only when it asks something:
    it has a question mark, the request ends with "." or ":", or the words
    after the number are a sentence of at least five words. "3. Document
    Control" and "List of Subprocessors" stay titles.
    """
    stripped = text.strip()
    if len(stripped) < 10:
        return False
    if _has_question_mark(stripped):
        return True
    body = _LEADING_LABEL.sub("", stripped, count=1).strip()
    if _INTERROGATIVE.match(body) or _INTERROGATIVE.match(stripped):
        if stripped.isupper() and len(stripped.split()) < 4:
            return False
        return True
    if not (_IMPERATIVE.match(body) or _IMPERATIVE.match(stripped)):
        return False
    words = body.split()
    if not (body.endswith((".", ":")) or len(words) >= 5):
        return False
    if stripped.isupper() and len(stripped.split()) < 4:
        return False
    return True


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
    if _has_question_mark(t[-50:]):
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
    # Checked before the capital and numbered-title rules so a question is not
    # consumed as the section heading for the rows that follow it.
    if _real_question(t):
        return False
    if t.isupper() and len(t) > 5:
        return True
    if re.match(r"^[\d\.]+\s+[A-Z]", t):
        return True
    # A short imperative title ("List of Subprocessors") is a heading. A request
    # that is long enough, or that ends with "." or ":", was already returned
    # above as a question.
    body = _LEADING_LABEL.sub("", t, count=1).strip()
    if _IMPERATIVE.match(body) or _IMPERATIVE.match(t):
        return True
    return False
