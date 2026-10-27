"""TC-01-003b: same-line table cells in PDF questionnaires, split by x-position.

Checks the expected questions and cell splits of the same-line table-row corpus
(tests/pdf_locator: table_row_corpus), that evidence text is unchanged, the
gap thresholds, and the fall-back to unsplit lines. Synthetic data only; no network,
no model calls.
"""

from __future__ import annotations

import dataclasses
import json
import re
import sys
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.services import pdf_cells
from app.services.pdf_cells import CELL_GAP_EM, CELL_GAP_EM_LONE, split_rows
from app.services.pdf_questionnaire_parser import parse_pdf_questionnaire
from app.services.pdf_text import extract_page_rows, extract_page_texts
from app.services.synthetic_pdf import Page, TextItem, build_pdf

sys.path.insert(0, str(Path(__file__).parent))
from pdf_locator import Case, corpus, table_row_corpus, write_case  # noqa: E402

TABLE_CASES = table_row_corpus()
TEXT_CASES = [c for c in corpus() if c.outcome == "text"]
SIZE = 11.0


def _ids(cases):
    return [c.name for c in cases]


@pytest.fixture(scope="module")
def paths(tmp_path_factory):
    d = tmp_path_factory.mktemp("pdf_table_rows")
    return {c.name: write_case(c, d) for c in TABLE_CASES + TEXT_CASES}


def _questions(path):
    return [
        (q["text"], json.loads(q["source_location"])["page"], q["section"])
        for q in parse_pdf_questionnaire(path)
    ]


def _split(path):
    return [r.cells for p in extract_page_rows(path) for r in p.rows if len(r.cells) > 1]


@pytest.mark.parametrize("case", TABLE_CASES, ids=_ids(TABLE_CASES))
def test_table_rows_expected_questions(case: Case, paths):
    assert _questions(paths[case.name]) == case.exact_questions


@pytest.mark.parametrize("case", TABLE_CASES, ids=_ids(TABLE_CASES))
def test_table_rows_expected_cell_splits(case: Case, paths):
    assert _split(paths[case.name]) == [tuple(r) for r in case.split_rows]


@pytest.mark.parametrize("case", TABLE_CASES, ids=_ids(TABLE_CASES))
def test_table_rows_answer_cells_not_in_question_text(case: Case, paths):
    for text, _, _ in _questions(paths[case.name]):
        assert not re.search(r"\b(yes|no|n/a)$", text), text
        assert "[x]" not in text and "[ ]" not in text, text


@pytest.mark.parametrize("case", TABLE_CASES, ids=_ids(TABLE_CASES))
def test_table_rows_page_markers(case: Case, paths):
    pages = extract_page_texts(paths[case.name])
    for pg, markers in case.page_markers.items():
        for m in markers:
            assert [i + 1 for i, t in enumerate(pages) if m in t] == [pg], m
    for seq in case.ordered:
        page = " ".join(pages[0].split())
        pos = [page.index(m) for m in seq]
        assert pos == sorted(pos), seq


ALL = TABLE_CASES + TEXT_CASES


@pytest.mark.parametrize("case", ALL, ids=_ids(ALL))
def test_rows_never_change_text(case: Case, paths):
    """Evidence text is byte-identical; rows are its non-empty lines; cells keep every
    character of the line, in order."""
    path = paths[case.name]
    pages = extract_page_rows(path)
    assert [p.text for p in pages] == extract_page_texts(path)
    for p in pages:
        assert [r.line for r in p.rows] == [ln.strip() for ln in p.text.splitlines() if ln.strip()]
        for r in p.rows:
            assert all(c and c == c.strip() for c in r.cells)
            assert re.sub(r"\s", "", "".join(r.cells)) == re.sub(r"\s", "", r.line)


@pytest.mark.parametrize(
    "name",
    [
        "two_column",
        "two_column_stream_right_first",
        "spans_and_offsets",
        "questionnaire_two_pages",
        "questionnaire_numbered",
        "multipage_blank_page",
    ],
)
def test_regression_corpus_lines_are_not_split(name, paths):
    assert _split(paths[name]) == []


