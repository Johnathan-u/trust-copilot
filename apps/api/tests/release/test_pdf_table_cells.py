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
import time
from io import BytesIO

import pytest
from pypdf import PdfReader

from app.services import pdf_cells
from app.services.pdf_cells import (
    CELL_GAP_EM,
    CELL_GAP_EM_LONE,
    MAX_COLUMN_CANDIDATES,
    split_rows,
)
from app.services.pdf_questionnaire_parser import parse_pdf_questionnaire
from app.services.pdf_text import extract_page_rows, extract_page_texts
from app.services.synthetic_pdf import Page, TextItem, _esc, build_pdf

from tests.pdf_locator import Case, corpus, table_row_corpus, write_case

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


def _spaced_ops(n: int, step: float) -> bytes:
    """``n`` text-show ops on one baseline, each advanced by ``step`` points."""
    piece = f"(A) Tj {step:.2f} 0 Td ".encode()
    return b"BT /F1 11 Tf 40 700 Td " + piece * n + b"ET"


def _rows_of_ops(tmp_path, n: int, step: float):
    path = tmp_path / f"ops-{n}.pdf"
    path.write_bytes(build_pdf([Page(raw=_spaced_ops(n, step))]))
    return extract_page_rows(path)[0].rows


def test_candidate_cap_leaves_the_page_unsplit(tmp_path):
    """A lone >=3 em gap still splits under the cap, and the next candidate does not."""
    under = _rows_of_ops(tmp_path, 3, 80)  # two gaps, both wide: three cells
    assert under[0].cells == ("A", "A", "A")
    # n ops produce n-1 candidate gaps. MAX+2 ops => MAX+1 candidates, over the cap.
    over = _rows_of_ops(tmp_path, MAX_COLUMN_CANDIDATES + 2, 80)
    assert len(over) == 1
    assert over[0].cells == (over[0].line,)
    assert over[0].line.count("A") == MAX_COLUMN_CANDIDATES + 2


