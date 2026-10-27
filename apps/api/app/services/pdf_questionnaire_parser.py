"""PDF questionnaire parser fallback (QNR-14). Extracts text and detects questions."""

import json
import re
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


# Yes/No/N/A (and the one-letter forms). A trailing "?" is a question fragment, not an answer.
_ANSWER_WORD = re.compile(r"(?i)^(y|n|yes|no|n/?a)$")
_CHECKBOX = re.compile(r"(?i)^[\[\(]\s*[x ]\s*[\]\)]$")
_NUMBER_CELL = re.compile(r"^[\d.]+$")
# Filled-in answer columns in the table corpus are sentences, not a short tail of the question.
_FILLED_ANSWER_MIN = 20


def _looks_like_answer(cell: str) -> bool:
    """True for an answer cell, not for a fragment of the question itself.

    Yes/No/N/A, a checkbox glyph, a number-only cell (``1.1``), or a filled-in answer.
    A short tail such as ``annually?`` or ``at rest`` is part of the question.
    """
    t = cell.strip()
    if not t or "?" in t:
        return False
    if looks_like_question(t) or looks_like_section_header(t):
        return False
    if _ANSWER_WORD.fullmatch(t) or _CHECKBOX.fullmatch(t) or _NUMBER_CELL.fullmatch(t):
        return True
    return len(t) >= _FILLED_ANSWER_MIN


def _one_complete_question(line: str) -> bool:
    """The joined line is a single question, not two question cells glued together."""
    return bool(looks_like_question(line) and line.count("?") <= 1)


def _candidate_lines(row: TextRow) -> tuple[str, ...]:
    """Cells when a split is safe to read, otherwise the joined line.

    A split can drop question text. A lone 3 em gap cuts one question into two
    fragments, and an aligned 1 em gap can leave a short tail such as ``annually?``
    under the 10-character minimum, so that tail is discarded. Cells are read only
    when every non-question cell looks like an answer (Yes/No/N/A, a checkbox glyph,
    a number-only token, or a filled-in answer), or when the joined line is not
    already one complete question (two question columns on one row). Otherwise the
    joined line is read unchanged. RTL or mirrored text is not split by ``pdf_cells``
    and is this unsplit line.
    """
    if len(row.cells) <= 1:
        return (row.line,)
    questionish = [c for c in row.cells if looks_like_question(c) or looks_like_section_header(c)]
    if not questionish:
        return (row.line,)
    others = [c for c in row.cells if c not in questionish]
    answers = bool(others) and all(_looks_like_answer(c) for c in others)
    if answers or not _one_complete_question(row.line):
        return row.cells
    return (row.line,)
