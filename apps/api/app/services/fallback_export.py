"""Fallback export pack when in-file placement is not possible (EXP-08)."""

import csv
from io import BytesIO, StringIO
from typing import Any

from app.services.xlsx_writer import is_formula_like


def neutralize_csv_cell(value: Any) -> str:
    """Make a CSV cell inert in spreadsheet apps (TC-13-003, OWASP CSV injection).

    CSV has no cell types, so a formula-like value ("=", "+", "-", "@", tab,
    CR, full-width variants) is prefixed with a single quote, which Excel /
    LibreOffice / Sheets treat as a literal-text marker. Other values are
    returned unchanged.
    """
    text = "" if value is None else str(value)
    if is_formula_like(text):
        return "'" + text
    return text


def create_fallback_pack_docx(
    questions: list[dict],
    question_to_answer: dict[int, str],
) -> bytes:
    """Create a simple DOCX with Question | Answer table."""
    try:
        from docx import Document
    except ImportError:
        return create_fallback_pack_csv(questions, question_to_answer)

    doc = Document()
    doc.add_heading("Questionnaire Answers (Fallback Export)", 0)
    doc.add_paragraph(
        "Direct placement into the source file was not possible. "
        "Below are all questions with their answers."
    )
    table = doc.add_table(rows=1, cols=2)
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    hdr[0].text = "Question"
    hdr[1].text = "Answer"
    for q in questions:
        qid = q.get("id")
        if qid is None:
            continue
        text = q.get("text", "")
        answer = question_to_answer.get(qid, "")
        row = table.add_row().cells
        row[0].text = str(text)
        row[1].text = str(answer)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def create_fallback_pack_csv(
    questions: list[dict],
    question_to_answer: dict[int, str],
) -> bytes:
    """Create CSV with Question, Answer columns (UTF-8 bytes).

    Both columns are neutralized: question text originates from an uploaded
    file and is as untrusted as answer text (TC-13-003).
    """
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Question", "Answer"])
    for q in questions:
        qid = q.get("id")
        if qid is None:
            continue
        text = q.get("text", "")
        answer = question_to_answer.get(qid, "")
        writer.writerow([neutralize_csv_cell(text), neutralize_csv_cell(answer)])
    return buf.getvalue().encode("utf-8")
