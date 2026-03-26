"""Tests for Trust Center analytics (P1-67)."""

import pytest
from app.models.workspace import Workspace
from app.services import trust_center_analytics_service as tca


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


class TestTrustCenterAnalyticsService:
    def test_get_analytics(self, db_session):
        ws = db_session.query(Workspace).first()
        result = tca.get_trust_center_analytics(db_session, ws.id)
        assert "total_articles" in result
        assert "published" in result
        assert "access_requests" in result


class TestTrustCenterAnalyticsAPI:
    def test_get_analytics(self, admin_client):
        r = admin_client.get("/api/trust-center-analytics")
        assert r.status_code == 200
        assert "total_articles" in r.json()

    def test_editor_cannot_access(self, editor_client):
        r = editor_client.get("/api/trust-center-analytics")
        assert r.status_code == 403
