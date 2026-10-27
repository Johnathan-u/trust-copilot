"""Same-line table-row corpus: expected questions vs each extraction path (TC-01-003b).

Evaluation only, run from apps/api in the TC-01-003a comparison image (pymupdf and
pdfplumber installed, used only to show their behaviour):
    python ../../artifacts/acceptance/TC-01-003b/compare_table_rows.py
Paths compared, all scored against Case.exact_questions:
* pymupdf(old baseline) / pdfplumber / pypdf-plain: line-based detection on each
  library's page text (the TC-01-003a detection loop);
* branch: parse_pdf_questionnaire (pypdf plain text + x-position cell split).
"""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path.cwd() / "tests"))

from app.services.pdf_questionnaire_parser import parse_pdf_questionnaire  # noqa: E402
from pdf_locator_corpus import table_row_corpus, write_case  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "cmp003a", Path(__file__).resolve().parent.parent / "TC-01-003a" / "compare_backends.py"
)
cmp003a = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cmp003a)


def branch(path):
    return [
        (q["text"], json.loads(q["source_location"])["page"], q["section"])
        for q in parse_pdf_questionnaire(path)
    ]


PATHS = {
    "pymupdf(old baseline)": lambda p: cmp003a.questions(cmp003a.ext_pymupdf(p)),
    "pdfplumber": lambda p: cmp003a.questions(cmp003a.ext_pdfplumber(p)),
    "pypdf-plain (PR #11)": lambda p: cmp003a.questions(cmp003a.ext_pypdf(p)),
    "branch (TC-01-003b)": branch,
}


def main():
    totals = {k: [0, 0, 0] for k in PATHS}
    lines = ["| case | " + " | ".join(PATHS) + " |", "|---|" + "---|" * len(PATHS)]
    detail = {}
    with tempfile.TemporaryDirectory() as d:
        for case in table_row_corpus():
            path = str(write_case(case, Path(d)))
            want = case.exact_questions
            cells = []
            for name, fn in PATHS.items():
                got = fn(path)
                found = sum(1 for w in want if w in got)
                extra = sum(1 for g in got if g not in want)
                totals[name][0] += found
                totals[name][1] += len(want)
                totals[name][2] += extra
                mark = "" if got == want else " ✗"
                cells.append(
                    f"{found}/{len(want)}" + (f" (+{extra} wrong)" if extra else "") + mark
                )
                detail.setdefault(case.name, {})[name] = [g[0] for g in got]
            lines.append(f"| {case.name} | " + " | ".join(cells) + " |")
    lines.append(
        "| **total** | "
        + " | ".join(f"**{a}/{b}** (+{c} wrong)" for a, b, c in totals.values())
        + " |"
    )
    print("\n".join(lines))
    print("\nPer case: expected questions found exactly (text, page, section) / expected;")
    print("'wrong' counts extracted questions not in the expected list; ✗ marks any")
    print("difference from the expected list, including order.\n")
    print("```json")
    print(json.dumps(detail, indent=1, ensure_ascii=False))
    print("```")


if __name__ == "__main__":
    main()
