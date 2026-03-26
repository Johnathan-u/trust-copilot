"""Tests for proof widgets (P0-85)."""

import pytest
from app.core.database import SessionLocal
from app.models.workspace import Workspace
from app.services import proof_widgets_service as pw


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


class TestProofWidgetsService:
    def _get_workspace(self, db):
        ws = db.query(Workspace).first()
        assert ws
        return ws

    def test_widgets_structure(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            data = pw.get_proof_widgets(db, ws.id)
            assert "questions_answered" in data
            assert "questionnaires_processed" in data
            assert "documents_indexed" in data
            assert "exports_delivered" in data
            assert "hours_saved_estimate" in data
            assert "coverage_pct" in data
            assert "generated_at" in data
        finally:
            db.close()

    def test_hours_saved_calculation(self):
        db = SessionLocal()
        try:
            ws = self._get_workspace(db)
            data = pw.get_proof_widgets(db, ws.id)
            expected = round(data["questions_answered"] * 0.08, 1)
            assert data["hours_saved_estimate"] == expected
        finally:
            db.close()


class TestProofWidgetsAPI:
    def test_get_widgets(self, admin_client):
        r = admin_client.get("/api/proof-widgets")
        assert r.status_code == 200
        data = r.json()
        assert "questions_answered" in data

    def test_editor_can_access(self, editor_client):
        r = editor_client.get("/api/proof-widgets")
        assert r.status_code == 200
