"""Full XLSX questionnaire parser (QNR-05, QNR-10, QNR-11, QNR-12)."""

from pathlib import Path

from app.services.cell_mapping import file_hash, questions_from_grid
from app.services.xlsx_parser import iter_sheets


def parse_xlsx_questionnaire(path: str | Path) -> list[dict]:
    """Parse XLSX into questions with source locations and answer-cell targets."""
    file_path = Path(path)
    data = file_path.read_bytes()
    digest = file_hash(data)
    results: list[dict] = []
    for sheet_name, rows in iter_sheets(file_path):

        def source_for(row: int, col: int, sheet: str = sheet_name) -> dict:
            return {"file": str(file_path), "sheet": sheet, "row": row, "col": col}

        results.extend(
            questions_from_grid(
                rows,
                sheet=sheet_name,
                file_path=str(file_path),
                file_digest=digest,
                source_for=source_for,
            )
        )
    return results
