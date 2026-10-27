#!/usr/bin/env python3
"""TC-01-005 regression check: public copy must not reintroduce removed claims.

Run from the repo root: python3 scripts/check_public_claims.py
Exits non-zero if a banned phrase or missing label is found. No DB or network needed.
See docs/acceptance/claims-register.md.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PUBLIC_FILES = [
    "README.md",
    "apps/web/app/layout.tsx",
    "apps/web/app/page.tsx",
    "apps/web/app/pricing/page.tsx",
    "apps/web/app/checkout/page.tsx",
    "apps/api/app/services/security_page_service.py",
]

# (pattern, register row) — case-insensitive
BANNED = [
    (r"hallucinat", "C1/C2"),
    (r"never used to train|never used for training", "D1"),
    (r"in minutes|not weeks|spending weeks|take weeks", "C5"),
    (r"supports common compliance frameworks", "C6"),
    (r"Word, PDF", "C7"),
    (r"original layout\.", "C9"),
    (r"common security questionnaire formats", "C10"),
    (r"no failures", "C20"),
    (r"until April 5|Free until|No charge until", "B1"),
    (r">FREE<", "B1"),
    (r"strict access controls", "D3"),
    (r"designed to meet the security expectations", "D2"),
    (r'"status": "(compliant|in_progress|certified)"', "D8"),
    (r"maintain compliance", "D13"),
    (r'"dpa_available": True|"subprocessor_list_available": True', "D10"),
    (r"validated by automated", "A9"),
]

# (file, required substring, register row)
REQUIRED_LABELS = [
    ("apps/api/app/services/demo_proof_service.py", '"synthetic_example"', "A8"),
    ("apps/api/app/services/roi_calculator_service.py", '"estimate_basis"', "A5"),
    ("apps/api/app/services/proof_widgets_service.py", '"hours_saved_basis"', "A7"),
    ("apps/api/app/services/crm_connector_service.py", '"data_basis": "synthetic_example"', "A2"),
    ("apps/api/app/services/security_faq_service.py", "DEFAULT_TEMPLATE_NOTICE + ", "D12"),
]


def main() -> int:
    failures = []
    for rel in PUBLIC_FILES + ["apps/api/app/services/demo_proof_service.py"]:
        text = (ROOT / rel).read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pat, row in BANNED:
                if re.search(pat, line, re.IGNORECASE):
                    failures.append(f"{rel}:{lineno}: banned claim ({row}): {line.strip()[:120]}")
    for rel, needle, row in REQUIRED_LABELS:
        if needle not in (ROOT / rel).read_text(encoding="utf-8"):
            failures.append(f"{rel}: missing example/heuristic label ({row}): {needle}")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for link in re.findall(r"\]\(((?:docs|apps|scripts)/[^)#]+)\)", readme):
        if not (ROOT / link).exists():
            failures.append(f"README.md: link to missing file (C21): {link}")
    if failures:
        print("\n".join(failures))
        print(f"FAIL: {len(failures)} claim regression(s)")
        return 1
    print("PASS: no removed claims reintroduced; example/heuristic labels present; README links resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
