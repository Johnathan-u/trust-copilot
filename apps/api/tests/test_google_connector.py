"""Tests for Google Workspace connector (P1-27, P1-28, P1-29)."""

import pytest
from app.services import google_workspace_collector_service as gw


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


class TestGoogleCollectorService:
    def test_collect_users(self):
        result = gw.collect_users("test.com")
        assert result["source"] == "google.users"
        assert len(result["findings"]) >= 3

    def test_collect_mfa(self):
        result = gw.collect_mfa_enrollment()
        assert result["source"] == "google.mfa"

    def test_collect_admin_roles(self):
        result = gw.collect_admin_roles()
        assert result["source"] == "google.admin_roles"

    def test_full_sync(self):
        result = gw.run_google_sync(1, "test.com")
        assert result["total_findings"] >= 7


class TestGoogleConnectorAPI:
    def test_users(self, admin_client):
        r = admin_client.get("/api/connectors/google/users")
        assert r.status_code == 200

    def test_mfa(self, admin_client):
        r = admin_client.get("/api/connectors/google/mfa")
        assert r.status_code == 200

    def test_admin_roles(self, admin_client):
        r = admin_client.get("/api/connectors/google/admin-roles")
        assert r.status_code == 200

    def test_sync(self, admin_client):
        r = admin_client.post("/api/connectors/google/sync")
        assert r.status_code == 200
        assert r.json()["total_findings"] >= 7

    def test_editor_cannot_sync(self, editor_client):
        r = editor_client.post("/api/connectors/google/sync")
        assert r.status_code == 403
