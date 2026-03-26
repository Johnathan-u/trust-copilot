"""Unit tests for compliance_coverage computation logic.

Pushes controlled mock data through get_compliance_coverage() and verifies
every output section: KPIs, framework_coverage, blind_spots, weak_areas,
evidence_strength, trends, drill_down, recommended_evidence.

Uses a mock DB session so no Postgres is needed — pure logic verification.
"""

import json
from datetime import datetime
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

class _Chain(list):
    """Chainable mock mimicking the SQLAlchemy query builder interface.

    Inherits list so SQLAlchemy's Column.in_() accepts it as an iterable.
    The *terminal* value (what .scalar() / .all() returns) is stored in _val.
    """

    def __init__(self, terminal=None):
        super().__init__([0])
        self._val = terminal

    def filter(self, *a, **kw):
        return self

    def join(self, *a, **kw):
        return self

    def group_by(self, *a, **kw):
        return self

    def order_by(self, *a, **kw):
        return self

    def limit(self, *a, **kw):
        return self

    def subquery(self):
        return MagicMock()

    def scalar(self):
        return self._val

    def all(self):
        return self._val if self._val is not None else []


def _cats(frameworks=None, subjects=None):
    """Build a primary_categories_json string."""
    return json.dumps({"frameworks": frameworks or [], "subjects": subjects or []})


def _cits(n):
    """Build a citations JSON string with *n* entries."""
    return json.dumps([{"chunk_id": i, "snippet": f"s{i}"} for i in range(n)])


def _make_db(total_questions, answer_rows, signal_rows, gap_rows):
    """Build a mock DB session that returns *controlled* data in the exact
    call-order that ``get_compliance_coverage`` issues its queries:

    1. Questionnaire.id  → subquery
    2. count(Question.id) → scalar (total_questions)
    3. base_qnr.c.id      (nested inside #2's .filter)
    4. Answer rows         → all
    5. base_qnr.c.id      (nested inside #4's .filter)
    6. QuestionMappingSignal rows → all
    7. EvidenceGap rows          → all
    """
    chains = [
        _Chain(),                    # 1
        _Chain(total_questions),     # 2
        _Chain(),                    # 3
        _Chain(answer_rows),         # 4
        _Chain(),                    # 5
        _Chain(signal_rows),         # 6
        _Chain(gap_rows),            # 7
    ]
    idx = {"n": 0}

    def _query(*a, **kw):
        i = idx["n"]
        idx["n"] += 1
        return chains[i] if i < len(chains) else _Chain()

    db = MagicMock()
    db.query.side_effect = _query
    return db


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

TOTAL_Q = 20

