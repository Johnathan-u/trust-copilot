"""PDF questionnaire parser fallback (QNR-14). Extracts text and detects questions."""

import json
from pathlib import Path

from app.services.answer_type import infer_answer_type
from app.services.pdf_cells import TextRow
from app.services.pdf_text import extract_page_rows, require_text
from app.services.question_detector import looks_like_question, looks_like_section_header
from app.services.question_normalizer import normalize_question as normalize


def parse_pdf_questionnaire(path: str | Path) -> list[dict]:
    """Parse PDF into questions. Fallback for non-structured PDFs (QNR-14).

    Raises PdfNoTextError when no page has a text layer (image-only PDF; no OCR),
    so the parse job fails explicitly instead of reporting 0 questions as parsed.
    Unreadable or password-protected PDFs raise pdf_text.PdfTextError.
    """
    pages = extract_page_rows(path)
    require_text([p.text for p in pages])
    section = None
    results = []
    for i, page in enumerate(pages):
        for row in page.rows:
            for line in _candidate_lines(row):
                if looks_like_section_header(line):
                    section = line
                    continue
                if looks_like_question(line):
                    norm = normalize(line)
                    if len(norm) < 10:
                        continue
                    source = {"file": str(path), "type": "pdf", "page": i + 1}
                    results.append(
                        {
                            "text": norm,
                            "section": section,
                            "answer_type": infer_answer_type(line),
                            "source_location": json.dumps(source),
                            "confidence": 70,
                        }
                    )
    return results


def _candidate_lines(row: TextRow) -> tuple[str, ...]:
    """The row's cells when splitting found a question or section cell, else the whole line.

    Table rows split at wide column gaps (TC-01-003b) are read cell by cell, as PyMuPDF
    did, so answer cells ("Yes", "No", "N/A", a filled-in answer) no longer trail the
    question text. If no cell is question- or header-like on its own, the joined line is
    used unchanged, so a split can never lose a question the joined line would yield.
    """
    if len(row.cells) > 1 and any(
        looks_like_question(c) or looks_like_section_header(c) for c in row.cells
    ):
        return row.cells
    return (row.line,)
