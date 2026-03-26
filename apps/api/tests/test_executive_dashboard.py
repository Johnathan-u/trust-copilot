"""Tests for executive dashboard (P0-87)."""

import pytest
from app.core.database import SessionLocal
from app.services import executive_dashboard_service as eds


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    return client


@pytest.fixture
def editor_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
    assert r.status_code == 200, f"Editor login failed: {r.text}"
    return client


class TestExecutiveDashboardService:
    def test_dashboard_structure(self):
        db = SessionLocal()
        try:
            data = eds.get_executive_dashboard(db)
            assert "platform" in data
            assert "revenue" in data
            assert "content" in data
            assert "generated_at" in data
        finally:
            db.close()

    def test_platform_metrics(self):
        db = SessionLocal()
        try:
            data = eds.get_executive_dashboard(db)
            p = data["platform"]
            assert "total_workspaces" in p
            assert "total_documents" in p
            assert "total_questionnaires" in p
            assert p["total_workspaces"] >= 1
        finally:
            db.close()

    def test_revenue_metrics(self):
        db = SessionLocal()
        try:
            data = eds.get_executive_dashboard(db)
            r = data["revenue"]
            assert "active_subscriptions" in r
            assert "total_credits_consumed" in r
        finally:
            db.close()

    def test_content_metrics(self):
        db = SessionLocal()
        try:
            data = eds.get_executive_dashboard(db)
            c = data["content"]
            assert "total_questions" in c
            assert "total_answers" in c
            assert "evidence_gaps" in c
            assert "coverage_pct" in c
        finally:
            db.close()


class TestExecutiveDashboardAPI:
    def test_get_dashboard(self, admin_client):
        r = admin_client.get("/api/executive-dashboard")
        assert r.status_code == 200
        data = r.json()
        assert "platform" in data

    def test_editor_cannot_access(self, editor_client):
        r = editor_client.get("/api/executive-dashboard")
        assert r.status_code == 403
