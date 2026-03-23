"""XLSX workbook and sheet walker (QNR-03)."""

from pathlib import Path
from typing import Iterator

import openpyxl


def iter_sheets(path: str | Path) -> Iterator[tuple[str, list[list]]]:
    """Yield (sheet_name, rows) for each sheet. Handles corrupt/empty files (RES-01)."""
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception:
        return
    try:
        for sheet in wb.worksheets:
            try:
                rows = [list(row) for row in sheet.iter_rows(values_only=True)]
                if rows:
                    yield sheet.title, rows
            except Exception:
                continue
    finally:
        wb.close()


def get_cell_value(rows: list[list], row_idx: int, col_idx: int) -> str | int | float | None:
    """Safely get cell value."""
    if row_idx < 0 or row_idx >= len(rows):
        return None
    row = rows[row_idx]
    if col_idx < 0 or col_idx >= len(row):
        return None
    return row[col_idx]