def test_table_grid_rows_split_into_their_cells(paths):
    assert _split(paths["table_grid"]) == [
        ("CTRL-ID", "CTRL-OWNER", "CTRL-FREQ"),
        *[(f"T{r}C1-CC{r}.1", f"T{r}C2-Owner{r}", f"T{r}C3-Quarterly") for r in range(1, 4)],
    ]


# --- thresholds ---------------------------------------------------------------------

Q = "Do you encrypt backups at rest?"


def _q_width(tmp_path) -> float:
    p = tmp_path / "probe.pdf"
    p.write_bytes(build_pdf([Page(texts=[TextItem(60, 100, Q, SIZE)])]))
    (run,) = pdf_cells._page_runs(PdfReader(p).pages[0])
    return run.x1 - run.x0


def _rows_for(tmp_path, items) -> list[tuple[str, ...]]:
    p = tmp_path / "t.pdf"
    p.write_bytes(build_pdf([Page(texts=items)]))
    return [r.cells for r in extract_page_rows(p)[0].rows]


@pytest.mark.parametrize(
    "gap_em, aligned, split",
    [
        (CELL_GAP_EM - 0.1, True, False),  # narrow gap: never a cell boundary
        (CELL_GAP_EM + 0.1, True, True),  # column shared with another row
        (CELL_GAP_EM + 0.1, False, False),  # lone narrow-ish gap: stays joined
        (CELL_GAP_EM_LONE - 0.1, False, False),
        (CELL_GAP_EM_LONE + 0.1, False, True),  # lone but very wide
    ],
)
def test_gap_thresholds(tmp_path, gap_em, aligned, split):
    x = 60 + _q_width(tmp_path) + gap_em * SIZE
    items = [TextItem(60, 100, Q, SIZE), TextItem(x, 100, "Yes", SIZE)]
    # second row: its answer cell either shares the column x or sits far from it
    items += [TextItem(60, 120, "Short", SIZE), TextItem(x if aligned else x + 40, 120, "No", SIZE)]
    rows = _rows_for(tmp_path, items)
    assert rows[0] == ((Q, "Yes") if split else (f"{Q} Yes",))


def test_different_baselines_are_never_cells(tmp_path):
    # superscript-like offset: same pypdf line only if within its line tolerance
    items = [TextItem(60, 100, Q, SIZE), TextItem(400, 103, "Yes", SIZE)]
    items += [TextItem(60, 120, "Short", SIZE), TextItem(400, 123, "No", SIZE)]
    for row in _rows_for(tmp_path, items):
        assert len(row) == 1


def test_rotated_text_is_never_split(tmp_path):
    raw = (
        b"q 0 1 -1 0 300 300 cm BT /F1 11 Tf 0 0 Td (Is rotated text kept whole?) Tj "
        b"300 0 Td (Yes) Tj ET Q\n"
        b"q 0 1 -1 0 320 300 cm BT /F1 11 Tf 0 0 Td (Is this one kept too?) Tj "
        b"300 0 Td (No) Tj ET Q"
    )
    p = tmp_path / "rot.pdf"
    p.write_bytes(build_pdf([Page(raw=raw)]))
    assert all(len(r.cells) == 1 for r in extract_page_rows(p)[0].rows)


# --- fall-back ------------------------------------------------------------------------


def test_geometry_failure_falls_back_to_unsplit_lines(paths, monkeypatch):
    def boom(page):
        raise RuntimeError("synthetic pypdf internals change")

    monkeypatch.setattr(pdf_cells, "_page_runs", boom)
    path = paths["questionnaire_table_cells"]
    assert _split(path) == []
    # pre-TC-01-003b output: answer cells trail the question, nothing is lost
    assert [q for q, _, _ in _questions(path)] == [
        "do you encrypt backups at rest? yes no",
        "is mfa required for remote access? yes no",
    ]


def test_text_geometry_mismatch_falls_back_to_unsplit_lines(paths, monkeypatch):
    real = pdf_cells._page_runs

    def altered(page):
        runs = real(page)
        return [*runs[:-1], dataclasses.replace(runs[-1], text=runs[-1].text + "X")]

    monkeypatch.setattr(pdf_cells, "_page_runs", altered)
    assert _split(paths["questionnaire_table_cells"]) == []


def test_split_rows_on_empty_text_page(paths):
    page = PdfReader(paths["multipage_blank_page"]).pages[1]
    assert split_rows(page, "") == []
