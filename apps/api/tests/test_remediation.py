"""Tests for remediation engine (E3-14, E3-15, E3-16)."""

import pytest
from app.models.workspace import Workspace
from app.services import remediation_service as svc


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


class TestRemediationService:
    def test_create_playbook(self, db_session):
        ws = db_session.query(Workspace).first()
        result = svc.create_playbook(db_session, ws.id, "mfa_disabled", "Re-enable MFA",
                                      steps=["Step 1", "Step 2"], severity="high")
        db_session.commit()
        assert result["control_key"] == "mfa_disabled"
        assert result["severity"] == "high"
        assert len(result["steps"]) == 2

    def test_list_playbooks(self, db_session):
        ws = db_session.query(Workspace).first()
        svc.create_playbook(db_session, ws.id, "test_key", "Test Playbook")
        db_session.commit()
        pbs = svc.list_playbooks(db_session, ws.id)
        assert len(pbs) >= 1

    def test_seed_builtins(self, db_session):
        ws = db_session.query(Workspace).first()
        result = svc.seed_builtins(db_session, ws.id)
        db_session.commit()
        assert result["seeded"] >= 1

    def test_get_builtins(self):
        builtins = svc.get_builtin_playbooks()
        assert len(builtins) >= 5

    def test_create_ticket(self, db_session):
        ws = db_session.query(Workspace).first()
        result = svc.create_ticket(db_session, ws.id, "Fix MFA issue",
                                    description="MFA was disabled", sla_hours=24)
        db_session.commit()
        assert result["title"] == "Fix MFA issue"
        assert result["status"] == "open"
        assert result["deadline"] is not None

    def test_list_tickets(self, db_session):
        ws = db_session.query(Workspace).first()
        svc.create_ticket(db_session, ws.id, "Ticket 1")
        db_session.commit()
        tickets = svc.list_tickets(db_session, ws.id)
        assert len(tickets) >= 1

    def test_update_ticket_status(self, db_session):
        ws = db_session.query(Workspace).first()
        created = svc.create_ticket(db_session, ws.id, "Status Ticket")
        db_session.commit()
        updated = svc.update_ticket_status(db_session, created["id"], "in_progress")
        db_session.commit()
        assert updated["status"] == "in_progress"
        closed = svc.update_ticket_status(db_session, created["id"], "closed")
        db_session.commit()
        assert closed["resolved_at"] is not None

    def test_ticket_stats(self, db_session):
        ws = db_session.query(Workspace).first()
        svc.create_ticket(db_session, ws.id, "Stats Ticket")
        db_session.commit()
        stats = svc.get_ticket_stats(db_session, ws.id)
        assert stats["total"] >= 1
        assert "by_status" in stats

    def test_auto_create(self, db_session):
        ws = db_session.query(Workspace).first()
        result = svc.auto_create_tickets(db_session, ws.id)
        db_session.commit()
        assert "created" in result


class TestRemediationAPI:
    def test_create_playbook(self, admin_client):
        r = admin_client.post("/api/remediation/playbooks", json={
            "control_key": "api_test", "title": "API Playbook",
            "steps": ["Fix it"], "severity": "low",
        })
        assert r.status_code == 200
        assert r.json()["title"] == "API Playbook"

    def test_list_playbooks(self, admin_client):
        r = admin_client.get("/api/remediation/playbooks")
        assert r.status_code == 200
        assert "playbooks" in r.json()

    def test_builtins(self, admin_client):
        r = admin_client.get("/api/remediation/playbooks/builtins")
        assert r.status_code == 200
        assert len(r.json()["builtins"]) >= 5

    def test_seed(self, admin_client):
        r = admin_client.post("/api/remediation/playbooks/seed")
        assert r.status_code == 200

    def test_create_ticket(self, admin_client):
        r = admin_client.post("/api/remediation/tickets", json={
            "title": "API Ticket", "sla_hours": 48,
        })
        assert r.status_code == 200
        assert r.json()["status"] == "open"

    def test_list_tickets(self, admin_client):
        r = admin_client.get("/api/remediation/tickets")
        assert r.status_code == 200
        assert "tickets" in r.json()

    def test_stats(self, admin_client):
        r = admin_client.get("/api/remediation/stats")
        assert r.status_code == 200
        assert "total" in r.json()

    def test_auto_create(self, admin_client):
        r = admin_client.post("/api/remediation/auto-create")
        assert r.status_code == 200

    def test_editor_can_read(self, editor_client):
        r = editor_client.get("/api/remediation/playbooks")
        assert r.status_code == 200

    def test_editor_cannot_create(self, editor_client):
        r = editor_client.post("/api/remediation/playbooks", json={
            "control_key": "x", "title": "X",
        })
        assert r.status_code == 403
