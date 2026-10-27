"""Split same-baseline table cells in pypdf text lines by x-position (TC-01-003b).

pypdf's plain ``extract_text()`` keeps content-stream order (so two-column pages read
column by column) but joins text on the same baseline into one line with single
spaces. In a table-style questionnaire the answer cells then trail the question:
``Do you encrypt backups at rest? Yes No``.

This module does not change that text. It reads the geometry of every text-show
operation on the page (start x, end x after the font's glyph widths, baseline, em
size) and maps the characters of each plain-text line back onto those operations.
A line is split into cells only where two consecutive operations on the same
baseline are separated horizontally by a wide gap:

* the gap is at least ``CELL_GAP_EM`` em, and
* the right-hand cell starts in a column that another line on the page also starts
  a cell in (within ``COLUMN_ALIGN_PT``), or the gap is at least
  ``CELL_GAP_EM_LONE`` em.

Anything that cannot be mapped exactly (form XObjects, decoding differences,
rotated or mirrored text, a pypdf internals change) leaves every line of that page
unsplit, which is the pre-TC-01-003b behaviour. Splitting never adds, drops or
reorders characters: cuts fall only between two operations, and the cells' characters
concatenated equal the line's (cells are stripped of surrounding whitespace).

Geometry comes from pypdf's layout-mode text-state machinery (private modules,
pypdf is pinned ``>=6.21.2,<7``). Any failure there is caught and logged at debug
level, and the page falls back to unsplit lines.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

CELL_GAP_EM = 1.0
CELL_GAP_EM_LONE = 3.0
COLUMN_ALIGN_PT = 1.5
SAME_BASELINE_EM = 0.2


@dataclass(frozen=True)
class TextRow:
    """One non-empty line of ``extract_text()`` output and its cells (left as stream order)."""

    line: str
    cells: tuple[str, ...]


@dataclass(frozen=True)
class _Run:
    text: str
    x0: float
    x1: float
    y: float
    em: float
    upright: bool


def _page_runs(page: Any) -> list[_Run]:
    """Every text-show operation on the page, in content-stream order."""
    from pypdf._text_extraction._layout_mode._fixed_width_page import (  # noqa: PLC0415
        recurse_to_target_op,
        set_font_operation,
    )
    from pypdf._text_extraction._layout_mode._text_state_manager import (  # noqa: PLC0415
        TextStateManager,
    )
    from pypdf.generic import ContentStream  # noqa: PLC0415

    contents = page.get_contents()
    if contents is None:
        return []
    fonts = page._layout_mode_fonts()
    ops = iter(ContentStream(contents, page.pdf, "bytes").operations)
    state = TextStateManager()
    tj_ops: list[Any] = []
    # Same top-level loop as pypdf's layout-mode text_show_operations, but keeping the
    # per-operation records (and rotated text, which is flagged instead of dropped).
    for operands, op in ops:
        if op in (b"BT", b"q"):
            _, tjs = recurse_to_target_op(ops, state, b"ET" if op == b"BT" else b"Q", fonts, False)
            tj_ops.extend(tjs)
        elif op == b"Tf":
            set_font_operation(state, fonts, operands)
        else:
            state.set_state_param(op, operands)
    runs = []
    for t in tj_ops:
        a, b, c, d = (float(v) for v in t.transform[:4])
        upright = (
            not t.rotated
            and not t.flip_vertical
            and a > 0
            and d > 0
            and abs(b) < 1e-6
            and abs(c) < 1e-6
        )
        runs.append(
            _Run(
                str(t.text),
                float(t.tx),
                float(t.displaced_tx),
                float(t.ty),
                float(t.font_height),
                upright,
            )
        )
    return runs


def _align(lines: list[str], runs: list[_Run]) -> list[list[int]] | None:
    """For each line, the run index of each non-whitespace character; None if no exact map."""
    chars = [(ch, i) for i, r in enumerate(runs) for ch in r.text if not ch.isspace()]
    pos = 0
    owners: list[list[int]] = []
    for line in lines:
        own = []
        for ch in line:
            if ch.isspace():
                continue
            if pos >= len(chars) or chars[pos][0] != ch:
                return None
            own.append(chars[pos][1])
            pos += 1
        owners.append(own)
    return owners if pos == len(chars) else None


def _candidates(line: str, own: list[int], runs: list[_Run]) -> list[tuple[int, float, float]]:
    """(cut index in line, gap in em, right-cell start x) for wide same-baseline gaps.

    The gap counts in either direction (the next operation may start left of the
    previous one, e.g. answer cells written before the question), but the two
    operations must not overlap horizontally.
    """
    out = []
    k = -1  # index into own for the previous non-whitespace char
    for idx, ch in enumerate(line):
        if ch.isspace():
            continue
        k += 1
        if k > 0 and own[k] != own[k - 1]:
            ra, rb = runs[own[k - 1]], runs[own[k]]
            em = max(ra.em, rb.em)
            if ra.upright and rb.upright and em > 0 and abs(ra.y - rb.y) <= SAME_BASELINE_EM * em:
                gap = max(rb.x0 - ra.x1, ra.x0 - rb.x1)  # either direction, no overlap
                if gap >= CELL_GAP_EM * em:
                    out.append((idx, gap / em, rb.x0))
    return out


def split_rows(page: Any, text: str) -> list[TextRow]:
    """Rows for the non-empty lines of ``text`` (the page's ``extract_text()`` output)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    plain = [TextRow(ln.strip(), (ln.strip(),)) for ln in lines]
    try:
        runs = _page_runs(page)
        owners = _align(lines, runs)
    except Exception as e:  # noqa: BLE001 - never fail extraction because of cell splitting
        logger.debug("pdf_cells: geometry unavailable (%s)", type(e).__name__)
        return plain
    if owners is None:
        logger.debug("pdf_cells: text/geometry mismatch, page left unsplit")
        return plain
    cands = [_candidates(ln, own, runs) for ln, own in zip(lines, owners)]
    rows = []
    for li, (ln, cs) in enumerate(zip(lines, cands)):
        cuts = []
        for idx, gap_em, x0 in cs:
            aligned = any(
                abs(x0 - ox) <= COLUMN_ALIGN_PT
                for lj, other in enumerate(cands)
                if lj != li
                for _, _, ox in other
            )
            if aligned or gap_em >= CELL_GAP_EM_LONE:
                cuts.append(idx)
        if not cuts:
            rows.append(plain[li])
            continue
        bounds = [0, *cuts, len(ln)]
        cells = tuple(ln[s:e].strip() for s, e in zip(bounds, bounds[1:]))
        rows.append(TextRow(ln.strip(), tuple(c for c in cells if c)))
    return rows
