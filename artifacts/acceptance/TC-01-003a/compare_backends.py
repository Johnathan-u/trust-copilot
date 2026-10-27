"""Old-vs-new locator comparison on the synthetic corpus (TC-01-003a).

Evaluation only, run from apps/api in a throwaway test image that has
pymupdf (baseline), pypdf and pdfplumber installed:
    python ../../artifacts/acceptance/TC-01-003a/compare_backends.py
PyMuPDF is used here only to record baseline behaviour. It is not a
dependency of the branch.
"""

import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path.cwd() / "tests"))

from app.services.question_detector import (  # noqa: E402
    looks_like_question,
    looks_like_section_header,
)
from app.services.question_normalizer import normalize_question  # noqa: E402
from pdf_locator_corpus import corpus, write_case  # noqa: E402


def ext_pymupdf(path):
    import pymupdf

    doc = pymupdf.open(path)
    try:
        return [p.get_text() for p in doc]
    finally:
        doc.close()


def ext_pypdf(path):
    from pypdf import PdfReader

    r = PdfReader(path)
    if r.is_encrypted:
        r.decrypt("")
    return [p.extract_text() or "" for p in r.pages]


def ext_pdfplumber(path):
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        return [p.extract_text() or "" for p in pdf.pages]


BACKENDS = {"pymupdf(baseline)": ext_pymupdf, "pypdf": ext_pypdf, "pdfplumber": ext_pdfplumber}


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def questions(pages):
    section, out = None, []
    for i, text in enumerate(pages):
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if looks_like_section_header(line):
                section = line
                continue
            if looks_like_question(line):
                n = normalize_question(line)
                if len(n) >= 10:
                    out.append((n, i + 1, section))
    return out


def score(case, pages, err):
    checks, fails = 0, []

    def check(ok, msg):
        nonlocal checks
        checks += 1
        if not ok:
            fails.append(msg)

    if case.outcome in ("unreadable", "encrypted"):
        no_text = not any(p.strip() for p in (pages or []))
        check(err is not None or no_text, "expected failure, got text")
        return checks, fails
    if err is not None:
        check(False, f"raised {err}")
        return checks, fails
    if case.outcome == "no_text":
        check(not any(p.strip() for p in pages), "expected no text")
    for pg in case.empty_pages:
        check(len(pages) >= pg and not pages[pg - 1].strip(), f"page {pg} not empty")
    for pg, markers in case.page_markers.items():
        for m in markers:
            on = [i + 1 for i, t in enumerate(pages) if m in norm(t)]
            check(on == [pg], f"{m!r} on pages {on}, want [{pg}]")
    for seq in case.ordered:
        for pg_text in pages:
            t = norm(pg_text)
            if all(m in t for m in seq):
                pos = [t.index(m) for m in seq]
                check(pos == sorted(pos), f"order broken {seq[:3]}...")
                break
    for row in case.same_line:
        lines = [ln for t in pages for ln in t.splitlines()]
        hit = [ln for ln in lines if all(c in ln for c in row)]
        ok = any([ln.index(c) for c in row] == sorted(ln.index(c) for c in row) for ln in hit)
        check(ok, f"row {row[0]} not on one line in order")
    for m in case.own_line:
        lines = [ln for t in pages for ln in t.splitlines() if m in ln]
        others = [o for o in case.own_line if o != m]
        merged = any(o in ln for ln in lines for o in others)
        check(bool(lines) and not merged, f"{m} merged with another marker")
    if case.questions:
        got = questions(pages)
        for sub, pg, sec in case.questions:
            found = any(sub in q and p == pg and s == sec for q, p, s in got)
            check(found, f"question {sub!r} p{pg} not found")
    return checks, fails


def main():
    rows, detail = [], {}
    with tempfile.TemporaryDirectory() as d:
        for case in corpus():
            path = write_case(case, Path(d))
            for name, fn in BACKENDS.items():
                try:
                    pages, err = fn(str(path)), None
                except Exception as e:  # noqa: BLE001
                    pages, err = None, f"{type(e).__name__}: {str(e)[:80]}"
                checks, fails = score(case, pages, err)
                rows.append((case.name, name, checks - len(fails), checks, fails))
                detail.setdefault(case.name, {})[name] = {
                    "error": err,
                    "pages": [p[:400] for p in pages] if pages else pages,
                    "failures": fails,
                }
    totals = {}
    for _, b, ok, n, _ in rows:
        t = totals.setdefault(b, [0, 0])
        t[0] += ok
        t[1] += n
    print("| case | " + " | ".join(BACKENDS) + " |")
    print("|---|" + "---|" * len(BACKENDS))
    for case in dict.fromkeys(r[0] for r in rows):
        cells = []
        for b in BACKENDS:
            r = next(x for x in rows if x[0] == case and x[1] == b)
            note = "" if not r[4] else " (" + "; ".join(r[4])[:120] + ")"
            cells.append(f"{r[2]}/{r[3]}{note}")
        print(f"| {case} | " + " | ".join(cells) + " |")
    tot = " | ".join(f"**{totals[b][0]}/{totals[b][1]}**" for b in BACKENDS)
    print(f"| **total** | {tot} |")
    out = json.dumps(detail, indent=1, ensure_ascii=False)
    Path("/tmp/tc01003a_compare_detail.json").write_text(out)


if __name__ == "__main__":
    main()
