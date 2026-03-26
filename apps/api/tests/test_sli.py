"""Tests for SLI service (P2-101)."""

import pytest
from app.services import sli_service as sli


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


class TestSliService:
    def test_get_slis(self, db_session):
        result = sli.get_slis(db_session)
        assert "slis" in result
        assert "error_budget" in result
        assert "on_call" in result
        assert "jobs_7d" in result


class TestSliAPI:
    def test_get(self, admin_client):
        r = admin_client.get("/api/sli")
        assert r.status_code == 200
        assert "slis" in r.json()

    def test_editor_cannot_access(self, editor_client):
        r = editor_client.get("/api/sli")
        assert r.status_code == 403
