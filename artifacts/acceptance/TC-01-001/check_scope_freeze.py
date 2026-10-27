#!/usr/bin/env python3
"""TC-01-001 mechanical check: every route module and page file in the repo is frozen
in docs/acceptance/scope-freeze.md with an owner epic and a delivery ticket.
Run from the repo root: python3 artifacts/acceptance/TC-01-001/check_scope_freeze.py
"""

import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[3]
doc = (root / "docs/acceptance/scope-freeze.md").read_text(encoding="utf-8")
rows = {
    m.group(1): m.group(0)
    for m in re.finditer(r"^\|[^|]+\|[^|]+\| `([^`]+\.(?:py|tsx))` \|.*$", doc, re.M)
}
routes = sorted(
    p.relative_to(root).as_posix()
    for p in (root / "apps/api/app/api/routes").glob("*.py")
    if p.name != "__init__.py"
)
pages = sorted(p.relative_to(root).as_posix() for p in (root / "apps/web/app").rglob("page.tsx"))
bad = []
for f in routes + pages:
    r = rows.get(f)
    if not r:
        bad.append(f"missing: {f}")
    elif not re.search(r"\| E\d\d ", r) or not re.search(r"TC-\d\d-\d\d\d", r):
        bad.append(f"no owner epic/ticket: {f}")
for f in rows:
    if not (root / f).exists():
        bad.append(f"frozen surface not in repo: {f}")
for sec in (
    "## 5. Background dispatchers",
    "## 6. Registered or advertised providers",
    "## 7. Explicitly out of scope",
    "No silent disabling",
):
    if sec not in doc:
        bad.append(f"missing section: {sec}")
print(
    f"route modules in repo: {len(routes)}; pages in repo: {len(pages)}; frozen rows: {len(rows)}"
)
if bad:
    print("\n".join(bad))
    print("FAIL")
    sys.exit(1)
print(
    "PASS: all route modules and pages frozen with owner epic and delivery tickets; dispatcher, provider, out-of-scope sections present"
)
