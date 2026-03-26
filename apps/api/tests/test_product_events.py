"""Tests for product events (P0-86)."""

import pytest
from app.core.database import SessionLocal
from app.models.workspace import Workspace
from app.services import product_event_service as pe


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


class TestProductEventService:
    def _get_workspace(self, db):
        ws = db.query(Workspace).first()
        assert ws
        return ws

    def test_track_event(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            pe.track(db, ws.id, "auth.login", event_category="auth", user_id=1)
            db.commit()
            counts = pe.get_event_counts(db, ws.id, days=1)
            assert "auth.login" in counts
            assert counts["auth.login"] >= 1
        finally:
            db.close()

    def test_category_counts(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            pe.track(db, ws.id, "document.upload", event_category="document")
            pe.track(db, ws.id, "document.delete", event_category="document")
            db.commit()
            cats = pe.get_category_counts(db, ws.id, days=1)
            assert "document" in cats
            assert cats["document"] >= 2
        finally:
            db.close()

    def test_daily_activity(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            pe.track(db, ws.id, "daily.test", event_category="general")
            db.commit()
            activity = pe.get_daily_activity(db, ws.id, days=1)
            assert isinstance(activity, list)
        finally:
            db.close()

    def test_funnel(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            pe.track(db, ws.id, "auth.login", event_category="auth")
            pe.track(db, ws.id, "document.upload", event_category="document")
            pe.track(db, ws.id, "answer.generate", event_category="answer")
            pe.track(db, ws.id, "export.complete", event_category="export")
            db.commit()
            funnel = pe.get_funnel(db, ws.id, days=1)
            assert "logins" in funnel
            assert "document_uploads" in funnel
            assert "answers_generated" in funnel
            assert "exports" in funnel
        finally:
            db.close()


class TestProductEventAPI:
    def test_track(self, admin_client):
        r = admin_client.post("/api/events", json={
            "event_type": "test.api.track",
            "event_category": "general",
        })
        assert r.status_code == 200
        assert r.json()["tracked"] is True

    def test_counts(self, admin_client):
        r = admin_client.get("/api/events/counts")
        assert r.status_code == 200
        assert "counts" in r.json()

    def test_categories(self, admin_client):
        r = admin_client.get("/api/events/categories")
        assert r.status_code == 200
        assert "categories" in r.json()

    def test_daily(self, admin_client):
        r = admin_client.get("/api/events/daily")
        assert r.status_code == 200
        assert "activity" in r.json()

    def test_funnel(self, admin_client):
        r = admin_client.get("/api/events/funnel")
        assert r.status_code == 200
        assert "logins" in r.json()

    def test_editor_can_track(self, editor_client):
        r = editor_client.post("/api/events", json={
            "event_type": "test.editor.track",
        })
        assert r.status_code == 200

    def test_editor_cannot_view_counts(self, editor_client):
        r = editor_client.get("/api/events/counts")
        assert r.status_code == 403
