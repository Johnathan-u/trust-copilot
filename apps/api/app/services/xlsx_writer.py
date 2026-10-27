"""XLSX workbook writer (EXP-02, EXP-03, EXP-04)."""

import json
import logging
from copy import copy
from io import BytesIO
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.worksheet.formula import ArrayFormula, DataTableFormula

_logger = logging.getLogger(__name__)

# TC-13-003: leading characters that spreadsheet apps (Excel, LibreOffice,
# Google Sheets) may interpret as the start of a formula / DDE expression.
# Includes the full-width variants some locales/IMEs produce, and tab/CR per
# the OWASP CSV-injection guidance.
FORMULA_TRIGGER_CHARS: tuple[str, ...] = (
    "=", "+", "-", "@", "\t", "\r",
    "\uff1d", "\uff0b", "\uff0d", "\uff20",
)


def is_formula_like(value: Any) -> bool:
    """True if ``value`` is a string a spreadsheet app could treat as a formula.

    Leading spaces are ignored for detection (conservative: " =1+1" is flagged).
    """
    if not isinstance(value, str) or not value:
        return False
    if value[0] in FORMULA_TRIGGER_CHARS:
        return True
    stripped = value.lstrip(" ")
    return bool(stripped) and stripped[0] in FORMULA_TRIGGER_CHARS


def cell_has_formula(cell: Any) -> bool:
    """True if ``cell`` currently holds an original (template) formula."""
    if getattr(cell, "data_type", None) == "f":
        return True
    return isinstance(getattr(cell, "value", None), (ArrayFormula, DataTableFormula))


def write_literal_text(cell: Any, text: Any) -> None:
    """Write ``text`` into ``cell`` as a literal string, never as a formula (TC-13-003).

    openpyxl turns any str starting with "=" into a formula cell; forcing the
    data type to "s" stores it as a plain (inline) string instead. Formula-like
    values additionally get Excel's quotePrefix flag (the hidden leading
    apostrophe) so re-editing the cell in Excel keeps it literal too. The
    visible text is never altered.
    """
    value = "" if text is None else str(text)
    cell.value = value
    cell.data_type = "s"
    if is_formula_like(value):
        cell.quotePrefix = True


def create_workbook() -> openpyxl.Workbook:
    """Create new workbook."""
    return openpyxl.Workbook()


def write_answers_to_sheet(ws: openpyxl.worksheet.worksheet.Worksheet, answers: list[dict]) -> None:
    """Write answers to sheet. answers: [{row, col, text}, ...]."""
    for a in answers:
        row, col = a.get("row", 1), a.get("col", 1)
        write_literal_text(ws.cell(row=row, column=col), a.get("text", ""))


def save_workbook(wb: openpyxl.Workbook) -> bytes:
    """Save workbook to bytes."""
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def load_workbook_from_bytes(data: bytes) -> openpyxl.Workbook:
    """Load workbook from bytes (EXP-03)."""
    return openpyxl.load_workbook(BytesIO(data), data_only=False)


def _copy_cell_style(source: openpyxl.cell.cell.Cell, target: openpyxl.cell.cell.Cell) -> None:
    """Copy visual formatting from the question cell to the answer cell (EXP-04).

    TC-13-003: formats are not blindly copied.
    - If the target cell already has its own formatting (the template's answer
      column styling), it is preserved untouched.
    - number_format and protection are never copied: a question cell's number
      format (date, percent, currency, ...) has no meaning for answer text,
      and copying "locked"/"hidden" protection could hide or lock answers.
    """
    if not source.has_style or target.has_style:
        return
    target.font = copy(source.font)
    target.border = copy(source.border)
    target.fill = copy(source.fill)
    target.alignment = copy(source.alignment)


def place_answers_into_workbook(
    wb: openpyxl.Workbook,
    placements: list[dict[str, Any]],
    answer_col_offset: int = 1,
    skipped: list[dict[str, Any]] | None = None,
) -> openpyxl.Workbook:
    """Place answers into workbook cells (EXP-03, EXP-04, TC-13-003).

    placements: list of {sheet, row, col, text}.
    row, col are 1-based (question cell from source_location).
    Answer is written to (row, col + answer_col_offset) by default (next column).
    Answers are always written as literal text (never formulas). A target cell
    that already holds an original template formula is NOT overwritten; the
    placement is skipped, logged, and appended to ``skipped`` if provided.
    Question-cell formatting is copied only onto unstyled targets, and never
    number_format/protection (see _copy_cell_style).
    """
    for p in placements:
        sheet_name = p.get("sheet")
        row = p.get("row", 1)
        col = p.get("col", 1)
        text = p.get("text", "")
        if not sheet_name or sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        answer_col = col + answer_col_offset
        question_cell = ws.cell(row=row, column=col)
        answer_cell = ws.cell(row=row, column=answer_col)
        if cell_has_formula(answer_cell):
            _logger.warning(
                "EXPORT: skipped answer placement; target holds original formula sheet=%r cell=%s",
                sheet_name,
                answer_cell.coordinate,
            )
            if skipped is not None:
                skipped.append({
                    "sheet": sheet_name,
                    "cell": answer_cell.coordinate,
                    "reason": "target_has_formula",
                })
            continue
        _copy_cell_style(question_cell, answer_cell)
        write_literal_text(answer_cell, text)
    return wb


def placements_from_questions_and_answers(
    questions: list[dict],
    question_to_answer: dict[int, str],
) -> list[dict[str, Any]]:
    """Build placement list from questions with source_location and answer map.

    questions: list of {id, source_location, ...}
    question_to_answer: {question_id: answer_text}
    """
    placements = []
    for q in questions:
        qid = q.get("id")
        if qid is None:
            continue
        text = question_to_answer.get(qid, "")
        loc_raw = q.get("source_location")
        if not loc_raw:
            continue
        try:
            loc = json.loads(loc_raw) if isinstance(loc_raw, str) else loc_raw
        except (json.JSONDecodeError, TypeError):
            continue
        placements.append({
            "sheet": loc.get("sheet"),
            "row": loc.get("row", 1),
            "col": loc.get("col", 1),
            "text": text,
        })
    return placements


def create_export_from_questionnaire(
    xlsx_bytes: bytes,
    questions: list[dict],
    question_to_answer: dict[int, str],
    answer_col_offset: int = 1,
    skipped: list[dict[str, Any]] | None = None,
) -> bytes:
    """Load original XLSX, place answers, return modified XLSX bytes (EXP-03).

    Original formulas elsewhere in the workbook are preserved (loaded with
    data_only=False); answers are written as literal text (TC-13-003).
    """
    wb = load_workbook_from_bytes(xlsx_bytes)
    placements = placements_from_questions_and_answers(questions, question_to_answer)
    wb = place_answers_into_workbook(wb, placements, answer_col_offset, skipped=skipped)
    return save_workbook(wb)
