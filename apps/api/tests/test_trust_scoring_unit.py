"""Unit tests for trust_scoring -- runs 20 mock verification cases.

Each case encodes a claim, structured evidence items, and an expected score.
Tests verify the scoring engine produces results within TOLERANCE of the target.
"""

import pytest

from app.services.trust_scoring import compute_trust_score


# -- Helper -----------------------------------------------------------------

def _e(desc, src, days, rel, **flags):
    """Shorthand evidence-item builder."""
    return {
        "description": desc,
        "source_type": src,
        "recency_days": days,
        "relevance": rel,
        **flags,
    }


# -- 20 Mock Cases ---------------------------------------------------------

CASES = [
    # -- C001  Clean, high-confidence (expected 96) -------------------------
    {
        "id": "C001",
        "claim": "Vendor is active, tax-registered, and has a real operating address.",
        "expected": 96,
        "evidence": [
            _e("State business registry match (updated 2026-03-10)", "primary", 5, "direct"),
            _e("IRS/TIN confirmation received 2026-03-14", "primary", 1, "direct"),
            _e("Utility bill matching declared address (2026-02)", "official", 30, "direct"),
            _e("Website resolves, business email domain matches", "public", 0, "supporting"),
            _e("Phone number matches public directory listing", "public", 0, "supporting"),
        ],
    },

    # -- C002  Strong with minor freshness issue (expected 84) --------------
    {
        "id": "C002",
        "claim": "Business is valid and reachable.",
        "expected": 84,
        "evidence": [
            _e("Companies registry match from 2025-11-20", "primary", 115, "direct"),
            _e("Website active, TLS valid", "public", 0, "supporting"),
            _e("Corporate email works", "public", 0, "supporting"),
            _e("Address appears on invoice 1", "independent", 30, "direct"),
            _e("Address appears on invoice 2", "independent", 30, "direct"),
        ],
        "missing_critical": ["recent_address_proof"],
    },

    # -- C003  Good with one soft inconsistency (expected 91) ---------------
    {
        "id": "C003",
        "claim": "Applicant resides at declared address.",
        "expected": 91,
        "evidence": [
            _e("Bank statement 2026-03 shows address", "official", 15, "direct"),
            _e("Utility bill 2026-02 shows address", "official", 30, "direct"),
            _e("Government ID shows address (89 Willow Ln Unit 5C)", "primary", 0, "direct"),
            _e("Employer letter shows address", "official", 0, "supporting"),
        ],
    },

    # -- C004  Moderate with incomplete evidence (expected 68) ---------------
    {
        "id": "C004",
        "claim": "User employment is current.",
        "expected": 68,
        "evidence": [
            _e("Offer letter dated 2024-08-20", "official", 90, "supporting"),
            _e("Last payslip available is 2025-10", "official", 30, "direct"),
            _e("LinkedIn says currently employed", "public", 0, "supporting"),
        ],
        "missing_critical": ["hr_verification"],
    },

    # -- C005  Moderate with stale evidence (expected 57) --------------------
    {
        "id": "C005",
        "claim": "Company still operates from declared address.",
        "expected": 57,
        "evidence": [
            _e("Lease agreement valid through 2024-12", "official", 440, "supporting"),
            _e("Website still lists address", "public", 0, "supporting"),
            _e("Google Business listing shows address (verified)", "independent", 0, "direct"),
        ],
        "missing_critical": ["recent_bills", "tax_notices"],
    },

    # -- C006  Mixed with direct contradiction (expected 49) -----------------
    {
        "id": "C006",
        "claim": "Applicant income is $8,500/month.",
        "expected": 49,
        "evidence": [
            _e("Employer letter implies $8,200/month gross", "official", 0, "direct"),
            _e("Bank deposits average $5,100/month (last 3 months)", "official", 0, "direct", contradicts=True),
            _e("Payslips show one-time bonus in January", "official", 60, "supporting"),
            _e("Applicant explanation: seasonal commissions", "self_reported", 0, "supporting"),
        ],
    },

    # -- C007  Weak, only self-reported (expected 28) ------------------------
    {
        "id": "C007",
        "claim": "Business has completed 1,000 orders.",
        "expected": 28,
        "evidence": [
            _e("Founder statement in application", "self_reported", 0, "direct"),
            _e("Internal screenshot of dashboard", "self_reported", 0, "supporting"),
        ],
        "missing_critical": ["independent_order_verification"],
    },

    # -- C008  Strong despite one weak contradictory signal (expected 88) ----
    {
        "id": "C008",
        "claim": "Charity is active and in good standing.",
        "expected": 88,
        "evidence": [
            _e("Charity commission registry: active as of 2026-03-01", "primary", 14, "direct"),
            _e("Annual filing accepted", "official", 30, "direct"),
            _e("Bank letter matches entity details", "official", 14, "direct"),
            _e("One old directory site: status 'unknown'", "public", 365, "supporting", contradicts=True),
        ],
    },

    # -- C009  Duplicate evidence pretending to be multiple (expected 42) ----
    {
        "id": "C009",
        "claim": "Address is verified.",
        "expected": 42,
        "evidence": [
            _e("PDF bank statement", "official", 0, "direct"),
            _e("JPG image of the same bank statement", "official", 0, "direct", is_duplicate=True),
            _e("Cropped screenshot of same statement header", "official", 0, "direct", is_duplicate=True),
        ],
    },

    # -- C010  Missing critical fields (expected 12) -------------------------
    {
        "id": "C010",
        "claim": "Supplier is fully identified.",
        "expected": 12,
        "evidence": [
            _e("Website contact form only", "public", 0, "tangential"),
            _e("Generic Gmail address", "public", 0, "tangential"),
            _e("Marketing brochure", "self_reported", 0, "supporting"),
        ],
        "missing_critical": ["registration_docs", "tax_id", "verified_address"],
    },

    # -- C011  High-quality with multilingual variance (expected 86) ---------
    {
        "id": "C011",
        "claim": "Entity details match across jurisdictions.",
        "expected": 86,
        "evidence": [
            _e("Domestic registry uses Spanish legal name", "primary", 30, "direct"),
            _e("International invoice uses English trade name", "independent", 30, "direct", inconsistency=True),
            _e("Tax certificate with same registration number", "primary", 30, "direct"),
            _e("Bank letter references abbreviated name 'Tec del Norte'", "official", 30, "supporting", inconsistency=True),
        ],
    },

    # -- C012  Fraud-suspected document tampering (expected 6) ---------------
    {
        "id": "C012",
        "claim": "Bank statement proves cash reserves of $240,000.",
        "expected": 6,
        "evidence": [
            _e("Submitted PDF bank statement (image editor metadata, font mismatch)", "official", 0, "direct", tampering=True),
            _e("Prior month balance pattern inconsistent", "official", 30, "direct", contradicts=True),
        ],
        "missing_critical": ["direct_bank_verification"],
    },

    # -- C013  Conflicting primary sources (expected 34) ---------------------
    {
        "id": "C013",
        "claim": "License is active.",
        "expected": 34,
        "evidence": [
            _e("State agency portal A: 'Active' as of 2026-02-28", "primary", 16, "direct"),
            _e("Renewal enforcement portal B: 'Suspended for non-payment' 2026-03-09", "primary", 7, "direct", contradicts=True),
            _e("Old renewal receipt from 2025", "official", 365, "supporting"),
        ],
    },

    # -- C014  Partial mismatch with plausible explanation (expected 82) -----
    {
        "id": "C014",
        "claim": "Owner identity is verified.",
        "expected": 82,
        "evidence": [
            _e("Passport: 'Sameer Alhadi' (transliteration variant)", "primary", 0, "direct", inconsistency=True),
            _e("Tax record: 'Samir Al-Hadi'", "primary", 0, "direct"),
            _e("Facial match passes", "independent", 0, "direct"),
            _e("Address matches across records", "independent", 0, "supporting"),
        ],
    },

    # -- C015  Poor case, stale-only evidence (expected 21) ------------------
    {
        "id": "C015",
        "claim": "Merchant is currently operational.",
        "expected": 21,
        "evidence": [
            _e("Social page last post 2023-08", "public", 960, "direct"),
            _e("Review site entry from 2024-01", "public", 805, "direct"),
            _e("Old supplier invoice from 2023-11", "independent", 865, "direct"),
            _e("Phone disconnected when checked", "public", 0, "direct", negative_signal=True),
            _e("Website no longer loads", "public", 0, "direct", negative_signal=True),
        ],
    },

    # -- C016  Strong with third-party corroboration (expected 93) -----------
    {
        "id": "C016",
        "claim": "Contractor completed prior projects of similar size.",
        "expected": 93,
        "evidence": [
            _e("Signed completion certificate 1", "official", 30, "direct"),
            _e("Signed completion certificate 2", "official", 30, "direct"),
            _e("Client reference 1 independently confirms", "independent", 30, "direct"),
            _e("Client reference 2 independently confirms", "independent", 30, "direct"),
            _e("Client reference 3 independently confirms", "independent", 30, "direct"),
            _e("Public procurement portal: matching award 1", "primary", 30, "direct"),
            _e("Public procurement portal: matching award 2", "primary", 30, "direct"),
            _e("Insurance certificates current", "official", 0, "supporting"),
        ],
    },

    # -- C017  Borderline with irrelevant evidence padding (expected 46) -----
    {
        "id": "C017",
        "claim": "Seller has strong fulfillment capability.",
        "expected": 46,
        "evidence": [
            _e("20 screenshots of social media followers", "public", 0, "tangential"),
            _e("8 product photos", "self_reported", 0, "tangential"),
            _e("1 warehouse lease", "official", 0, "direct"),
        ],
        "missing_critical": ["shipping_sla", "order_throughput", "carrier_accounts", "delivery_performance"],
    },

    # -- C018  Excellent with recency and primary evidence (expected 95) -----
    {
        "id": "C018",
        "claim": "Organization has sufficient liquidity.",
        "expected": 95,
        "evidence": [
            _e("Audited financial statements FY2025", "official", 90, "direct"),
            _e("Bank confirmation letter dated 2026-03-18", "primary", 3, "direct"),
            _e("Accounts payable aging 2026-03-17", "official", 4, "direct"),
            _e("Accounts receivable aging 2026-03-17", "official", 4, "direct"),
        ],
    },

    # -- C019  Evidence supports existence, not specific claim (expected 31) -
    {
        "id": "C019",
        "claim": "Business annual revenue exceeds $5M.",
        "expected": 31,
        "evidence": [
            _e("Business registration verified", "primary", 30, "tangential"),
            _e("Website active", "public", 0, "tangential"),
            _e("10 employees on staff page", "public", 0, "tangential"),
            _e("Office lease", "official", 0, "supporting"),
        ],
        "missing_critical": ["financial_statements", "tax_filings", "bank_inflow_summaries"],
    },

    # -- C020  Very strong with one unresolved small gap (expected 78) -------
    {
        "id": "C020",
        "claim": "Importer is compliant and shipment-ready.",
        "expected": 78,
        "evidence": [
            _e("Customs registration active", "primary", 10, "direct"),
            _e("VAT number valid", "primary", 10, "direct"),
            _e("Warehouse contract active", "official", 30, "direct"),
            _e("Insurance active", "official", 0, "supporting"),
            _e("Prior import entries in customs history", "primary", 30, "direct"),
            _e("Safety certificate expired 10 days ago", "official", 10, "direct", contradicts=True),
        ],
        "missing_critical": ["valid_safety_certificate"],
    },
]


