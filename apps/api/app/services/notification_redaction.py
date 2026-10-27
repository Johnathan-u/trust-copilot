"""Redact secrets and source or evidence content before it is stored or returned.

Notification states, log fields, and error strings go through this helper.
Recipient addresses are kept: they are the destination, and they do not match
the secret patterns.
"""

from __future__ import annotations

import re

_SECRET_PATTERNS = (
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{8,}", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE),
    re.compile(r"\bya29\.[A-Za-z0-9._\-]+"),
    re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]+\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|authorization)\b\s*[:=]\s*\S+"
    ),
)

# Source and evidence bodies are not notification copy. Drop the marked tail.
_EVIDENCE_PATTERNS = (
    re.compile(
        r"(?i)\b(?:evidence|source(?:\s+quote)?|quote_hash|chunk_id|document_version_id)\b\s*[:=].*"
    ),
)

_REDACTED = "[redacted]"


def redact_notification_text(value: object, *, limit: int = 500) -> str:
    """Return a bounded string safe to persist on a delivery row."""
    if value is None:
        return ""
    text = str(value).replace("\x00", "")
    if not text:
        return ""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    for pattern in _EVIDENCE_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    text = text.strip()
    if limit > 0 and len(text) > limit:
        text = text[:limit].rstrip() + " [truncated]"
    return text
