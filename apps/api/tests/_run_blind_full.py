"""Run all 100 blind cases and print full Q&A report."""

import json
from datetime import date

from app.services.trust_scoring import compute_trust_score

BLIND_PATH = r"C:\Users\John\Downloads\trust_scoring_blind_100_pack\trust_scoring_blind_100_cases.json"
AS_OF = date(2026, 3, 23)


def _map_source(st, ch, hint):
    if ch == "self_reported":
        return "self_reported"
    if ch == "public_record":
        if st in ("business_registry", "tax_registration"):
            return "primary"
        return "public"
    if ch == "third_party":
        if st in ("bank_letter", "lease", "insurance_certificate", "certificate"):
            return "official"
        if st in ("invoice", "screening"):
            return "independent"
        if hint == "low":
            return "public"
        return "independent"
    return "public"


def _recency(issued):
    if not issued:
        return -1
    try:
        return max(0, (AS_OF - date.fromisoformat(issued)).days)
    except (ValueError, TypeError):
        return -1


def _convert(raw):
    seen = set()
    items = []
    for ev in raw["evidence"]:
        fl = ev.get("flags", [])
        grp = ev.get("duplicate_group")
        dup = False
        if grp:
            if grp in seen:
                dup = True
            else:
                seen.add(grp)
        items.append({
            "description": ev.get("title", ""),
            "source_type": _map_source(
                ev.get("source_type", ""),
                ev.get("channel", ""),
                ev.get("confidence_hint", "medium"),
            ),
            "recency_days": _recency(ev.get("issued_at")),
            "relevance": ev.get("relevance", "supporting"),
            "is_duplicate": dup,
            "contradicts": "contradiction" in fl,
            "negative_signal": "expired" in fl and "contradiction" not in fl,
            "tampering": "tampering" in fl,
            "inconsistency": "inconsistency" in fl,
        })
    return items, raw.get("critical_gaps", [])


def main():
    with open(BLIND_PATH, encoding="utf-8") as f:
        data = json.load(f)

    cases = data["cases"]
    results = []

    for c in cases:
        ev, miss = _convert(c)
        r = compute_trust_score(ev, missing_critical=miss)
        results.append((c, r, ev, miss))

    # --- Summary table ---
    print()
    print("=" * 130)
    print("  ALL 100 BLIND CASES — QUESTION, EXPECTED vs ACTUAL")
    print("=" * 130)
    hdr = f"{'ID':<6} {'Cat':<14} {'Bnd':>3} {'Exp':>4} {'Got':>4} {'D':>5}  {'Grd':<5}  Question"
    print(hdr)
    print("-" * 130)

    total_abs = 0
    for c, r, ev, miss in results:
        diff = r["score"] - c["expected_score"]
        total_abs += abs(diff)
        q = c["question"]
        if len(q) > 75:
            q = q[:72] + "..."
        mark = ""
        if abs(diff) > 8:
            mark = " <<< MISS"
        elif abs(diff) > 4:
            mark = " !"
        print(
            f"{c['case_id']:<6} {c['scenario_category']:<14} "
            f"{c['expected_band']:>3} {c['expected_score']:>4} "
            f"{r['score']:>4} {diff:>+5}  {r['grade']:<5}  {q}{mark}"
        )

    mae = total_abs / len(results)
    w4 = sum(1 for c2, r2, _, _ in results if abs(r2["score"] - c2["expected_score"]) <= 4)
    w8 = sum(1 for c2, r2, _, _ in results if abs(r2["score"] - c2["expected_score"]) <= 8)

    print("-" * 130)
    print(f"  MAE = {mae:.2f}  |  within +/-4 = {w4}%  |  within +/-8 = {w8}%")
    print("=" * 130)

    # --- Detailed per-case ---
    print()
    print("=" * 130)
    print("  DETAILED BREAKDOWN PER CASE")
    print("=" * 130)

    for c, r, ev, miss in results:
        diff = r["score"] - c["expected_score"]
        print()
        print(f"--- {c['case_id']} [{c['scenario_category']}] "
              f"Entity: {c['profile']['name']} ---")
        print(f"  Q: {c['question']}")
        print(f"  Expected: {c['expected_score']} (band {c['expected_band']})  "
              f"| Got: {r['score']} (grade {r['grade']})  | Diff: {diff:+d}")
        print(f"  Rationale: {'; '.join(c.get('golden_rationale', []))}")
        print(f"  Critical gaps: {miss if miss else 'none'}")
        print(f"  Breakdown: {r['breakdown']}")
        print(f"  Evidence ({len(ev)} items):")
        for i, e in enumerate(ev, 1):
            flags = []
            if e.get("is_duplicate"):
                flags.append("DUP")
            if e.get("contradicts"):
                flags.append("CONTRADICTION")
            if e.get("tampering"):
                flags.append("TAMPERING")
            if e.get("inconsistency"):
                flags.append("INCONSISTENCY")
            if e.get("negative_signal"):
                flags.append("EXPIRED")
            flag_str = f"  [{','.join(flags)}]" if flags else ""
            print(
                f"    {i}. [{e['source_type']}/{e['relevance']}/{e['recency_days']}d] "
                f"{e['description'][:70]}{flag_str}"
            )


if __name__ == "__main__":
    main()
