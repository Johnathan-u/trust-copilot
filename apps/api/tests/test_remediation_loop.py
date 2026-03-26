"""Tests for E3-17, E3-18, E3-19 remediation loop."""

import pytest
from app.models.evidence_item import EvidenceItem
from app.models.workspace import Workspace
from app.models.workspace_control import WorkspaceControl
from app.services import remediation_loop_service as loop
from app.services import remediation_service as rs


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200
    return client


class TestRemediationLoopService:
    def test_submit_evidence(self, db_session):
        ws = db_session.query(Workspace).first()
        wc = WorkspaceControl(workspace_id=ws.id, custom_name="loop-test", status="not_implemented")
        db_session.add(wc)
        db_session.flush()
        ev = EvidenceItem(workspace_id=ws.id, title="Proof", source_type="manual")
        db_session.add(ev)
        db_session.flush()
        t = rs.create_ticket(db_session, ws.id, "Fix it", control_id=wc.id, sla_hours=24)
        db_session.commit()
        result = loop.submit_post_remediation_evidence(db_session, t["id"], [ev.id], actor_user_id=1)
        db_session.commit()
        assert result["status"] == "evidence_submitted"
        assert ev.id in result["linked_evidence_ids"]

    def test_impact_analysis(self, db_session):
        ws = db_session.query(Workspace).first()
        t = rs.create_ticket(db_session, ws.id, "Impact ticket", affected_deal_ids=[1, 2])
        db_session.commit()
        impact = loop.analyze_remediation_impact(db_session, t["id"])
        assert impact["ticket_id"] == t["id"]
        assert impact["affected_deal_ids"] == [1, 2]

    def test_automation_dry_run_no_opt_in(self, db_session):
        ws = db_session.query(Workspace).first()
        r = loop.run_safe_automation(db_session, ws.id, "mfa_re_enable", dry_run=True)
        db_session.commit()
        assert r["dry_run"] is True

    def test_automation_live_requires_opt_in(self, db_session):
        ws = db_session.query(Workspace).first()
        loop.set_automation_enabled(db_session, ws.id, "mfa_re_enable", False)
        db_session.commit()
        r = loop.run_safe_automation(db_session, ws.id, "mfa_re_enable", dry_run=False)
        assert "error" in r

    def test_enable_and_run(self, db_session):
        ws = db_session.query(Workspace).first()
        loop.set_automation_enabled(db_session, ws.id, "mfa_re_enable", True)
        db_session.commit()
        r = loop.run_safe_automation(db_session, ws.id, "mfa_re_enable", dry_run=False)
        db_session.commit()
        assert r.get("result") == "completed"


class TestRemediationLoopAPI:
    def test_automations_list(self, admin_client):
        r = admin_client.get("/api/remediation/automations")
        assert r.status_code == 200
        assert len(r.json()["automations"]) >= 3

    def test_dry_run_api(self, admin_client):
        r = admin_client.post("/api/remediation/automations/mfa_re_enable/run", json={"dry_run": True})
        assert r.status_code == 200
        assert r.json()["dry_run"] is True

    def test_audit_requires_admin(self, client):
        client.cookies.clear()
        client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
        r = client.get("/api/remediation/audit")
        assert r.status_code == 403
