"""Tests for connector health visibility (P1-30)."""

import pytest
from app.core.database import SessionLocal
from app.models.workspace import Workspace
from app.services import connector_health_service as ch
from app.services import source_registry_service as sr


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


class TestConnectorHealthService:
    def test_health_structure(self, db_session):
        ws = db_session.query(Workspace).first()
        sr.seed_sources(db_session, ws.id)
        db_session.commit()
        health = ch.get_connector_health(db_session, ws.id)
        assert "overall_status" in health
        assert "total_connectors" in health
        assert "connectors" in health
        assert "checked_at" in health

    def test_unknown_when_never_synced(self, db_session):
        ws = db_session.query(Workspace).first()
        sr.seed_sources(db_session, ws.id)
        sr.update_source(db_session, ws.id, "azure", enabled=True)
        db_session.commit()
        health = ch.get_connector_health(db_session, ws.id)
        azure = [c for c in health["connectors"] if c["source_type"] == "azure"]
        assert len(azure) == 1
        assert azure[0]["status"] == "unknown"

    def test_healthy_after_successful_sync(self, db_session):
        ws = db_session.query(Workspace).first()
        sr.seed_sources(db_session, ws.id)
        sr.update_source(db_session, ws.id, "slack", enabled=True)
        sr.record_sync(db_session, ws.id, "slack", True)
        db_session.commit()
        health = ch.get_connector_health(db_session, ws.id)
        slack = [c for c in health["connectors"] if c["source_type"] == "slack"]
        assert slack[0]["status"] == "healthy"

    def test_unhealthy_after_failed_sync(self, db_session):
        ws = db_session.query(Workspace).first()
        sr.seed_sources(db_session, ws.id)
        sr.update_source(db_session, ws.id, "gmail", enabled=True)
        sr.record_sync(db_session, ws.id, "gmail", False, error="token expired")
        db_session.commit()
        health = ch.get_connector_health(db_session, ws.id)
        gmail = [c for c in health["connectors"] if c["source_type"] == "gmail"]
        assert gmail[0]["status"] == "unhealthy"


class TestConnectorHealthAPI:
    def test_get_health(self, admin_client):
        admin_client.post("/api/sources/seed")
        r = admin_client.get("/api/connector-health")
        assert r.status_code == 200
        assert "overall_status" in r.json()

    def test_editor_can_access(self, editor_client, admin_client):
        admin_client.post("/api/sources/seed")
        r = editor_client.get("/api/connector-health")
        assert r.status_code == 200