def _tm_grid(n: int, cols: int = 8) -> bytes:
    """``n`` text-show ops, each placed with an absolute Tm (the stack stays O(1)).

    Columns are 60 pt apart, so adjacent cells are candidate gaps. A single BT of
    relative Td ops makes pypdf's text-matrix chain O(n) per op; real table pages
    position each run absolutely, which is the 32k-op case this guards.
    """
    parts = [b"BT /F1 11 Tf "]
    for i in range(n):
        x = 40 + (i % cols) * 60
        y = 800 - ((i // cols) % 40) * 18
        parts.append(f"1 0 0 1 {x:.1f} {y:.1f} Tm (A) Tj ".encode())
    parts.append(b"ET")
    return b"".join(parts)


def test_large_page_of_32k_ops_splits_within_five_seconds(tmp_path):
    """32k text ops used to take ~59s in the quadratic column scan. Cap + bisect stay under 5s."""
    n = 32_000
    path = tmp_path / "large.pdf"
    path.write_bytes(build_pdf([Page(raw=_tm_grid(n))]))
    page = PdfReader(path).pages[0]
    text = page.extract_text() or ""
    started = time.perf_counter()
    rows = split_rows(page, text)
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0, f"32k-op split took {elapsed:.2f}s"
    # 8 columns at 60 pt is well over the candidate cap, so the page stays unsplit.
    assert rows and all(r.cells == (r.line,) for r in rows)
    assert sum(r.line.count("A") for r in rows) == n


# 39 lines x 50 gaps, plus one gap on each of 3 answer rows -> 1,953 candidates.
_NEAR_CAP_NOISE_LINES = 39
_NEAR_CAP_CELLS = 51
_NEAR_CAP_ALIGNED = (
    ("Do you encrypt backups at rest?", "Yes"),
    ("Is MFA required for remote access?", "No"),
    ("Do you review vendor access yearly?", "N/A"),
)


def _run_widths(texts: list[str]) -> list[float]:
    """Advance widths of ``texts`` at ``SIZE``, each placed with its own absolute Tm."""
    parts = [f"BT /F1 {SIZE:g} Tf ".encode()]
    for i, text in enumerate(texts):
        parts.append(f"1 0 0 1 40 {700 - 20 * i:.0f} Tm (".encode() + _esc(text) + b") Tj ")
    parts.append(b"ET")
    page = PdfReader(BytesIO(build_pdf([Page(raw=b"".join(parts))]))).pages[0]
    runs = pdf_cells._page_runs(page)
    assert [run.text for run in runs] == list(texts)
    return [run.x1 - run.x0 for run in runs]


def _near_cap_page() -> tuple[bytes, list[tuple[str, ...]]]:
    """Synthetic page whose candidate count stays inside 1,900–1,999.

    Noise lines each occupy their own x band, and the gap after every run is jittered,
    so a candidate x is not within ``COLUMN_ALIGN_PT`` of another line: the bisect
    window misses. Three question rows share one answer-column x (Yes/No/N/A) and do
    split. Positions are absolute Tm, so the text-matrix chain stays O(1) per op.
    """
    gap = (CELL_GAP_EM + 0.25) * SIZE  # 1.25 em: a candidate, not a lone >=3 em cut
    jitters = (0.0, 0.3, 0.6, 0.9, 1.2)
    widths = _run_widths(["A", *(q for q, _ in _NEAR_CAP_ALIGNED)])
    a_w, q_widths = widths[0], widths[1:]
    max_pitch = a_w + gap + max(jitters)
    band = (_NEAR_CAP_CELLS - 1) * max_pitch + a_w + 8.0  # gutter keeps bands from aligning
    answer_x = 36.0
    parts = [f"BT /F1 {SIZE:g} Tf ".encode()]
    for i in range(_NEAR_CAP_NOISE_LINES):
        y = 800 - i * 16
        x = 120.0 + i * band
        for j in range(_NEAR_CAP_CELLS):
            parts.append(f"1 0 0 1 {x:.2f} {y:.1f} Tm (A) Tj ".encode())
            x += a_w + gap + jitters[(i + j) % len(jitters)]
    for k, ((question, answer), q_w) in enumerate(zip(_NEAR_CAP_ALIGNED, q_widths, strict=True)):
        y = 140 - k * 20
        q_x = answer_x - gap - q_w
        parts.append(f"1 0 0 1 {q_x:.2f} {y:.1f} Tm (".encode() + _esc(question) + b") Tj ")
        parts.append(f"1 0 0 1 {answer_x:.2f} {y:.1f} Tm (".encode() + _esc(answer) + b") Tj ")
    parts.append(b"ET")
    expected = [(" ".join(["A"] * _NEAR_CAP_CELLS),)] * _NEAR_CAP_NOISE_LINES
    expected += [(q, a) for q, a in _NEAR_CAP_ALIGNED]
    return build_pdf([Page(raw=b"".join(parts))]), expected


def _column_candidate_count(page, text: str) -> int:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    runs = pdf_cells._page_runs(page)
    owners = pdf_cells._align(lines, runs)
    assert owners is not None, "text/geometry mismatch"
    return sum(
        len(pdf_cells._candidates(ln, own, runs)) for ln, own in zip(lines, owners, strict=True)
    )


def test_near_cap_page_runs_bisect_path_within_five_seconds(tmp_path, monkeypatch):
    """Just under the 2,000 cap, bisect runs: jittered gaps miss, and the answer column splits."""
    path = tmp_path / "near-cap.pdf"
    pdf, expected = _near_cap_page()
    path.write_bytes(pdf)
    page = PdfReader(path).pages[0]
    text = page.extract_text() or ""
    count = _column_candidate_count(page, text)
    assert 1_900 <= count <= 1_999

    calls = {"n": 0}
    real = pdf_cells._other_line_aligned

    def counted(points, xs, x0, line_id):
        calls["n"] += 1
        return real(points, xs, x0, line_id)

    monkeypatch.setattr(pdf_cells, "_other_line_aligned", counted)
    started = time.perf_counter()
    rows = split_rows(page, text)
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0, f"near-cap split took {elapsed:.2f}s ({count} candidates)"
    assert [r.cells for r in rows] == expected
    # The cap returns before any alignment check, so a call per candidate means bisect ran.
    assert calls["n"] == count


def test_lone_3em_gap_inside_a_question_keeps_one_question(tmp_path):
    """A >=3 em gap cuts one question into two fragments; the parser keeps the joined question."""
    left = "Do you encrypt backups"
    path = tmp_path / "wide.pdf"
    path.write_bytes(build_pdf([Page(texts=[TextItem(60, 100, left, SIZE)])]))
    (run,) = pdf_cells._page_runs(PdfReader(path).pages[0])
    x = 60 + (run.x1 - run.x0) + (CELL_GAP_EM_LONE + 0.1) * SIZE
    path.write_bytes(
        build_pdf([Page(texts=[TextItem(60, 100, left, SIZE), TextItem(x, 100, "at rest?", SIZE)])])
    )
    assert _questions(path) == [("do you encrypt backups at rest", 1, None)]


def test_aligned_1em_gap_before_annually_keeps_full_question(tmp_path):
    """An aligned 1 em gap must not drop a short tail that is under the 10-character minimum."""
    left = "Is the backup encryption key rotated"
    path = tmp_path / "probe.pdf"
    path.write_bytes(build_pdf([Page(texts=[TextItem(60, 100, left, SIZE)])]))
    (run,) = pdf_cells._page_runs(PdfReader(path).pages[0])
    x = 60 + (run.x1 - run.x0) + (CELL_GAP_EM + 0.1) * SIZE
    path.write_bytes(
        build_pdf(
            [
                Page(
                    texts=[
                        TextItem(60, 100, left, SIZE),
                        TextItem(x, 100, "annually?", SIZE),
                        TextItem(60, 120, "Notes", SIZE),
                        TextItem(x, 120, "Extra", SIZE),
                    ]
                )
            ]
        )
    )
    assert _questions(path) == [("is the backup encryption key rotated annually", 1, None)]


def test_rtl_line_falls_back_to_unsplit_line(tmp_path):
    """Mirrored (RTL) text is not split; the question is the joined line, answer included."""
    raw = (
        b"q -1 0 0 1 500 700 cm BT /F1 11 Tf 0 0 Td (Do you encrypt backups at rest?) Tj "
        b"200 0 Td (Yes) Tj ET Q"
    )
    path = tmp_path / "rtl.pdf"
    path.write_bytes(build_pdf([Page(raw=raw)]))
    rows = extract_page_rows(path)[0].rows
    assert len(rows) == 1
    assert rows[0].cells == (rows[0].line,)
    questions = _questions(path)
    assert len(questions) == 1
    assert questions[0][0] == "do you encrypt backups at rest?yes"
    assert questions[0][1:] == (1, None)
