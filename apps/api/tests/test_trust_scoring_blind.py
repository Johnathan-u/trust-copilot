"""Blind validation: 100 unseen cases against the trust scoring engine.

Maps the blind-pack schema to compute_trust_score inputs and measures:
  - MAE
  - % within +/-4
  - % within +/-8
  - largest misses by category
"""

import json
from datetime import date
from pathlib import Path

import pytest

from app.services.trust_scoring import compute_trust_score

BLIND_PATH = Path(r"C:\Users\John\Downloads\trust_scoring_blind_100_pack\trust_scoring_blind_100_cases.json")
AS_OF = date(2026, 3, 23)


# -- Schema mapping ---------------------------------------------------------

def _map_source_type(source_type: str, channel: str, confidence_hint: str) -> str:
    if channel == "self_reported":
        return "self_reported"
    if channel == "public_record":
        if source_type in ("business_registry", "tax_registration"):
            return "primary"
        return "public"
    if channel == "third_party":
        if source_type in ("bank_letter", "lease", "insurance_certificate", "certificate"):
            return "official"
        if source_type in ("invoice", "screening"):
            return "independent"
        if confidence_hint == "low":
            return "public"
        return "independent"
    return "public"


def _recency_days(issued_at: str | None) -> int:
    if not issued_at:
        return -1
    try:
        issued = date.fromisoformat(issued_at)
        return max(0, (AS_OF - issued).days)
    except (ValueError, TypeError):
        return -1


def _map_case(raw: dict) -> tuple[list[dict], list[str]]:
    """Convert a blind-pack case into (evidence_items, missing_critical)."""
    seen_dup_groups: set[str] = set()
    items: list[dict] = []

    for ev in raw["evidence"]:
        flags = ev.get("flags", [])
        grp = ev.get("duplicate_group")

        is_dup = False
        if grp is not None:
            if grp in seen_dup_groups:
                is_dup = True
            else:
                seen_dup_groups.add(grp)

        items.append({
            "description": ev.get("title", ""),
            "source_type": _map_source_type(
                ev.get("source_type", ""),
                ev.get("channel", ""),
                ev.get("confidence_hint", "medium"),
            ),
            "recency_days": _recency_days(ev.get("issued_at")),
            "relevance": ev.get("relevance", "supporting"),
            "is_duplicate": is_dup,
            "contradicts": "contradiction" in flags,
            "negative_signal": "expired" in flags and "contradiction" not in flags,
            "tampering": "tampering" in flags,
            "inconsistency": "inconsistency" in flags,
        })

    missing = raw.get("critical_gaps", [])
    return items, missing


# -- Load cases -------------------------------------------------------------

def _load_cases() -> list[dict]:
    with open(BLIND_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data["cases"]


CASES = _load_cases()


# -- Individual parametrised test -------------------------------------------

@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_blind_case(case):
    evidence, missing = _map_case(case)
    result = compute_trust_score(evidence, missing_critical=missing)
    score = result["score"]
    expected = case["expected_score"]
    diff = abs(score - expected)
    assert diff <= 8, (
        f'{case["case_id"]} ({case["scenario_category"]}): '
        f'expected {expected}, got {score} (off by {diff}). '
        f'Breakdown: {result["breakdown"]}'
    )


# -- Full report (run with pytest -s -k blind_report) -----------------------

def test_blind_report():
    """Print metrics table for all 100 blind cases."""
    rows = []
    cat_errors: dict[str, list[int]] = {}
    for c in CASES:
        evidence, missing = _map_case(c)
        result = compute_trust_score(evidence, missing_critical=missing)
        score = result["score"]
        expected = c["expected_score"]
        diff = score - expected
        cat = c["scenario_category"]
        cat_errors.setdefault(cat, []).append(abs(diff))
        rows.append((c["case_id"], cat, expected, score, diff, result["grade"]))

    abs_diffs = [abs(d) for _, _, _, _, d, _ in rows]
    mae = sum(abs_diffs) / len(abs_diffs)
    within_4 = sum(1 for d in abs_diffs if d <= 4) / len(abs_diffs) * 100
    within_8 = sum(1 for d in abs_diffs if d <= 8) / len(abs_diffs) * 100

    print(f"\n{'=' * 56}")
    print(f"  BLIND VALIDATION REPORT  (100 cases, frozen weights)")
    print(f"{'=' * 56}")
    print(f"  MAE           = {mae:.2f}   (target <= 6.0)")
    print(f"  within +/-4   = {within_4:.0f}%    (target >= 65%)")
    print(f"  within +/-8   = {within_8:.0f}%    (target >= 85%)")
    print(f"{'=' * 56}")
    print(f"\n{'ID':<6} {'Cat':<14} {'Exp':>4} {'Got':>4} {'D':>5}  Grade")
    print(f"{'-' * 56}")
    for cid, cat, exp, got, diff, grade in rows:
        marker = ""
        ad = abs(diff)
        if ad > 8:
            marker = " <<< MISS"
        elif ad > 4:
            marker = " !"
        print(f"{cid:<6} {cat:<14} {exp:>4} {got:>4} {diff:>+5}  {grade}{marker}")

    print(f"\n{'=' * 56}")
    print(f"  MAE BY CATEGORY")
    print(f"{'=' * 56}")
    for cat in sorted(cat_errors):
        errs = cat_errors[cat]
        cat_mae = sum(errs) / len(errs)
        cat_max = max(errs)
        print(f"  {cat:<14}  MAE={cat_mae:5.1f}  max={cat_max:3d}  n={len(errs)}")
    print(f"{'=' * 56}\n")
