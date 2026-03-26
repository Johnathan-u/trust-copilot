"""Tests for alerting engine (P1-37)."""

import pytest
from app.services import alerting_engine_service as svc


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


class TestAlertingEngineService:
    def test_check_drift(self, db_session):
        from app.models.workspace import Workspace
        ws = db_session.query(Workspace).first()
        alerts = svc.check_drift_alerts(db_session, ws.id)
        assert isinstance(alerts, list)

    def test_check_connectors(self, db_session):
        from app.models.workspace import Workspace
        ws = db_session.query(Workspace).first()
        alerts = svc.check_connector_failure_alerts(db_session, ws.id)
        assert isinstance(alerts, list)

    def test_check_stale_evidence(self, db_session):
        from app.models.workspace import Workspace
        ws = db_session.query(Workspace).first()
        alerts = svc.check_stale_evidence_alerts(db_session, ws.id)
        assert isinstance(alerts, list)

    def test_run_all_checks(self, db_session):
        from app.models.workspace import Workspace
        ws = db_session.query(Workspace).first()
        result = svc.run_all_checks(db_session, ws.id)
        assert "total_alerts" in result
        assert "by_type" in result

    def test_email_digest(self, db_session):
        from app.models.workspace import Workspace
        ws = db_session.query(Workspace).first()
        result = svc.generate_email_digest(db_session, ws.id)
        assert "subject" in result
        assert "generated_at" in result


class TestAlertingEngineAPI:
    def test_drift(self, admin_client):
        r = admin_client.get("/api/alerting-engine/drift")
        assert r.status_code == 200
        assert "alerts" in r.json()

    def test_connectors(self, admin_client):
        r = admin_client.get("/api/alerting-engine/connectors")
        assert r.status_code == 200

    def test_stale_evidence(self, admin_client):
        r = admin_client.get("/api/alerting-engine/stale-evidence")
        assert r.status_code == 200

    def test_all_alerts(self, admin_client):
        r = admin_client.get("/api/alerting-engine/all")
        assert r.status_code == 200
        assert "total_alerts" in r.json()

    def test_email_digest(self, admin_client):
        r = admin_client.get("/api/alerting-engine/email-digest")
        assert r.status_code == 200
        assert "subject" in r.json()

    def test_editor_cannot_email_digest(self, editor_client):
        r = editor_client.get("/api/alerting-engine/email-digest")
        assert r.status_code == 403
