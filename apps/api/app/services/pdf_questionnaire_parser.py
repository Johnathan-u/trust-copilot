"""PDF questionnaire parser fallback (QNR-14). Extracts text and detects questions."""

import json
from pathlib import Path

from app.services.answer_type import infer_answer_type
from app.services.question_detector import looks_like_question, looks_like_section_header
from app.services.question_normalizer import normalize_question as normalize


def parse_pdf_questionnaire(path: str | Path) -> list[dict]:
    """Parse PDF into questions. Fallback for non-structured PDFs (QNR-14)."""
    try:
        import pymupdf
    except ImportError:
        return []

    doc = pymupdf.open(path)
    section = None
    results = []
    for i, page in enumerate(doc):
        text = page.get_text()
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if looks_like_section_header(line):
                section = line
                continue
            if looks_like_question(line):
                norm = normalize(line)
                if len(norm) < 10:
                    continue
                source = {"file": str(path), "type": "pdf", "page": i + 1}
                results.append({
                    "text": norm,
                    "section": section,
                    "answer_type": infer_answer_type(line),
                    "source_location": json.dumps(source),
                    "confidence": 70,
                })
    doc.close()
    return results
