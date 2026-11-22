"""XLSX workbook and sheet walker (QNR-03)."""

import json
from pathlib import Path
from typing import Iterator

import openpyxl

from app.services.evidence_format import WorkbookCorruptError

UNREADABLE_WORKBOOK = (
    "Workbook is corrupt or unreadable. Re-export it as an .xlsx file and upload it again."
)
NO_QUESTIONS_REVIEW = (
    "No questions were detected in this workbook. Review the file or upload a corrected copy."
)


class WorkbookUnreadable(ValueError):
    """A spreadsheet that could not be opened. ``str(err)`` is safe to show."""

    def __init__(self) -> None:
        super().__init__(UNREADABLE_WORKBOOK)


def iter_sheets(path: str | Path) -> Iterator[tuple[str, list[list]]]:
    """Yield (sheet_name, rows) for each sheet.

    A file that cannot be opened, or whose every sheet fails to read, raises
    WorkbookCorruptError. The message does not include the path or the parser
    exception. A readable workbook with no rows yields nothing; that is an
    empty file, not a corrupt one.
    """
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise WorkbookCorruptError(detail=type(exc).__name__) from exc
    try:
        try:
            sheets = list(wb.worksheets)
        except Exception as exc:
            raise WorkbookCorruptError(detail=type(exc).__name__) from exc
        failed = 0
        for sheet in sheets:
            try:
                rows = [list(row) for row in sheet.iter_rows(values_only=True)]
            except Exception:
                failed += 1
                continue
            if rows:
                yield sheet.title, rows
        if sheets and failed == len(sheets):
            raise WorkbookCorruptError()
    finally:
        wb.close()


def iter_questionnaire_sheets(path: str | Path) -> Iterator[tuple[str, list[list]]]:
    """Yield (sheet_name, rows) for questionnaire parsing.

    A macro, encrypted, or legacy workbook raises UnsupportedWorkbookStructure
    before any sheet is read. That message is the one export uses. A file that
    cannot be opened, or whose every sheet fails to read, raises
    WorkbookUnreadable with a fixed message. The message does not include the
    path or the parser's own exception text. A readable workbook with no rows
    yields nothing; that is an empty questionnaire, not a corrupt file.
    """
    from app.services.xlsx_writer import reject_unsupported_workbook

    file_path = Path(path)
    reject_unsupported_workbook(file_path.read_bytes())
    try:
        workbook = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    except Exception as exc:
        raise WorkbookUnreadable() from exc
    try:
        try:
            sheets = list(workbook.worksheets)
        except Exception as exc:
            raise WorkbookUnreadable() from exc
        failed = 0
        for sheet in sheets:
            try:
                rows = [list(row) for row in sheet.iter_rows(values_only=True)]
            except Exception:
                failed += 1
                continue
            if rows:
                yield sheet.title, rows
        if sheets and failed == len(sheets):
            raise WorkbookUnreadable()
    finally:
        workbook.close()


def mark_workbook_needs_review(questionnaire) -> None:
    """A readable workbook contained no questions. Leave it for a person to review."""
    questionnaire.status = "needs_review"
    questionnaire.parse_metadata = json.dumps(
        {"count": 0, "questions": [], "review": NO_QUESTIONS_REVIEW}
    )


def get_cell_value(rows: list[list], row_idx: int, col_idx: int) -> str | int | float | None:
    """Safely get cell value."""
    if row_idx < 0 or row_idx >= len(rows):
        return None
    row = rows[row_idx]
    if col_idx < 0 or col_idx >= len(row):
        return None
    return row[col_idx]
