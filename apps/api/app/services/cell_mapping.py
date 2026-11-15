"""Explicit per-question source and answer-cell mapping.

Each imported question keeps a hash of its normalized text, a hash of the
original file bytes, the sheet when the format has one, the question cell,
the answer cell and the mapping ruleset version. The answer cell is chosen
from a header such as Answer or Response. It is never implied by adding a
column offset, so an owner column between the question and the answer is not
the target.

CELL_MAPPING_VERSION is the ruleset that makes that choice. Rows saved before
the ruleset keep version 0, which means no explicit answer cell was stored.
Raise the constant when the header rules change; do not reuse a version for
a different rule. A new import stores the current constant. It does not
increment a row just because the question text changed: text drift is the
content hash, and file drift is the original file hash.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from app.services.answer_type import infer_answer_type
from app.services.question_detector import (
    column_role,
    looks_like_question,
    looks_like_section_header,
)
from app.services.question_normalizer import normalize_question as normalize

# Ruleset that selects an explicit answer cell. Legacy rows stay at 0.
CELL_MAPPING_VERSION = 1

SourceBuilder = Callable[[int, int], dict[str, Any]]
CellNamer = Callable[[int, int], str]


def content_hash(text: str) -> str:
    """SHA-256 of the question text that is stored on the question."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_hash(data: bytes) -> str:
    """SHA-256 of the original file bytes."""
    return hashlib.sha256(data).hexdigest()


def column_letter(index: int) -> str:
    """1-based column number to spreadsheet letters. 1 is A, 4 is D."""
    letters: list[str] = []
    number = index
    while number > 0:
        number, remainder = divmod(number - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))


def cell_ref(row: int, col: int) -> str:
    """1-based row and column as an A1 reference."""
    return f"{column_letter(col)}{row}"


def find_column_map(rows: list[list]) -> dict[str, int | None]:
    """Header columns for question, owner and answer.

    Indexes are 0-based. ``header_row`` is the row that supplied the answer
    column, or the row that supplied both a question column and an answer
    column when both are present. Missing roles are None.
    """
    found: dict[str, int | None] = {
        "header_row": None,
        "question": None,
        "owner": None,
        "answer": None,
    }
    for row_index, row in enumerate(rows[:30]):
        try:
            cells = list(row) if row is not None else []
        except (TypeError, ValueError):
            continue
        roles: dict[str, int] = {}
        for col_index, cell in enumerate(cells):
            role = column_role(cell if isinstance(cell, str) else None)
            if role and role not in roles:
                roles[role] = col_index
        if "answer" not in roles and "question" not in roles:
            continue
        if found["header_row"] is None:
            found = {
                "header_row": row_index,
                "question": roles.get("question"),
                "owner": roles.get("owner"),
                "answer": roles.get("answer"),
            }
        if "question" in roles and "answer" in roles and roles["question"] != roles["answer"]:
            return {
                "header_row": row_index,
                "question": roles["question"],
                "owner": roles.get("owner"),
                "answer": roles["answer"],
            }
    return found


def questions_from_grid(
    rows: list[list],
    *,
    sheet: str | None,
    file_path: str,
    file_digest: str,
    source_for: SourceBuilder,
    cell_name: CellNamer = cell_ref,
    section: str | None = None,
    confidence: int = 85,
) -> list[dict]:
    """Questions in one sheet or CSV grid, with explicit answer cells.

    When a question header and a different answer header are both present,
    only the question column is read. Otherwise the existing left-to-right
    scan is kept, and an answer header on that sheet still names the answer
    cell. No scan invents an answer cell by stepping one column across.
    """
    column_map = find_column_map(rows)
    question_col = column_map["question"]
    answer_col = column_map["answer"]
    explicit = (
        question_col is not None and answer_col is not None and question_col != answer_col
    )
    results: list[dict] = []
    for row_index, row in enumerate(rows):
        try:
            cells = list(row) if row is not None else []
        except (TypeError, ValueError):
            continue
        indexes: list[int] | range
        if explicit:
            indexes = [int(question_col)]
        else:
            indexes = range(len(cells))
        for col_index in indexes:
            if col_index < 0 or col_index >= len(cells):
                continue
            val = cells[col_index] if cells[col_index] is not None else ""
            if looks_like_section_header(val):
                section = str(val).strip()
                break
            if not looks_like_question(val):
                continue
            raw = str(val).strip()
            norm = normalize(raw)
            if len(norm) < 10:
                continue
            row_number = row_index + 1
            col_number = col_index + 1
            answer_cell = None
            if answer_col is not None and answer_col != col_index:
                answer_cell = cell_name(row_number, int(answer_col) + 1)
            results.append(
                {
                    "text": norm,
                    "section": section,
                    "answer_type": infer_answer_type(raw),
                    "source_location": json.dumps(source_for(row_number, col_number)),
                    "confidence": confidence,
                    "content_hash": content_hash(norm),
                    "original_file_hash": file_digest,
                    "sheet": sheet,
                    "question_cell": cell_name(row_number, col_number),
                    "answer_cell": answer_cell,
                    "mapping_version": CELL_MAPPING_VERSION,
                }
            )
            break
    return results


def annotate_question_provenance(
    questions: list[dict],
    file_bytes: bytes,
    *,
    kind: str,
) -> list[dict]:
    """Add provenance to parser rows that do not already carry an answer cell.

    PDF questions keep the parser's page locator. They have no workbook answer
    cell: a PDF import is not an original-cell round trip. Other kinds keep
    fields the parser already set.
    """
    digest = file_hash(file_bytes)
    annotated: list[dict] = []
    for question in questions:
        item = dict(question)
        text = item.get("text") or ""
        item["content_hash"] = item.get("content_hash") or content_hash(text)
        item["original_file_hash"] = item.get("original_file_hash") or digest
        version = item.get("mapping_version")
        item["mapping_version"] = CELL_MAPPING_VERSION if version is None else version
        if kind != "pdf":
            annotated.append(item)
            continue
        loc = _load_location(item.get("source_location"))
        page = loc.get("page") if isinstance(loc, dict) else None
        item["sheet"] = None
        item["question_cell"] = f"page:{page}" if page else None
        item["answer_cell"] = None
        annotated.append(item)
    return annotated


def _load_location(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}
