"""Tests for evidence retention and archiving (P1-51)."""

import pytest
from app.models.workspace import Workspace
from app.services import retention_service as svc


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


class TestRetentionService:
    def test_set_policy(self, db_session):
        ws = db_session.query(Workspace).first()
        result = svc.set_policy(db_session, ws.id, retention_days=365, archive_after_days=180)
        db_session.commit()
        assert result["retention_days"] == 365
        assert result["archive_after_days"] == 180

    def test_set_source_policy(self, db_session):
        ws = db_session.query(Workspace).first()
        result = svc.set_policy(db_session, ws.id, retention_days=90, source_type="slack")
        db_session.commit()
        assert result["source_type"] == "slack"
        assert result["retention_days"] == 90

    def test_get_policies(self, db_session):
        ws = db_session.query(Workspace).first()
        svc.set_policy(db_session, ws.id, retention_days=365)
        db_session.commit()
        policies = svc.get_policies(db_session, ws.id)
        assert len(policies) >= 1

    def test_evaluate_retention(self, db_session):
        ws = db_session.query(Workspace).first()
        result = svc.evaluate_retention(db_session, ws.id)
        assert "total" in result
        assert "to_archive" in result
        assert "to_delete" in result

    def test_run_archival(self, db_session):
        ws = db_session.query(Workspace).first()
        result = svc.run_archival(db_session, ws.id)
        db_session.commit()
        assert "archived" in result

    def test_dry_run_deletion(self, db_session):
        ws = db_session.query(Workspace).first()
        result = svc.run_deletion(db_session, ws.id, dry_run=True)
        assert result["dry_run"] is True


class TestRetentionAPI:
    def test_set_policy(self, admin_client):
        r = admin_client.post("/api/retention/policies", json={
            "retention_days": 365, "archive_after_days": 180,
        })
        assert r.status_code == 200

    def test_list_policies(self, admin_client):
        r = admin_client.get("/api/retention/policies")
        assert r.status_code == 200
        assert "policies" in r.json()

    def test_evaluate(self, admin_client):
        r = admin_client.get("/api/retention/evaluate")
        assert r.status_code == 200
        assert "total" in r.json()

    def test_archive(self, admin_client):
        r = admin_client.post("/api/retention/archive")
        assert r.status_code == 200

    def test_delete_dry_run(self, admin_client):
        r = admin_client.post("/api/retention/delete?dry_run=true")
        assert r.status_code == 200
        assert r.json()["dry_run"] is True

    def test_editor_cannot_evaluate(self, editor_client):
        r = editor_client.get("/api/retention/evaluate")
        assert r.status_code == 403
