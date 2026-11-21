"""Canonical framework and subject tag keys.

``docs/product/tag-vocabulary.json`` is the reviewed contract. A checkout loads
that file. The API image copies only ``apps/api``, so it loads the packaged copy
at ``app/data/tag_vocabulary.json``. ``tests/release/test_tag_vocabulary.py``
fails if those two files, or the loaded catalog, diverge.

Subject entries are stored on tags with category ``topic``. An alias normalizes
to letters and digits and resolves to one canonical key. Two entries in the same
section cannot share a normalized token.
"""

from __future__ import annotations

import json
from pathlib import Path

_PACKAGED = Path(__file__).resolve().parent.parent / "data" / "tag_vocabulary.json"
_PAYLOAD: dict | None = None
_INDEX: dict[tuple[str, str], str] | None = None
_LABELS: dict[tuple[str, str], str] | None = None
_ENTRIES: list[dict] | None = None


def normalize_tag_token(value: str | None) -> str:
    """Compare keys, labels, and aliases without case or punctuation."""
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def vocabulary_path() -> Path:
    """Docs file in a checkout, otherwise the packaged copy."""
    try:
        docs = Path(__file__).resolve().parents[4] / "docs" / "product" / "tag-vocabulary.json"
    except IndexError:
        docs = None
    if docs is not None and docs.is_file():
        return docs
    return _PACKAGED


def load_tag_vocabulary() -> dict:
    _ensure()
    assert _PAYLOAD is not None
    return _PAYLOAD


def catalog_entries() -> list[dict]:
    """Framework rows, then subject rows stored as category ``topic``."""
    _ensure()
    assert _ENTRIES is not None
    return list(_ENTRIES)


def canonical_tag_key(category: str, key: str) -> str | None:
    """Return the catalog key for a framework or subject alias, or None."""
    if category not in ("framework", "topic"):
        return None
    token = normalize_tag_token(key)
    if not token:
        return None
    _ensure()
    assert _INDEX is not None
    return _INDEX.get((category, token))


def canonical_label(category: str, key: str) -> str | None:
    _ensure()
    assert _LABELS is not None
    return _LABELS.get((category, key))


def _ensure() -> None:
    global _PAYLOAD, _INDEX, _LABELS, _ENTRIES
    if _ENTRIES is not None:
        return
    payload = json.loads(vocabulary_path().read_text(encoding="utf-8"))
    _validate(payload)
    index: dict[tuple[str, str], str] = {}
    labels: dict[tuple[str, str], str] = {}
    entries: list[dict] = []
    _fill(entries, index, labels, "framework", payload["frameworks"])
    _fill(entries, index, labels, "topic", payload["subjects"])
    _PAYLOAD = payload
    _INDEX = index
    _LABELS = labels
    _ENTRIES = entries


def _fill(
    entries: list[dict],
    index: dict[tuple[str, str], str],
    labels: dict[tuple[str, str], str],
    category: str,
    rows: list[dict],
) -> None:
    for entry in rows:
        key = entry["key"]
        label = entry["label"]
        entries.append({"category": category, "key": key, "label": label})
        labels[(category, key)] = label
        tokens = [normalize_tag_token(key), normalize_tag_token(label)]
        tokens.extend(normalize_tag_token(alias) for alias in entry["aliases"])
        for token in tokens:
            index[(category, token)] = key


def _validate(payload: dict) -> None:
    if payload.get("version") != 1:
        raise ValueError("tag vocabulary version must be 1")
    if payload.get("subject_tag_category") != "topic":
        raise ValueError("subject tag category must be topic")
    for section in ("frameworks", "subjects"):
        rows = payload.get(section)
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"tag vocabulary section {section} is empty")
        seen: dict[str, str] = {}
        for entry in rows:
            key = str(entry["key"])
            label = str(entry["label"])
            aliases = entry["aliases"]
            if not isinstance(aliases, list):
                raise ValueError(f"{key} aliases must be a list")
            tokens = [normalize_tag_token(key), normalize_tag_token(label)]
            tokens.extend(normalize_tag_token(str(alias)) for alias in aliases)
            for token in tokens:
                if not token:
                    raise ValueError(f"empty tag token for {key}")
                previous = seen.get(token)
                if previous not in (None, key):
                    raise ValueError(f"tag alias {token!r} is shared by {previous} and {key}")
                seen[token] = key
