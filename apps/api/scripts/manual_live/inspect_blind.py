"""Manual dataset script (see README.md). Not a pytest module."""

from _live_guard import require_data_file
import json

with open(require_data_file("TC_TRUST_SCORING_BLIND_PACK")) as f:
    data = json.load(f)

cats = {}
for c in data["cases"]:
    cat = c["scenario_category"]
    if cat not in cats:
        cats[cat] = c

for cat in ["stale", "dup", "tampered", "inconsistent", "tangential", "mixed"]:
    c = cats[cat]
    cid = c["case_id"]
    exp = c["expected_score"]
    gaps = c["critical_gaps"]
    print(f"=== {cid} ({cat}) expected={exp} gaps={gaps} ===")
    for e in c["evidence"]:
        flags = e["flags"]
        dg = e["duplicate_group"]
        print(
            f"  {e['source_type']:<25} ch={e['channel']:<15} "
            f"rel={e['relevance']:<12} issued={e['issued_at']}  "
            f"flags={flags}  dup_grp={dg}  conf={e['confidence_hint']}"
        )
    print()