ANSWERS = [
    # (id, question_id, status, confidence, primary_categories_json, citations, created_at)
    # --- day 1 (2026-03-20): 3 drafts ---
    ( 1,  1, "draft",                 85, _cats(["SOC 2"], ["Access Control"]),                              _cits(3), datetime(2026, 3, 20)),
    ( 2,  2, "draft",                 45, _cats(["SOC 2"], ["Access Control"]),                              _cits(1), datetime(2026, 3, 20)),
    ( 3,  3, "draft",                 90, _cats(["SOC 2", "ISO 27001"], ["Encryption"]),                     _cits(5), datetime(2026, 3, 20)),
    # --- day 2 (2026-03-21): 3 approved, 2 drafts, 1 insufficient ---
    ( 4,  4, "approved",              80, _cats(["ISO 27001"], ["Risk Assessment"]),                         _cits(2), datetime(2026, 3, 21)),
    ( 5,  5, "approved",              75, _cats(["ISO 27001"], ["Risk Assessment"]),                         _cits(4), datetime(2026, 3, 21)),
    ( 6,  6, "approved",              92, _cats(["GDPR"], ["Privacy / Data Governance"]),                    _cits(6), datetime(2026, 3, 21)),
    ( 7,  7, "draft",                 30, _cats(["SOC 2"], ["Vendor Management"]),                           _cits(0), datetime(2026, 3, 21)),
    ( 8,  8, "draft",                 55, _cats(["SOC 2"], ["Vendor Management"]),                           _cits(1), datetime(2026, 3, 21)),
    ( 9,  9, "insufficient_evidence", 20, _cats(["ISO 27001"], ["Business Continuity / Disaster Recovery"]), _cits(0), datetime(2026, 3, 21)),
    # --- day 3 (2026-03-22): 3 drafts, 3 insufficient (one with no categories) ---
    (10, 10, "insufficient_evidence", 15, _cats(["SOC 2"], ["Incident Response"]),                           _cits(0), datetime(2026, 3, 22)),
    (11, 11, "insufficient_evidence", 25, _cats(["GDPR"], ["Breach Notification"]),                          _cits(0), datetime(2026, 3, 22)),
    (12, 12, "draft",                 70, _cats(["HIPAA"], ["Access Control"]),                              _cits(2), datetime(2026, 3, 22)),
    (13, 13, "draft",                 88, _cats(["HIPAA"], ["Encryption"]),                                  _cits(3), datetime(2026, 3, 22)),
    (14, 14, "insufficient_evidence", 10, None, None, datetime(2026, 3, 22)),  # no categories → signal fallback
    (15, 15, "draft",                 95, _cats(["SOC 2"], ["Change Management"]),                           _cits(4), datetime(2026, 3, 22)),
    # --- day 4 (2026-03-23): 2 drafts, 1 insufficient ---
    (16, 16, "draft",                 35, _cats(["GDPR"], ["Privacy / Data Governance"]),                    _cits(1), datetime(2026, 3, 23)),
    (17, 17, "insufficient_evidence", 18, _cats(["SOC 2"], ["Physical Security"]),                           _cits(0), datetime(2026, 3, 23)),
    (18, 18, "draft",                 60, _cats(["SOC 2"], ["Secure SDLC"]),                                 _cits(2), datetime(2026, 3, 23)),
]

SIGNALS = [
    # (question_id, framework_labels_json, subject_labels_json)
    (14, '["PCI DSS"]', '["Data Retention / Disposal"]'),
]

