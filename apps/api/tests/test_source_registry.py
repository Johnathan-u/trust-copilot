"""Tests for source registry (P0-05)."""

import pytest
from app.core.database import SessionLocal
from app.models.workspace import Workspace
from app.services import source_registry_service as sr


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


class TestSourceRegistryService:
    def _get_workspace(self, db):
        ws = db.query(Workspace).first()
        assert ws, "Need at least one workspace"
        return ws

    def test_seed_sources(self, db_session):
        ws = self._get_workspace(db_session)
        created = sr.seed_sources(db_session, ws.id)
        db_session.commit()
        assert created >= 0
        sources = sr.list_sources(db_session, ws.id)
        assert len(sources) >= len(sr.KNOWN_SOURCES)
        second = sr.seed_sources(db_session, ws.id)
        assert second == 0

    def test_list_sources(self, db_session):
        ws = self._get_workspace(db_session)
        sr.seed_sources(db_session, ws.id)
        db_session.commit()
        sources = sr.list_sources(db_session, ws.id)
        assert isinstance(sources, list)
        assert all("source_type" in s for s in sources)

    def test_get_source(self, db_session):
        ws = self._get_workspace(db_session)
        sr.seed_sources(db_session, ws.id)
        db_session.commit()
        result = sr.get_source(db_session, ws.id, "slack")
        assert result is not None
        assert result["source_type"] == "slack"
        assert result["auth_method"] == "bot_token"

    def test_update_source(self, db_session):
        ws = self._get_workspace(db_session)
        sr.seed_sources(db_session, ws.id)
        db_session.commit()
        updated = sr.update_source(db_session, ws.id, "slack", enabled=True, sync_cadence="daily")
        db_session.commit()
        assert updated is not None
        assert updated["enabled"] is True
        assert updated["sync_cadence"] == "daily"

    def test_record_sync(self, db_session):
        ws = self._get_workspace(db_session)
        sr.seed_sources(db_session, ws.id)
        db_session.commit()
        sr.record_sync(db_session, ws.id, "gmail", True)
        db_session.commit()
        src = sr.get_source(db_session, ws.id, "gmail")
        assert src["last_sync_status"] == "success"
        assert src["last_error"] is None
        sr.record_sync(db_session, ws.id, "gmail", False, error="quota exceeded")
        db_session.commit()
        src = sr.get_source(db_session, ws.id, "gmail")
        assert src["last_sync_status"] == "failed"
        assert "quota" in src["last_error"]

    def test_health_summary(self, db_session):
        ws = self._get_workspace(db_session)
        sr.seed_sources(db_session, ws.id)
        db_session.commit()
        health = sr.get_health_summary(db_session, ws.id)
        assert "total_sources" in health
        assert health["total_sources"] >= len(sr.KNOWN_SOURCES)

    def test_enabled_only_filter(self, db_session):
        ws = self._get_workspace(db_session)
        sr.seed_sources(db_session, ws.id)
        sr.update_source(db_session, ws.id, "slack", enabled=True)
        db_session.commit()
        enabled = sr.list_sources(db_session, ws.id, enabled_only=True)
        assert all(s["enabled"] for s in enabled)

    def test_known_sources_have_required_fields(self):
        for src in sr.KNOWN_SOURCES:
            assert "source_type" in src
            assert "display_name" in src
            assert "auth_method" in src
            assert "failure_modes" in src
            assert "object_types" in src


class TestSourceRegistryAPI:
    def test_list_sources(self, admin_client):
        r = admin_client.post("/api/sources/seed")
        assert r.status_code == 200
        r = admin_client.get("/api/sources")
        assert r.status_code == 200
        assert "sources" in r.json()

    def test_get_source(self, admin_client):
        admin_client.post("/api/sources/seed")
        r = admin_client.get("/api/sources/slack")
        assert r.status_code == 200
        assert r.json()["source_type"] == "slack"

    def test_update_source(self, admin_client):
        admin_client.post("/api/sources/seed")
        r = admin_client.patch("/api/sources/slack", json={"enabled": True})
        assert r.status_code == 200
        assert r.json()["enabled"] is True

    def test_health_endpoint(self, admin_client):
        admin_client.post("/api/sources/seed")
        r = admin_client.get("/api/sources/health")
        assert r.status_code == 200
        assert "total_sources" in r.json()

    def test_seed_idempotent(self, admin_client):
        r1 = admin_client.post("/api/sources/seed")
        r2 = admin_client.post("/api/sources/seed")
        assert r2.json()["created"] == 0

    def test_editor_cannot_seed(self, editor_client):
        r = editor_client.post("/api/sources/seed")
        assert r.status_code == 403

    def test_editor_can_read(self, editor_client, admin_client):
        admin_client.post("/api/sources/seed")
        r = editor_client.get("/api/sources")
        assert r.status_code == 200

    def test_not_found_source(self, admin_client):
        r = admin_client.get("/api/sources/nonexistent")
        assert r.status_code == 404
