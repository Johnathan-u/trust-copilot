"""Tests for control engine (P1-31, P1-34, P1-35, P1-36)."""

import pytest
from app.core.database import SessionLocal
from app.models.workspace import Workspace
from app.models.workspace_control import WorkspaceControl
from app.services import control_engine_service as ce


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


class TestControlEngineService:
    def _get_control(self, db):
        ws = db.query(Workspace).first()
        ctrl = db.query(WorkspaceControl).filter(WorkspaceControl.workspace_id == ws.id).first()
        return ws, ctrl

    def test_evaluate_control(self, db_session):
        ws, ctrl = self._get_control(db_session)
        if not ctrl:
            pytest.skip("No workspace controls to evaluate")
        result = ce.evaluate_control(db_session, ws.id, ctrl.id)
        db_session.commit()
        assert "status" in result
        assert "confidence" in result
        assert "evidence_count" in result
        assert result["status"] in ("passing", "failing", "stale", "not_assessed")

    def test_evaluate_all(self, db_session):
        ws = db_session.query(Workspace).first()
        result = ce.evaluate_all_controls(db_session, ws.id)
        db_session.commit()
        assert "total_controls" in result
        assert "passing" in result
        assert "failing" in result
        assert "drift_count" in result

    def test_control_timeline(self, db_session):
        ws, ctrl = self._get_control(db_session)
        if not ctrl:
            pytest.skip("No workspace controls")
        ce.evaluate_control(db_session, ws.id, ctrl.id)
        db_session.commit()
        timeline = ce.get_control_timeline(db_session, ws.id, ctrl.id)
        assert isinstance(timeline, list)

    def test_drift_report(self, db_session):
        ws = db_session.query(Workspace).first()
        drifts = ce.get_drift_report(db_session, ws.id)
        assert isinstance(drifts, list)

    def test_not_found_control(self, db_session):
        ws = db_session.query(Workspace).first()
        result = ce.evaluate_control(db_session, ws.id, 99999)
        assert "error" in result


class TestControlEngineAPI:
    def test_evaluate_all(self, admin_client):
        r = admin_client.post("/api/control-engine/evaluate-all")
        assert r.status_code == 200
        assert "total_controls" in r.json()

    def test_drift_report(self, admin_client):
        r = admin_client.get("/api/control-engine/drift")
        assert r.status_code == 200
        assert "drifts" in r.json()

    def test_editor_can_read_drift(self, editor_client):
        r = editor_client.get("/api/control-engine/drift")
        assert r.status_code == 200

    def test_editor_cannot_evaluate(self, editor_client):
        r = editor_client.post("/api/control-engine/evaluate-all")
        assert r.status_code == 403