GAPS = [
    # (suggested_evidence_doc_title, count)
    ("Vendor Risk Management Policy", 3),
    ("Incident Response Plan", 2),
    ("Business Continuity & DR Plan", 1),
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestComplianceCoverageComputation:
    """Push mock data through get_compliance_coverage and verify every section."""

    def _run(self, total_q=TOTAL_Q, answers=ANSWERS, signals=SIGNALS, gaps=GAPS):
        from app.services.compliance_coverage import get_compliance_coverage
        db = _make_db(total_q, answers, signals, gaps)
        return get_compliance_coverage(db, workspace_id=1)

    # ── KPI cards ──────────────────────────────────────────────────────────

    def test_kpi_totals(self):
        r = self._run()
        kpi = r["kpi"]
        assert kpi["total_questions"] == 20
        assert kpi["total_answered"] == 18
        assert kpi["total_drafted"] == 13   # draft + approved
        assert kpi["total_insufficient"] == 5

    def test_kpi_coverage_pct(self):
        r = self._run()
        assert r["kpi"]["coverage_pct"] == 65.0  # 13 / 20

    def test_kpi_high_confidence_pct(self):
        """8 answers have confidence >= 70 AND are draft/approved (out of 13 drafted)."""
        r = self._run()
        assert r["kpi"]["high_confidence_pct"] == 61.5  # 8 / 13

    def test_kpi_insufficient_pct(self):
        r = self._run()
        assert r["kpi"]["insufficient_pct"] == 25.0  # 5 / 20

    def test_kpi_blind_spot_count(self):
        r = self._run()
        assert r["kpi"]["blind_spot_count"] == 5

    # ── Framework coverage ─────────────────────────────────────────────────

    def test_framework_coverage_has_five_frameworks(self):
        r = self._run()
        assert len(r["framework_coverage"]) == 5

    def test_framework_coverage_sorted_by_total_desc(self):
        r = self._run()
        totals = [fc["total"] for fc in r["framework_coverage"]]
        assert totals == sorted(totals, reverse=True)

    def test_soc2_stats(self):
        r = self._run()
        soc2 = next(fc for fc in r["framework_coverage"] if fc["framework"] == "SOC 2")
        assert soc2 == {
            "framework": "SOC 2",
            "total": 9,
            "drafted": 7,
            "insufficient": 2,
            "coverage_pct": 77.8,
        }

    def test_iso27001_stats(self):
        r = self._run()
        iso = next(fc for fc in r["framework_coverage"] if fc["framework"] == "ISO 27001")
        assert iso["total"] == 4
        assert iso["drafted"] == 3
        assert iso["insufficient"] == 1
        assert iso["coverage_pct"] == 75.0

    def test_gdpr_stats(self):
        r = self._run()
        gdpr = next(fc for fc in r["framework_coverage"] if fc["framework"] == "GDPR")
        assert gdpr["total"] == 3
        assert gdpr["drafted"] == 2
        assert gdpr["insufficient"] == 1
        assert gdpr["coverage_pct"] == 66.7

    def test_hipaa_full_coverage(self):
        r = self._run()
        hipaa = next(fc for fc in r["framework_coverage"] if fc["framework"] == "HIPAA")
        assert hipaa["coverage_pct"] == 100.0
        assert hipaa["insufficient"] == 0
        assert hipaa["total"] == 2

    def test_pci_dss_via_signal_fallback(self):
        """Answer 14 has no categories; signal_map provides PCI DSS."""
        r = self._run()
        pci = next(fc for fc in r["framework_coverage"] if fc["framework"] == "PCI DSS")
        assert pci == {
            "framework": "PCI DSS",
            "total": 1,
            "drafted": 0,
            "insufficient": 1,
            "coverage_pct": 0.0,
        }

    # ── Blind spots ────────────────────────────────────────────────────────

    def test_blind_spot_subjects(self):
        r = self._run()
        subjects = {bs["subject"] for bs in r["blind_spots"]}
        assert subjects == {
            "Business Continuity / Disaster Recovery",
            "Incident Response",
            "Breach Notification",
            "Data Retention / Disposal",
            "Physical Security",
        }

    def test_blind_spot_insufficient_counts(self):
        r = self._run()
        for bs in r["blind_spots"]:
            assert bs["insufficient_count"] == 1
            assert bs["total"] >= 1

    # ── Weak areas ─────────────────────────────────────────────────────────

    def test_weak_areas_only_vendor_management(self):
        """Only Vendor Management has avg confidence < 60 with >= 2 answers."""
        r = self._run()
        assert len(r["weak_areas"]) == 1
        wa = r["weak_areas"][0]
        assert wa["subject"] == "Vendor Management"
        assert wa["avg_confidence"] == 42.5  # (30 + 55) / 2
        assert wa["count"] == 2

    # ── Evidence strength ──────────────────────────────────────────────────

    def test_evidence_strength_count(self):
        r = self._run()
        assert len(r["evidence_strength"]) == 5

    def test_evidence_strength_sorted_desc(self):
        r = self._run()
        avgs = [e["avg_evidence_count"] for e in r["evidence_strength"]]
        assert avgs == sorted(avgs, reverse=True)

    def test_evidence_strength_top_is_encryption(self):
        """Encryption: avg (5+3)/2 = 4.0 citations."""
        r = self._run()
        top = r["evidence_strength"][0]
        assert top["subject"] == "Encryption"
        assert top["avg_evidence_count"] == 4.0
        assert top["total_answers"] == 2

    def test_evidence_strength_bottom_is_vendor_management(self):
        """Vendor Management: avg (0+1)/2 = 0.5 citations."""
        r = self._run()
        bottom = r["evidence_strength"][-1]
        assert bottom["subject"] == "Vendor Management"
        assert bottom["avg_evidence_count"] == 0.5

    # ── Trends (cumulative daily) ──────────────────────────────────────────

    def test_trends_four_days(self):
        r = self._run()
        assert len(r["trends"]) == 4

    def test_trends_dates_ascending(self):
        r = self._run()
        dates = [t["date"] for t in r["trends"]]
        assert dates == sorted(dates)

    def test_trends_day1_perfect_coverage(self):
        """Day 1: 3 drafted, 0 insufficient → 100% cumulative coverage."""
        r = self._run()
        t = r["trends"][0]
        assert t["date"] == "2026-03-20"
        assert t["coverage_pct"] == 100.0
        assert t["insufficient_pct"] == 0.0
        assert t["low_confidence_pct"] == 0.0

    def test_trends_day2_cumulative(self):
        """Day 2: running_drafted=8, running_insuff=1, running_total=9, running_low_conf=1."""
        r = self._run()
        t = r["trends"][1]
        assert t["date"] == "2026-03-21"
        assert t["coverage_pct"] == 88.9   # 8/9
        assert t["insufficient_pct"] == 11.1  # 1/9
        assert t["low_confidence_pct"] == 11.1  # 1/9

    def test_trends_day3_cumulative(self):
        """Day 3: running_drafted=11, running_insuff=4, running_total=15, running_low_conf=1."""
        r = self._run()
        t = r["trends"][2]
        assert t["date"] == "2026-03-22"
        assert t["coverage_pct"] == 73.3   # 11/15
        assert t["insufficient_pct"] == 26.7  # 4/15
        assert t["low_confidence_pct"] == 6.7  # 1/15

    def test_trends_day4_final(self):
        """Day 4: running_drafted=13, running_insuff=5, running_total=18, running_low_conf=2."""
        r = self._run()
        t = r["trends"][3]
        assert t["date"] == "2026-03-23"
        assert t["coverage_pct"] == 72.2   # 13/18
        assert t["insufficient_pct"] == 27.8  # 5/18
        assert t["low_confidence_pct"] == 11.1  # 2/18

    # ── Drill-down ─────────────────────────────────────────────────────────

    def test_drill_down_has_entries(self):
        r = self._run()
        assert len(r["drill_down"]) > 0

    def test_drill_down_sorted_by_insufficient_desc(self):
        r = self._run()
        insuff = [d["insufficient"] for d in r["drill_down"]]
        assert insuff == sorted(insuff, reverse=True)

    def test_drill_down_vendor_management_soc2(self):
        r = self._run()
        vm = next(d for d in r["drill_down"]
                  if d["subject"] == "Vendor Management" and d["framework"] == "SOC 2")
        assert vm["questions_seen"] == 2
        assert vm["answered"] == 2
        assert vm["low_confidence"] == 1
        assert vm["insufficient"] == 0

    def test_drill_down_incident_response_soc2(self):
        r = self._run()
        ir = next(d for d in r["drill_down"]
                  if d["subject"] == "Incident Response")
        assert ir["framework"] == "SOC 2"
        assert ir["questions_seen"] == 1
        assert ir["answered"] == 0
        assert ir["insufficient"] == 1

    def test_drill_down_data_retention_pci(self):
        """Answer 14's signal fallback → PCI DSS framework in drill-down."""
        r = self._run()
        dr = next(d for d in r["drill_down"]
                  if d["subject"] == "Data Retention / Disposal")
        assert dr["framework"] == "PCI DSS"
        assert dr["insufficient"] == 1

    # ── Recommended evidence ───────────────────────────────────────────────

    def test_recommended_evidence_from_gaps(self):
        r = self._run()
        items = r["recommended_evidence"]
        assert len(items) == 3
        assert items[0]["title"] == "Vendor Risk Management Policy"
        assert items[0]["improves_questions"] == 3
        assert items[1]["title"] == "Incident Response Plan"
        assert items[1]["improves_questions"] == 2

    def test_recommended_evidence_fallback_when_no_gaps(self):
        """No EvidenceGap rows → _infer_evidence_suggestions generates suggestions."""
        r = self._run(gaps=[])
        items = r["recommended_evidence"]
        assert len(items) > 0
        titles = {it["title"] for it in items}
        assert any("Incident Response" in t for t in titles)
        for item in items:
            assert item["improves_questions"] >= 1

    # ── Edge cases ─────────────────────────────────────────────────────────

    def test_empty_workspace(self):
        r = self._run(total_q=0, answers=[], signals=[], gaps=[])
        kpi = r["kpi"]
        assert kpi["total_questions"] == 0
        assert kpi["total_answered"] == 0
        assert kpi["total_drafted"] == 0
        assert kpi["total_insufficient"] == 0
        assert kpi["coverage_pct"] == 0
        assert kpi["high_confidence_pct"] == 0
        assert kpi["insufficient_pct"] == 0
        assert kpi["blind_spot_count"] == 0
        assert r["framework_coverage"] == []
        assert r["blind_spots"] == []
        assert r["weak_areas"] == []
        assert r["evidence_strength"] == []
        assert r["trends"] == []
        assert r["drill_down"] == []

    def test_all_insufficient_zero_coverage(self):
        answers = [
            (1, 1, "insufficient_evidence", 10, _cats(["SOC 2"], ["Access Control"]), None, datetime(2026, 3, 20)),
            (2, 2, "insufficient_evidence", 15, _cats(["SOC 2"], ["Encryption"]),     None, datetime(2026, 3, 20)),
        ]
        r = self._run(total_q=5, answers=answers, signals=[], gaps=[])
        kpi = r["kpi"]
        assert kpi["total_drafted"] == 0
        assert kpi["total_insufficient"] == 2
        assert kpi["coverage_pct"] == 0.0
        assert kpi["insufficient_pct"] == 40.0  # 2/5
        assert kpi["high_confidence_pct"] == 0

    def test_no_categories_no_signal_goes_uncategorized(self):
        """Answer with no categories + no signal → Uncategorized (excluded from output)."""
        answers = [
            (1, 1, "draft", 50, None, None, datetime(2026, 3, 20)),
        ]
        r = self._run(total_q=1, answers=answers, signals=[], gaps=[])
        assert r["kpi"]["total_drafted"] == 1
        assert r["kpi"]["coverage_pct"] == 100.0
        assert r["framework_coverage"] == []
        assert r["blind_spots"] == []
        assert r["drill_down"] == []

    def test_null_confidence_excluded_from_high_conf(self):
        """Answers with confidence=None should not count as high-confidence."""
        answers = [
            (1, 1, "draft", None, _cats(["SOC 2"], ["Access Control"]), _cits(1), datetime(2026, 3, 20)),
            (2, 2, "draft", None, _cats(["SOC 2"], ["Access Control"]), _cits(1), datetime(2026, 3, 20)),
        ]
        r = self._run(total_q=2, answers=answers, signals=[], gaps=[])
        assert r["kpi"]["total_drafted"] == 2
        assert r["kpi"]["high_confidence_pct"] == 0

    def test_other_unknown_frameworks_excluded(self):
        """Frameworks named 'Other' or 'Unknown' are filtered out."""
        answers = [
            (1, 1, "draft", 80, _cats(["Other", "SOC 2"], ["Access Control"]),   _cits(1), datetime(2026, 3, 20)),
            (2, 2, "draft", 80, _cats(["Unknown"],         ["Access Control"]),   _cits(1), datetime(2026, 3, 20)),
        ]
        r = self._run(total_q=2, answers=answers, signals=[], gaps=[])
        fws = {fc["framework"] for fc in r["framework_coverage"]}
        assert "Other" not in fws
        assert "Unknown" not in fws
        assert "SOC 2" in fws

    def test_malformed_json_handled_gracefully(self):
        """Broken JSON in categories/citations should not crash."""
        answers = [
            (1, 1, "draft", 50, "NOT VALID JSON", "ALSO BAD", datetime(2026, 3, 20)),
        ]
        r = self._run(total_q=1, answers=answers, signals=[], gaps=[])
        assert r["kpi"]["total_drafted"] == 1
        assert r["framework_coverage"] == []

    def test_signal_malformed_json_handled(self):
        """Broken signal JSON should not crash — falls back to empty lists."""
        answers = [
            (1, 1, "draft", 50, None, None, datetime(2026, 3, 20)),
        ]
        signals = [(1, "NOT JSON", "ALSO BAD")]
        r = self._run(total_q=1, answers=answers, signals=signals, gaps=[])
        assert r["kpi"]["total_drafted"] == 1
