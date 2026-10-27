"""TC-01-005 service-level evidence (no DB, no network).

Run from apps/api:
  TRUST_COPILOT_TESTING=1 DATABASE_URL=postgresql://x:x@127.0.0.1:1/none SESSION_SECRET=x \
    python ../../artifacts/acceptance/TC-01-005/service_label_check.py
Mirrors the assertions in tests/test_roi_calculator.py, tests/test_demo_proof.py and
tests/test_security_page.py that do not need a database, plus the new labels.
"""

from unittest.mock import patch

from app.services import demo_proof_service as dp
from app.services import roi_calculator_service as roi
from app.services import security_page_service as sp

r = roi.calculate_roi()
assert r["savings"]["time_reduction_pct"] > 90 and r["savings"]["roi_multiple"] > 0
assert r["estimate_basis"]["type"] == "illustrative"
r = roi.calculate_roi(questionnaires_per_year=20, hours_per_questionnaire=5)
assert (
    r["manual"]["total_hours_per_year"] == 100
    and r["with_trust_copilot"]["total_hours_per_year"] == 10
)

q = dp._build_sample_questionnaire()
assert q["title"] == "Sample SOC 2 Security Questionnaire"
assert q["data_basis"] == "synthetic_example" and "disclaimer" in q and "confidence_basis" in q
assert not any("validated by automated" in x["answer"] for x in q["questions"])
c = dp._build_coverage_report(q)
assert c["coverage_pct"] == 100.0
assert c["high_confidence"] + c["medium_confidence"] + c["low_confidence"] == c["total_questions"]
assert c["data_basis"] == "synthetic_example"
assert dp._build_gap_list(q)["data_basis"] == "synthetic_example"
assert len(dp._build_walkthrough()["steps"]) == 5

faq = [{"category": "data_storage", "question": "q", "answer": "a", "framework_tags": "SOC2"}]
with (
    patch.object(sp.faq_svc, "list_faqs", return_value=faq),
    patch.object(sp.faq_svc, "get_categories", return_value=[]),
):
    p = sp.get_public_security_page(None, 1)
assert p["title"] == "Security & Data Handling"
assert len(p["certifications"]) >= 3 and any(
    x["name"] == "SOC 2 Type II" for x in p["certifications"]
)
assert all(x["status"] == "not_attested" for x in p["certifications"])
assert len(p["infrastructure_highlights"]) >= 5 and any(
    "AES-256" in h for h in p["infrastructure_highlights"]
)
assert (
    p["contact"]["dpa_available"] is False and p["contact"]["subprocessor_list_available"] is False
)
assert "notice" in p
print("PASS: service-level label checks (ROI, demo proof, security page)")
