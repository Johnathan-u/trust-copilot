"""Tests for alert management (P1-38, P1-39)."""

import pytest
from app.models.workspace import Workspace
from app.services import alert_management_service as am


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


class TestAlertManagementService:
    def test_acknowledge(self, db_session):
        ws = db_session.query(Workspace).first()
        result = am.acknowledge(db_session, ws.id, "control_failing", "acknowledge", reason="Accepted risk")
        db_session.commit()
        assert result["action"] == "acknowledge"
        assert result["reason"] == "Accepted risk"

    def test_snooze(self, db_session):
        ws = db_session.query(Workspace).first()
        result = am.acknowledge(db_session, ws.id, "drift", "snooze", snooze_hours=24, control_id=1)
        db_session.commit()
        assert result["action"] == "snooze"
        assert result["snoozed_until"] is not None

    def test_override_with_reason(self, db_session):
        ws = db_session.query(Workspace).first()
        result = am.acknowledge(db_session, ws.id, "control_failing", "override", reason="Compensating control exists")
        db_session.commit()
        assert result["action"] == "override"

    def test_invalid_action(self, db_session):
        ws = db_session.query(Workspace).first()
        result = am.acknowledge(db_session, ws.id, "test", "invalid_action")
        assert "error" in result

    def test_list_acknowledgments(self, db_session):
        ws = db_session.query(Workspace).first()
        am.acknowledge(db_session, ws.id, "test_list", "acknowledge")
        db_session.commit()
        acks = am.list_acknowledgments(db_session, ws.id)
        assert isinstance(acks, list)
        assert len(acks) >= 1

    def test_is_snoozed(self, db_session):
        ws = db_session.query(Workspace).first()
        am.acknowledge(db_session, ws.id, "snooze_test", "snooze", control_id=999, snooze_hours=24)
        db_session.commit()
        assert am.is_snoozed(db_session, ws.id, 999) is True


class TestAlertManagementAPI:
    def test_acknowledge(self, admin_client):
        r = admin_client.post("/api/alerts/acknowledge", json={
            "alert_type": "control_failing",
            "action": "acknowledge",
            "reason": "Test ack",
        })
        assert r.status_code == 200
        assert r.json()["action"] == "acknowledge"

    def test_list(self, admin_client):
        r = admin_client.get("/api/alerts")
        assert r.status_code == 200
        assert "acknowledgments" in r.json()

    def test_editor_cannot_acknowledge(self, editor_client):
        r = editor_client.post("/api/alerts/acknowledge", json={
            "alert_type": "test",
            "action": "acknowledge",
        })
        assert r.status_code == 403

    def test_invalid_action_rejected(self, admin_client):
        r = admin_client.post("/api/alerts/acknowledge", json={
            "alert_type": "test",
            "action": "invalid_action",
        })
        assert r.status_code == 400
