"""Tests for trust promises (E2-08, E2-10–E2-13)."""

import pytest
from datetime import datetime, timedelta, timezone

from app.models.workspace import Workspace
from app.services import promise_service as ps


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200
    return client


class TestPromiseService:
    def test_create_list(self, db_session):
        ws = db_session.query(Workspace).first()
        p = ps.create_promise(db_session, ws.id, "We use MFA everywhere", "trust_article", topic_key="mfa")
        db_session.commit()
        assert p["source_type"] == "trust_article"
        lst = ps.list_promises(db_session, ws.id)
        assert len(lst) >= 1

    def test_map_controls_coverage(self, db_session):
        ws = db_session.query(Workspace).first()
        from app.models.workspace_control import WorkspaceControl

        wc = WorkspaceControl(workspace_id=ws.id, custom_name="cov", status="verified")
        db_session.add(wc)
        db_session.flush()
        p = ps.create_promise(db_session, ws.id, "Access reviews quarterly", "sla")
        db_session.commit()
        ps.map_promise_to_controls(db_session, p["id"], [wc.id])
        db_session.commit()
        cov = ps.promise_coverage(db_session, p["id"])
        assert cov["fully_backed"] is True

    def test_contradictions(self, db_session):
        ws = db_session.query(Workspace).first()
        ps.create_promise(db_session, ws.id, "Data retained 90 days", "contract_clause", topic_key="data_retention")
        ps.create_promise(db_session, ws.id, "Retention period is 180 days", "questionnaire_answer", topic_key="data_retention")
        db_session.commit()
        c = ps.detect_contradictions(db_session, ws.id)
        assert len(c) >= 1

    def test_expiring(self, db_session):
        ws = db_session.query(Workspace).first()
        soon = datetime.now(timezone.utc) + timedelta(days=10)
        ps.create_promise(
            db_session, ws.id, "SOC2 attestation", "trust_article",
            expires_at=soon, topic_key="compliance",
        )
        db_session.commit()
        ex = ps.get_expiring_promises(db_session, ws.id, 30)
        assert len(ex) >= 1

    def test_dashboard(self, db_session):
        ws = db_session.query(Workspace).first()
        dash = ps.promise_dashboard(db_session, ws.id)
        assert "total_promises" in dash
        assert "contradiction_groups" in dash


class TestPromiseAPI:
    def test_dashboard(self, admin_client):
        r = admin_client.get("/api/promises/dashboard")
        assert r.status_code == 200
        assert "total_promises" in r.json()

    def test_create(self, admin_client):
        r = admin_client.post("/api/promises", json={
            "promise_text": "We encrypt data at rest",
            "source_type": "trust_article",
        })
        assert r.status_code == 200

    def test_contradictions_api(self, admin_client):
        r = admin_client.get("/api/promises/contradictions")
        assert r.status_code == 200
