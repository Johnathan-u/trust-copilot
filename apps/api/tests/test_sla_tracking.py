"""Tests for SLA and turnaround tracking (P1-61)."""

import pytest
from app.models.workspace import Workspace
from app.services import sla_tracking_service as sla


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


class TestSLATrackingService:
    def test_metrics_structure(self, db_session):
        ws = db_session.query(Workspace).first()
        metrics = sla.get_sla_metrics(db_session, ws.id)
        assert "total_questionnaires" in metrics
        assert "total_jobs_completed" in metrics
        assert "turnaround" in metrics
        assert "sla" in metrics
        assert "avg_seconds" in metrics["turnaround"]
        assert "compliance_pct" in metrics["sla"]

    def test_percentile_calculation(self):
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        assert sla._percentile(data, 50) == 6.0
        assert sla._percentile(data, 95) == 10.0
        assert sla._percentile([], 50) == 0


class TestSLATrackingAPI:
    def test_get_metrics(self, admin_client):
        r = admin_client.get("/api/sla")
        assert r.status_code == 200
        assert "turnaround" in r.json()

    def test_editor_cannot_access(self, editor_client):
        r = editor_client.get("/api/sla")
        assert r.status_code == 403