# -- Parametrised test ------------------------------------------------------

TOLERANCE = 5


@pytest.mark.parametrize(
    "case",
    CASES,
    ids=[c["id"] for c in CASES],
)
def test_trust_score(case):
    result = compute_trust_score(
        case["evidence"],
        missing_critical=case.get("missing_critical"),
    )
    score = result["score"]
    expected = case["expected"]
    diff = abs(score - expected)
    assert diff <= TOLERANCE, (
        f'{case["id"]}: expected ~{expected}, got {score} (off by {diff}). '
        f'Breakdown: {result["breakdown"]}'
    )


# -- Report runner (use `pytest -s -k report` to see table) -----------------

def test_report_all_cases():
    """Print a comparison table of all 20 cases."""
    rows = []
    max_diff = 0
    for c in CASES:
        r = compute_trust_score(c["evidence"], c.get("missing_critical"))
        diff = r["score"] - c["expected"]
        max_diff = max(max_diff, abs(diff))
        rows.append((c["id"], c["expected"], r["score"], diff, r["grade"]))

    header = f"{'ID':<6} {'Exp':>4} {'Got':>4} {'D':>4}  Grade"
    print(f"\n{'=' * 36}")
    print(header)
    print(f"{'-' * 36}")
    for cid, exp, got, diff, grade in rows:
        marker = " ok" if abs(diff) <= TOLERANCE else " MISS"
        print(f"{cid:<6} {exp:>4} {got:>4} {diff:>+4}  {grade}{marker}")
    print(f"{'-' * 36}")
    print(f"Max |D| = {max_diff}")
    print(f"{'=' * 36}\n")
