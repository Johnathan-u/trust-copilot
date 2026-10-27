"""TC-01-003a: PyMuPDF -> pypdf replacement, checked on the synthetic locator corpus.

Two kinds of checks:
* semantic: each corpus case's expectations (page numbers, span order, columns,
  tables, questionnaire page/section, no-text / unreadable / encrypted outcomes);
* parity: branch output vs the recorded PyMuPDF baseline
  (tests/fixtures/pdf_locator/baseline_pymupdf.json, made by
  artifacts/acceptance/TC-01-003a/record_baseline.py at f72def3). Every allowed
  difference is listed below with its reason.
Synthetic data only; no network, no model calls.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from app.services import pdf_text
from app.services.evidence_parser import parse_evidence
from app.services.pdf_questionnaire_parser import parse_pdf_questionnaire
from app.services.pdf_text import (
    PdfEncryptedError,
    PdfNoTextError,
    PdfTextError,
    PdfUnreadableError,
    extract_page_texts,
)

sys.path.insert(0, str(Path(__file__).parent))
from pdf_locator_corpus import FIXTURE_PDF, Case, corpus, write_case  # noqa: E402

API_ROOT = Path(__file__).resolve().parent.parent
BASELINE = json.loads(
    (Path(__file__).parent / "fixtures" / "pdf_locator" / "baseline_pymupdf.json").read_text()
)
CASES = corpus()
ERRORS = {"unreadable": PdfUnreadableError, "encrypted": PdfEncryptedError}

# Cases where PyMuPDF emitted each same-baseline table cell on its own line and pypdf
# joins the cells of a row with spaces. Text is otherwise identical.
ROW_JOINED = {"table_grid", "questionnaire_table_cells"}
# Baseline outcomes that become explicit errors on the branch (documented in the PR).
NEWLY_EXPLICIT = {
    # (case, parser) -> new exception; baseline returned [] silently
    ("image_only_scan", "questionnaire"): PdfNoTextError,
    ("vector_only_no_text", "questionnaire"): PdfNoTextError,
    ("whitespace_only_text", "questionnaire"): PdfNoTextError,
    ("truncated_pdf", "questionnaire"): PdfUnreadableError,
    # baseline evidence: [] -> index_service "Parse returned no content"; now the readable
    # "no text layer; OCR isn't supported" message (TC-01-003a review follow-up)
    ("image_only_scan", "evidence"): PdfNoTextError,
    ("vector_only_no_text", "evidence"): PdfNoTextError,
    ("whitespace_only_text", "evidence"): PdfNoTextError,
    # baseline: 0 pages -> [] -> index_service "Parse returned no content" (explicit)
    ("truncated_pdf", "evidence"): PdfUnreadableError,
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


@pytest.fixture(scope="module")
def paths(tmp_path_factory):
    d = tmp_path_factory.mktemp("pdf_corpus")
    return {c.name: write_case(c, d) for c in CASES}


def _ids(cases):
    return [c.name for c in cases]


TEXT_CASES = [c for c in CASES if c.outcome == "text"]


@pytest.mark.parametrize("case", TEXT_CASES, ids=_ids(TEXT_CASES))
def test_semantic_page_markers_order_and_lines(case: Case, paths):
    pages = extract_page_texts(paths[case.name])
    for pg in case.empty_pages:
        assert not pages[pg - 1].strip(), f"page {pg} should be empty"
    for pg, markers in case.page_markers.items():
        for m in markers:
            on = [i + 1 for i, t in enumerate(pages) if m in _norm(t)]
            assert on == [pg], f"{m!r} found on pages {on}, expected [{pg}]"
    for seq in case.ordered:
        page = next(_norm(t) for t in pages if all(m in _norm(t) for m in seq))
        pos = [page.index(m) for m in seq]
        assert pos == sorted(pos), f"reading order broken for {seq}"
    lines = [ln for t in pages for ln in t.splitlines()]
    for row in case.same_line:
        assert any(
            all(c in ln for c in row)
            and [ln.index(c) for c in row] == sorted(ln.index(c) for c in row)
            for ln in lines
        ), f"table row {row} not on one line"
    for m in case.own_line:
        hit = [ln for ln in lines if m in ln]
        assert hit, m
        assert not any(o in ln for ln in hit for o in case.own_line if o != m), f"{m} merged"


Q_CASES = [c for c in CASES if c.questions]


@pytest.mark.parametrize("case", Q_CASES, ids=_ids(Q_CASES))
def test_semantic_questionnaire_page_and_section(case: Case, paths):
    got = parse_pdf_questionnaire(paths[case.name])
    for sub, page, section in case.questions:
        assert any(
            sub in q["text"]
            and json.loads(q["source_location"])["page"] == page
            and q["section"] == section
            and json.loads(q["source_location"])["type"] == "pdf"
            and q["confidence"] == 70
            for q in got
        ), f"question {sub!r} (page {page}, {section}) not found in {got}"


NO_TEXT = [c for c in CASES if c.outcome == "no_text"]


@pytest.mark.parametrize("case", NO_TEXT, ids=_ids(NO_TEXT))
def test_image_only_no_text_fails_explicitly(case: Case, paths):
    path = paths[case.name]
    pages = extract_page_texts(path)
    assert pages and not any(p.strip() for p in pages)
    # Evidence and questionnaire: explicit, readable error (no silent [] / 0 questions).
    for fn in (parse_evidence, parse_pdf_questionnaire):
        with pytest.raises(PdfNoTextError, match="no text layer; OCR isn't supported"):
            fn(path)


BAD = [c for c in CASES if c.outcome in ERRORS]


@pytest.mark.parametrize("case", BAD, ids=_ids(BAD))
def test_unreadable_and_encrypted_raise_explicit_errors(case: Case, paths):
    exc = ERRORS[case.outcome]
    for fn in (extract_page_texts, parse_evidence, parse_pdf_questionnaire):
        with pytest.raises(exc):
            fn(paths[case.name])


def test_pdf_errors_are_value_errors_for_existing_handlers():
    for exc in (PdfNoTextError, PdfUnreadableError, PdfEncryptedError):
        assert issubclass(exc, PdfTextError) and issubclass(exc, ValueError)


def _run(fn, path):
    try:
        return {"ok": fn(path)}, None
    except PdfTextError as e:
        return None, e


@pytest.mark.parametrize("case", CASES, ids=_ids(CASES))
def test_evidence_parity_with_pymupdf_baseline(case: Case, paths):
    base = BASELINE[case.name]["evidence"]
    got, err = _run(parse_evidence, paths[case.name])
    key = (case.name, "evidence")
    if key in NEWLY_EXPLICIT:
        assert base == {"ok": []} and isinstance(err, NEWLY_EXPLICIT[key])
        return
    if "error" in base:
        assert err is not None, f"baseline raised {base['error']}, branch returned {got}"
        return
    assert err is None, err
    new, old = got["ok"], base["ok"]
    assert [p["page"] for p in new] == [p["page"] for p in old], "page numbers changed"
    for n, o in zip(new, old):
        if case.name in ROW_JOINED:
            # Same characters and offsets; only newline-vs-space between table cells.
            assert n["text"].replace("\n", " ") == o["text"].replace("\n", " ")
        else:
            assert n["text"] == o["text"], f"page {o['page']} text differs"


@pytest.mark.parametrize("case", CASES, ids=_ids(CASES))
def test_questionnaire_parity_with_pymupdf_baseline(case: Case, paths):
    base = BASELINE[case.name]["questionnaire"]
    got, err = _run(parse_pdf_questionnaire, paths[case.name])
    key = (case.name, "questionnaire")
    if key in NEWLY_EXPLICIT:
        assert base == {"ok": []} and isinstance(err, NEWLY_EXPLICIT[key])
        return
    if "error" in base:
        assert err is not None
        return
    assert err is None, err
    new = got["ok"]
    for q in new:
        loc = json.loads(q["source_location"])
        assert loc["file"] == str(paths[case.name])
        q["source_location"] = dict(loc, file="<path>")
    # Exact parity for every case, including questionnaire_table_cells: since TC-01-003b
    # the parser reads same-baseline table cells separately, so answer cells no longer
    # trail the question text (tests/test_pdf_table_cells.py).
    assert new == base["ok"]


def test_repo_fixture_pdf_still_parses():
    items = parse_evidence(FIXTURE_PDF)
    assert [i["page"] for i in items] == [1]
    assert "Information Security Policy" in items[0]["text"]


def test_text_pdf_with_text_but_no_questions_still_returns_empty_list(paths):
    # Unchanged: a text-bearing PDF with no question-like lines parses to [] (not an error).
    assert parse_pdf_questionnaire(paths["spans_and_offsets"]) == []


def test_no_per_request_missing_backend_path():
    # pypdf is a hard import (startup/import failure, see test_pdf_failure_surfacing.py);
    # the old per-request PdfSupportUnavailableError path is gone.
    assert not hasattr(pdf_text, "PdfSupportUnavailableError")
    assert "except ImportError" not in Path(pdf_text.__file__).read_text()


def test_parsers_do_not_import_pymupdf():
    code = (
        "import sys; sys.modules['pymupdf'] = None; sys.modules['fitz'] = None\n"
        "from app.services.evidence_parser import parse_evidence\n"
        "from app.services.pdf_questionnaire_parser import parse_pdf_questionnaire\n"
        f"items = parse_evidence({str(FIXTURE_PDF)!r})\n"
        "assert items and items[0]['page'] == 1\n"
        f"parse_pdf_questionnaire({str(FIXTURE_PDF)!r})\n"
        "assert 'pymupdf' not in [m for m in sys.modules if sys.modules[m] is not None]\n"
        "print('ok')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=API_ROOT, capture_output=True, text=True)
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr


def test_no_pymupdf_left_in_dependencies_or_code():
    deps = tomllib.loads((API_ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    names = [re.split(r"[<>=~!\[ ;]", d, maxsplit=1)[0].lower() for d in deps]
    assert "pymupdf" not in names and "fitz" not in names
    assert any(d.startswith("pypdf") and ">=" in d and "<" in d for d in deps), deps
    pattern = re.compile(r"^\s*(import|from)\s+(pymupdf|fitz)\b", re.MULTILINE)
    offenders = [
        str(p.relative_to(API_ROOT))
        for sub in ("app", "scripts")
        for p in (API_ROOT / sub).rglob("*.py")
        if pattern.search(p.read_text(encoding="utf-8", errors="replace"))
    ]
    assert offenders == []


def test_supported_upload_formats_unchanged(tmp_path):
    # parse_evidence still dispatches the same extensions; unknown ones still return [].
    (tmp_path / "a.txt").write_text("plain synthetic text")
    assert parse_evidence(tmp_path / "a.txt") == [{"text": "plain synthetic text"}]
    (tmp_path / "a.rtf").write_text("x")
    assert parse_evidence(tmp_path / "a.rtf") == []


def test_mock_doc_generator_uses_synthetic_writer(tmp_path):
    sys.path.insert(0, str(API_ROOT / "scripts"))
    try:
        import generate_mock_docs
    finally:
        sys.path.remove(str(API_ROOT / "scripts"))
    out = tmp_path / "security_policy.pdf"
    generate_mock_docs.generate_security_policy_pdf(out)
    text = " ".join(i["text"] for i in parse_evidence(out))
    assert "Information Security Policy" in text and "tested annually" in text
