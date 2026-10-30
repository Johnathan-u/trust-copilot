"""Full XLSX questionnaire parser (QNR-05, QNR-10, QNR-11, QNR-12)."""

import json
import re
from pathlib import Path

from app.services.answer_type import infer_answer_type
from app.services.question_detector import looks_like_question, looks_like_section_header
from app.services.question_normalizer import normalize_question as normalize
from app.services.xlsx_parser import get_cell_value, iter_sheets  # noqa: F401


def _looks_like_xlsx_section_header(value: str | None) -> bool:
    if not looks_like_section_header(value):
        return False
    text = value.strip()
    # Bare labels such as DOCUMENT RETENTION also match imperative question cues.
    # Only explicit question notation may override a candidate section heading.
    if "?" not in text[-50:] and not re.match(r"^Q\d+[.)]", text, re.IGNORECASE):
        return True
    # Numbering alone matches the shared question heuristic, even for section labels.
    # Check the remaining text for question cues before letting a heading win.
    without_number = re.sub(r"^(?:Q)?\d+(?:\.\d+)*(?:[.)]\s*|\s+)", "", text, flags=re.IGNORECASE)
    return not looks_like_question(without_number)


def parse_xlsx_questionnaire(path: str | Path) -> list[dict]:
    """Parse XLSX into questions with source locations and metadata."""
    results = []
    for sheet_name, rows in iter_sheets(path):
        section = None
        for ri, row in enumerate(rows):
            try:
                row_cells = list(row) if row is not None else []
            except (TypeError, ValueError):
                continue
            for ci, cell in enumerate(row_cells):
                val = cell if cell is not None else ""
                if _looks_like_xlsx_section_header(val):
                    section = str(val).strip()
                    break
                if looks_like_question(val):
                    text = str(val).strip()
                    norm = normalize(text)
                    if len(norm) < 10:
                        continue
                    source = {"file": str(path), "sheet": sheet_name, "row": ri + 1, "col": ci + 1}
                    results.append(
                        {
                            "text": norm,
                            "section": section,
                            "answer_type": infer_answer_type(text),
                            "source_location": json.dumps(source),
                            "confidence": 85,
                        }
                    )
                    break
    return results
