"""Tests for control timeline view (P1-40)."""

import pytest
from app.models.workspace import Workspace
from app.models.workspace_control import WorkspaceControl
from app.services import control_timeline_service as ct


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200
    return client


class TestControlTimelineService:
    def test_timeline_not_found(self, db_session):
        ws = db_session.query(Workspace).first()
        result = ct.get_control_timeline(db_session, ws.id, 999999)
        assert result.get("error") == "Control not found"

    def test_timeline_returns_events(self, db_session):
        ws = db_session.query(Workspace).first()
        wc = db_session.query(WorkspaceControl).filter(
            WorkspaceControl.workspace_id == ws.id
        ).first()
        if not wc:
            pytest.skip("No workspace controls")
        result = ct.get_control_timeline(db_session, ws.id, wc.id)
        assert "events" in result
        assert "control_id" in result
        assert "current_status" in result

    def test_timeline_includes_review_if_present(self, db_session):
        ws = db_session.query(Workspace).first()
        wc = db_session.query(WorkspaceControl).filter(
            WorkspaceControl.workspace_id == ws.id,
            WorkspaceControl.last_reviewed_at.isnot(None),
        ).first()
        if not wc:
            pytest.skip("No reviewed workspace controls")
        result = ct.get_control_timeline(db_session, ws.id, wc.id)
        types = [e["type"] for e in result["events"]]
        assert "reviewed" in types


class TestControlTimelineAPI:
    def test_get_timeline(self, admin_client, db_session):
        # Admin session is always workspace_id=1 (see conftest seed).
        ws = db_session.query(Workspace).filter(Workspace.id == 1).first()
        wc = db_session.query(WorkspaceControl).filter(
            WorkspaceControl.workspace_id == ws.id
        ).first()
        if not wc:
            pytest.skip("No workspace controls")
        r = admin_client.get(f"/api/control-timeline/{wc.id}")
        assert r.status_code == 200
        assert "events" in r.json()

    def test_not_found(self, admin_client):
        r = admin_client.get("/api/control-timeline/999999")
        assert r.status_code == 404
