"""Tests for CRM connectors (E1-02, E1-03)."""

import pytest

from app.models.workspace import Workspace
from app.services import crm_connector_service as svc


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


class TestCRMConnectorService:
    def test_sync_salesforce(self, db_session):
        ws = db_session.query(Workspace).first()
        before = svc.get_sync_status(db_session, ws.id)["salesforce"]
        result = svc.sync_salesforce(db_session, ws.id)
        db_session.commit()
        assert result["source"] == "salesforce"
        assert result["synced"] == 0
        assert result["details"]
        assert all(item["action"] == "rejected" for item in result["details"])
        assert svc.get_sync_status(db_session, ws.id)["salesforce"] == before

    def test_sync_hubspot(self, db_session):
        ws = db_session.query(Workspace).first()
        before = svc.get_sync_status(db_session, ws.id)["hubspot"]
        result = svc.sync_hubspot(db_session, ws.id)
        db_session.commit()
        assert result["source"] == "hubspot"
        assert result["synced"] == 0
        assert all(item["action"] == "rejected" for item in result["details"])
        assert svc.get_sync_status(db_session, ws.id)["hubspot"] == before

    def test_idempotent_sync(self, db_session):
        ws = db_session.query(Workspace).first()
        before = svc.get_sync_status(db_session, ws.id)["salesforce"]
        svc.sync_salesforce(db_session, ws.id)
        db_session.commit()
        result = svc.sync_salesforce(db_session, ws.id)
        db_session.commit()
        assert result["synced"] == 0
        assert all(item["action"] == "rejected" for item in result["details"])
        assert svc.get_sync_status(db_session, ws.id)["salesforce"] == before

    def test_sync_status(self, db_session):
        ws = db_session.query(Workspace).first()
        before = svc.get_sync_status(db_session, ws.id)
        svc.sync_salesforce(db_session, ws.id)
        svc.sync_hubspot(db_session, ws.id)
        db_session.commit()
        status = svc.get_sync_status(db_session, ws.id)
        assert status["salesforce"] == before["salesforce"]
        assert status["hubspot"] == before["hubspot"]
        assert "total" in status


class TestCRMAPI:
    def test_sync_salesforce(self, admin_client):
        r = admin_client.post("/api/crm/sync/salesforce")
        assert r.status_code == 200
        assert r.json()["source"] == "salesforce"

    def test_sync_hubspot(self, admin_client):
        r = admin_client.post("/api/crm/sync/hubspot")
        assert r.status_code == 200
        assert r.json()["source"] == "hubspot"

    def test_status(self, admin_client):
        r = admin_client.get("/api/crm/status")
        assert r.status_code == 200
        assert "total" in r.json()

    def test_editor_cannot_sync(self, editor_client):
        r = editor_client.post("/api/crm/sync/salesforce")
        assert r.status_code == 403
