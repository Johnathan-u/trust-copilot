"""DOCX questionnaire parser (QNR-07, QNR-08, QNR-09)."""

import json
from pathlib import Path

from app.services.answer_type import infer_answer_type
from app.services.cell_mapping import (
    CELL_MAPPING_VERSION,
    content_hash,
    file_hash,
    questions_from_grid,
)
from app.services.question_detector import looks_like_question, looks_like_section_header
from app.services.question_normalizer import normalize_question as normalize


def parse_docx_questionnaire(path: str | Path) -> list[dict]:
    """Parse DOCX into questions from paragraphs and tables.

    Paragraphs keep a paragraph locator and have no answer cell. A table with
    question and answer headers records an explicit table cell for the answer
    and does not treat the owner column as that target. Neither form is an
    original-workbook cell round trip.
    """
    try:
        from docx import Document
    except ImportError:
        return []
    file_path = Path(path)
    try:
        data = file_path.read_bytes()
        doc = Document(file_path)
    except Exception:
        return []
    digest = file_hash(data)
    results = []
    section = None

    for i, para in enumerate(doc.paragraphs):
        text = (para.text or "").strip()
        if not text:
            continue
        if looks_like_section_header(text):
            section = text
            continue
        if looks_like_question(text):
            norm = normalize(text)
            if len(norm) < 10:
                continue
            index = i + 1
            source = {"file": str(file_path), "type": "paragraph", "index": index}
            results.append(
                _located(norm, text, section, source, digest, f"paragraph:{index}", None)
            )

    for ti, tbl in enumerate(doc.tables):
        grid = [[(cell.text or "").strip() for cell in row.cells] for row in tbl.rows]
        table_number = ti + 1

        def source_for(row: int, col: int, table: int = table_number) -> dict:
            return {
                "file": str(file_path),
                "type": "table",
                "table": table,
                "row": row,
                "col": col,
            }

        def cell_name(row: int, col: int, table: int = table_number) -> str:
            return f"T{table}R{row}C{col}"

        results.extend(
            questions_from_grid(
                grid,
                sheet=None,
                file_path=str(file_path),
                file_digest=digest,
                source_for=source_for,
                cell_name=cell_name,
                section=section,
                confidence=80,
            )
        )

    return results


def _located(norm, raw, section, source, digest, question_cell, answer_cell) -> dict:
    return {
        "text": norm,
        "section": section,
        "answer_type": infer_answer_type(raw),
        "source_location": json.dumps(source),
        "confidence": 80,
        "content_hash": content_hash(norm),
        "original_file_hash": digest,
        "sheet": None,
        "question_cell": question_cell,
        "answer_cell": answer_cell,
        "mapping_version": CELL_MAPPING_VERSION,
    }
