"""Tests for source confidence scoring (P1-46)."""

import pytest
from app.models.control_evidence_link import ControlEvidenceLink
from app.models.evidence_item import EvidenceItem
from app.models.workspace import Workspace
from app.models.workspace_control import WorkspaceControl
from app.services import confidence_scoring_service as svc


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200
    return client


class TestConfidenceScoringService:
    def test_score_evidence(self, db_session):
        ws = db_session.query(Workspace).first()
        ev = EvidenceItem(workspace_id=ws.id, title="Scoring Test", source_type="integration")
        db_session.add(ev)
        db_session.flush()
        db_session.commit()
        result = svc.score_evidence(db_session, ev.id)
        assert "total_score" in result
        assert "breakdown" in result
        assert result["total_score"] > 0

    def test_score_nonexistent(self, db_session):
        result = svc.score_evidence(db_session, 99999)
        assert "error" in result

    def test_source_type_weights(self, db_session):
        ws = db_session.query(Workspace).first()
        ev_int = EvidenceItem(workspace_id=ws.id, title="Integration", source_type="integration")
        ev_slack = EvidenceItem(workspace_id=ws.id, title="Slack", source_type="slack")
        db_session.add_all([ev_int, ev_slack])
        db_session.flush()
        db_session.commit()
        r1 = svc.score_evidence(db_session, ev_int.id)
        r2 = svc.score_evidence(db_session, ev_slack.id)
        assert r1["breakdown"]["source_type"] > r2["breakdown"]["source_type"]

    def test_score_all_for_control(self, db_session):
        ws = db_session.query(Workspace).first()
        wc = db_session.query(WorkspaceControl).filter(WorkspaceControl.workspace_id == ws.id).first()
        if not wc:
            wc = WorkspaceControl(workspace_id=ws.id, custom_name="Score Test", status="implemented")
            db_session.add(wc)
            db_session.flush()
        ev = EvidenceItem(workspace_id=ws.id, title="Link Test", source_type="manual")
        db_session.add(ev)
        db_session.flush()
        link = ControlEvidenceLink(control_id=wc.id, evidence_id=ev.id)
        db_session.add(link)
        db_session.flush()
        db_session.commit()
        results = svc.score_all_for_control(db_session, wc.id)
        assert len(results) >= 1
        assert "total_score" in results[0]


class TestConfidenceScoringAPI:
    def test_score_evidence_api(self, admin_client):
        r = admin_client.get("/api/confidence-scoring/evidence/1")
        assert r.status_code == 200

    def test_score_control_api(self, admin_client):
        r = admin_client.get("/api/confidence-scoring/control/1")
        assert r.status_code == 200
        assert "scores" in r.json()
