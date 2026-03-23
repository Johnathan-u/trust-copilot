"""TEST-04: Golden tests for questionnaire parsers."""

import json
from pathlib import Path

from app.services.docx_questionnaire_parser import parse_docx_questionnaire
from app.services.xlsx_questionnaire_parser import parse_xlsx_questionnaire

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "questionnaires"


def _normalize_xlsx_for_golden(questions: list[dict]) -> list[dict]:
    """Normalize parser output for comparison (strip file path from source_location)."""
    out = []
    for q in questions:
        sl = json.loads(q["source_location"]) if isinstance(q["source_location"], str) else q["source_location"]
        out.append({
            "text": q["text"],
            "section": q.get("section"),
            "answer_type": q["answer_type"],
            "source_location": {"sheet": sl["sheet"], "row": sl["row"], "col": sl["col"]},
            "confidence": q["confidence"],
        })
    return out


def _normalize_docx_for_golden(questions: list[dict]) -> list[dict]:
    """Normalize DOCX parser output (source_location has type/paragraph or table/row/col)."""
    out = []
    for q in questions:
        sl = json.loads(q["source_location"]) if isinstance(q["source_location"], str) else q["source_location"]
        out.append({
            "text": q["text"],
            "section": q.get("section"),
            "answer_type": q["answer_type"],
            "source_location": sl,
            "confidence": q["confidence"],
        })
    return out


def test_parse_simple_soc2_xlsx_golden() -> None:
    """Parse simple SOC2-style XLSX and compare to golden output."""
    path = FIXTURES / "simple_soc2.xlsx"
    golden_path = FIXTURES / "simple_soc2.json"
    assert path.exists(), f"Fixture missing: {path}"
    assert golden_path.exists(), f"Golden missing: {golden_path}"
    questions = parse_xlsx_questionnaire(path)
    actual = _normalize_xlsx_for_golden(questions)
    expected = json.loads(golden_path.read_text())
    assert actual == expected


def test_parse_simple_soc2_docx() -> None:
    """Parse simple SOC2-style DOCX and verify questions extracted."""
    path = FIXTURES / "simple_soc2.docx"
    assert path.exists(), f"Fixture missing: {path}"
    questions = parse_docx_questionnaire(path)
    assert len(questions) >= 2
    texts = [q["text"] for q in questions]
    assert any("security policy" in t.lower() for t in texts)
    assert all("source_location" in q for q in questions)


def test_parse_iso27001_xlsx() -> None:
    """Parse ISO27001 fixture (EXP-09)."""
    path = FIXTURES / "iso27001.xlsx"
    if not path.exists():
        pytest.skip("Run scripts/generate-fixtures.py first")
    questions = parse_xlsx_questionnaire(path)
    assert len(questions) >= 1
    assert all("source_location" in q for q in questions)


def test_parse_vendor_dd_xlsx() -> None:
    """Parse vendor DD fixture (EXP-09)."""
    path = FIXTURES / "vendor_dd.xlsx"
    if not path.exists():
        pytest.skip("Run scripts/generate-fixtures.py first")
    questions = parse_xlsx_questionnaire(path)
    assert len(questions) >= 1
