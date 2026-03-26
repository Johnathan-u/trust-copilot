"""Tests for reuse analytics (P1-78)."""

import pytest
from app.models.workspace import Workspace
from app.services import reuse_analytics_service as ra


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200
    return client


@pytest.fixture
def editor_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
    assert r.status_code == 200
    return client


class TestReuseAnalyticsService:
    def test_get_analytics(self, db_session):
        ws = db_session.query(Workspace).first()
        result = ra.get_reuse_analytics(db_session, ws.id)
        assert "total_golden_answers" in result
        assert "reuse_rate" in result
        assert "by_category" in result
        assert "top_reused" in result


class TestReuseAnalyticsAPI:
    def test_get(self, admin_client):
        r = admin_client.get("/api/reuse-analytics")
        assert r.status_code == 200
        assert "total_golden_answers" in r.json()

    def test_editor_cannot_access(self, editor_client):
        r = editor_client.get("/api/reuse-analytics")
        assert r.status_code == 403
