"""Tests for the demo proof package system (P0-13)."""

import pytest


@pytest.fixture
def auth_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200
    return client


class TestDemoProofService:
    def test_sample_questionnaire_structure(self):
        from app.services.demo_proof_service import _build_sample_questionnaire
        q = _build_sample_questionnaire()
        assert q["title"] == "Sample SOC 2 Security Questionnaire"
        assert q["total_questions"] >= 10
        for question in q["questions"]:
            assert "section" in question
            assert "question" in question
            assert "answer" in question
            assert "confidence" in question
            assert "evidence_sources" in question

    def test_coverage_report(self):
        from app.services.demo_proof_service import _build_sample_questionnaire, _build_coverage_report
        q = _build_sample_questionnaire()
        report = _build_coverage_report(q)
        assert report["total_questions"] == q["total_questions"]
        assert report["coverage_pct"] == 100.0
        assert report["avg_confidence"] > 0
        assert report["high_confidence"] + report["medium_confidence"] + report["low_confidence"] == report["total_questions"]
        assert len(report["by_section"]) >= 4

    def test_gap_list(self):
        from app.services.demo_proof_service import _build_sample_questionnaire, _build_gap_list
        q = _build_sample_questionnaire()
        gaps = _build_gap_list(q)
        assert "total_gaps" in gaps
        assert "gaps" in gaps
        for gap in gaps["gaps"]:
            assert gap["confidence"] < 85
            assert "recommendation" in gap

    def test_walkthrough(self):
        from app.services.demo_proof_service import _build_walkthrough
        w = _build_walkthrough()
        assert len(w["steps"]) == 5
        for step in w["steps"]:
            assert "step" in step
            assert "title" in step
            assert "description" in step

    def test_generate_full_package(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.demo_proof_service import generate_demo_package
        db = SessionLocal()
        try:
            pkg = generate_demo_package(db, 1)
            assert "sample_questionnaire" in pkg
            assert "coverage_report" in pkg
            assert "gap_list" in pkg
            assert "walkthrough" in pkg
            assert "live_stats" in pkg
            assert pkg["live_stats"]["questionnaires_processed"] >= 0
        finally:
            db.close()


class TestDemoProofAPI:
    def test_full_package(self, auth_client):
        r = auth_client.get("/api/demo-proof")
        assert r.status_code == 200
        data = r.json()
        assert "sample_questionnaire" in data
        assert "coverage_report" in data
        assert "gap_list" in data
        assert "walkthrough" in data
        assert "live_stats" in data

    def test_questionnaire_endpoint(self, auth_client):
        r = auth_client.get("/api/demo-proof/questionnaire")
        assert r.status_code == 200
        assert r.json()["total_questions"] >= 10

    def test_coverage_endpoint(self, auth_client):
        r = auth_client.get("/api/demo-proof/coverage")
        assert r.status_code == 200
        assert "coverage_pct" in r.json()

    def test_gaps_endpoint(self, auth_client):
        r = auth_client.get("/api/demo-proof/gaps")
        assert r.status_code == 200
        assert "total_gaps" in r.json()

    def test_walkthrough_endpoint(self, auth_client):
        r = auth_client.get("/api/demo-proof/walkthrough")
        assert r.status_code == 200
        assert len(r.json()["steps"]) == 5

    def test_unauthenticated(self, client):
        r = client.get("/api/demo-proof")
        assert r.status_code == 401
