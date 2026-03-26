"""Tests for monitoring scheduler (P1-33)."""

import pytest
from app.models.workspace import Workspace
from app.services import monitoring_scheduler_service as ms


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


class TestMonitoringService:
    def test_run_daily_checks(self, db_session):
        ws = db_session.query(Workspace).first()
        result = ms.run_daily_checks(db_session, ws.id)
        db_session.commit()
        assert "checks" in result
        assert "overall_status" in result
        assert len(result["checks"]) >= 2

    def test_checks_include_control_evaluation(self, db_session):
        ws = db_session.query(Workspace).first()
        result = ms.run_daily_checks(db_session, ws.id)
        db_session.commit()
        names = [c["name"] for c in result["checks"]]
        assert "control_evaluation" in names
        assert "connector_health" in names


class TestMonitoringAPI:
    def test_run_checks(self, admin_client):
        r = admin_client.post("/api/monitoring/run")
        assert r.status_code == 200
        assert "checks" in r.json()

    def test_editor_cannot_run(self, editor_client):
        r = editor_client.post("/api/monitoring/run")
        assert r.status_code == 403
