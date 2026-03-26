"""Tests for evidence freshness policies (P1-43)."""

import pytest
from app.models.workspace import Workspace
from app.services import freshness_policy_service as svc


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


class TestFreshnessPolicyService:
    def test_set_policy(self, db_session):
        ws = db_session.query(Workspace).first()
        result = svc.set_policy(db_session, ws.id, "integration", 7, 2)
        db_session.commit()
        assert result["source_type"] == "integration"
        assert result["max_age_days"] == 7

    def test_update_existing_policy(self, db_session):
        ws = db_session.query(Workspace).first()
        svc.set_policy(db_session, ws.id, "manual", 180, 30)
        db_session.commit()
        result = svc.set_policy(db_session, ws.id, "manual", 90, 14)
        db_session.commit()
        assert result["max_age_days"] == 90

    def test_get_policies(self, db_session):
        ws = db_session.query(Workspace).first()
        svc.set_policy(db_session, ws.id, "ai", 30, 7)
        db_session.commit()
        policies = svc.get_policies(db_session, ws.id)
        assert len(policies) >= 1

    def test_effective_policy_default(self, db_session):
        ws = db_session.query(Workspace).first()
        result = svc.get_effective_policy(db_session, ws.id, "unknown_type")
        assert "max_age_days" in result
        assert result.get("is_default") is True

    def test_evaluate_freshness(self, db_session):
        ws = db_session.query(Workspace).first()
        results = svc.evaluate_freshness(db_session, ws.id)
        assert isinstance(results, list)

    def test_delete_policy(self, db_session):
        ws = db_session.query(Workspace).first()
        svc.set_policy(db_session, ws.id, "document", 180)
        db_session.commit()
        assert svc.delete_policy(db_session, ws.id, "document") is True
        db_session.commit()
        assert svc.delete_policy(db_session, ws.id, "document") is False


class TestFreshnessPolicyAPI:
    def test_set_policy(self, admin_client):
        r = admin_client.post("/api/freshness-policies", json={
            "source_type": "integration", "max_age_days": 7, "warn_before_days": 2,
        })
        assert r.status_code == 200
        assert r.json()["source_type"] == "integration"

    def test_list_policies(self, admin_client):
        r = admin_client.get("/api/freshness-policies")
        assert r.status_code == 200
        assert "policies" in r.json()

    def test_effective(self, admin_client):
        r = admin_client.get("/api/freshness-policies/effective?source_type=manual")
        assert r.status_code == 200
        assert "max_age_days" in r.json()

    def test_evaluate(self, admin_client):
        r = admin_client.get("/api/freshness-policies/evaluate")
        assert r.status_code == 200
        assert "results" in r.json()

    def test_editor_cannot_set(self, editor_client):
        r = editor_client.post("/api/freshness-policies", json={
            "source_type": "ai", "max_age_days": 30,
        })
        assert r.status_code == 403
