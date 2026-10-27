"""Record the PyMuPDF baseline locator output for the synthetic corpus (TC-01-003a).

Evaluation only. Runs the f72def3 versions of evidence_parser.py and
pdf_questionnaire_parser.py (PyMuPDF) on every corpus case and writes
apps/api/tests/fixtures/pdf_locator/baseline_pymupdf.json, which the branch tests
compare the new pypdf backend against. Run from apps/api in an image that still has
pymupdf installed, with the baseline sources extracted by `git show f72def3:<path>`:
    python ../../artifacts/acceptance/TC-01-003a/record_baseline.py <baseline_src_dir>
"""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path.cwd() / "tests"))

from pdf_locator_corpus import corpus, write_case  # noqa: E402

OUT = Path("tests/fixtures/pdf_locator/baseline_pymupdf.json")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(fn, path):
    try:
        return {"ok": fn(path)}
    except Exception as e:  # noqa: BLE001
        return {"error": type(e).__name__}


def main(src):
    ev = load("baseline_evidence_parser", Path(src) / "evidence_parser.py")
    qp = load("baseline_pdf_questionnaire_parser", Path(src) / "pdf_questionnaire_parser.py")
    out = {}
    with tempfile.TemporaryDirectory() as d:
        for case in corpus():
            path = write_case(case, Path(d))
            q = run(qp.parse_pdf_questionnaire, path)
            if "ok" in q:
                for item in q["ok"]:
                    loc = json.loads(item["source_location"])
                    loc["file"] = "<path>"
                    item["source_location"] = loc
            out[case.name] = {
                "evidence": run(ev.parse_evidence, path),
                "questionnaire": q,
            }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"wrote {OUT} ({len(out)} cases)")


if __name__ == "__main__":
    main(sys.argv[1])
