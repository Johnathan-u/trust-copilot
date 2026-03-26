"""Tests for credit burn and overage prompts (P1-62)."""

import pytest
from app.models.workspace import Workspace
from app.services import credit_prompt_service as cp


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


class TestCreditPromptService:
    def test_status_structure(self, db_session):
        ws = db_session.query(Workspace).first()
        status = cp.get_credit_status(db_session, ws.id)
        assert "balance" in status
        assert "monthly_allocation" in status
        assert "burn_pct" in status
        assert "remaining_pct" in status
        assert "is_exhausted" in status
        assert "severity" in status


class TestCreditPromptAPI:
    def test_get_status(self, admin_client):
        r = admin_client.get("/api/credit-status")
        assert r.status_code == 200
        assert "balance" in r.json()

    def test_editor_can_access(self, editor_client):
        r = editor_client.get("/api/credit-status")
        assert r.status_code == 200
