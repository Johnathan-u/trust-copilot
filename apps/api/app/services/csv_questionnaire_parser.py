"""CSV questionnaire parser.

CSV has no sheets. Each question keeps a 1-based row and column, an A1-style
question cell and, when the header row names one, an explicit answer cell.
Upload still accepts the workbook, document and text extensions it accepted
before; this parser is what a stored .csv file is read with.
"""

import csv
from io import StringIO
from pathlib import Path

from app.services.cell_mapping import file_hash, questions_from_grid


def parse_csv_questionnaire(path: str | Path) -> list[dict]:
    """Parse a comma-separated questionnaire into questions and cell targets."""
    file_path = Path(path)
    data = file_path.read_bytes()
    text = data.decode("utf-8-sig", errors="replace")
    rows = [row for row in csv.reader(StringIO(text)) if any(cell.strip() for cell in row)]
    if not rows:
        return []

    def source_for(row: int, col: int) -> dict:
        return {"file": str(file_path), "type": "csv", "row": row, "col": col}

    return questions_from_grid(
        rows,
        sheet=None,
        file_path=str(file_path),
        file_digest=file_hash(data),
        source_for=source_for,
    )
