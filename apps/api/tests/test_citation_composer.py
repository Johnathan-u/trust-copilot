"""Tests for citation composer (P1-48)."""

import pytest
from app.models.control_evidence_link import ControlEvidenceLink
from app.models.evidence_item import EvidenceItem
from app.models.workspace import Workspace
from app.models.workspace_control import WorkspaceControl
from app.services import citation_composer_service as svc


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200
    return client


class TestCitationComposerService:
    def test_compose_citations(self, db_session):
        ws = db_session.query(Workspace).first()
        wc = db_session.query(WorkspaceControl).filter(WorkspaceControl.workspace_id == ws.id).first()
        if not wc:
            wc = WorkspaceControl(workspace_id=ws.id, custom_name="Citation Test", status="implemented")
            db_session.add(wc)
            db_session.flush()
        result = svc.compose_citations(db_session, ws.id, wc.id)
        assert "control" in result
        assert "citation_strength" in result

    def test_compose_citations_not_found(self, db_session):
        ws = db_session.query(Workspace).first()
        result = svc.compose_citations(db_session, ws.id, 99999)
        assert "error" in result

    def test_compose_with_evidence(self, db_session):
        ws = db_session.query(Workspace).first()
        wc = WorkspaceControl(workspace_id=ws.id, custom_name="Citation Ev Test", status="verified")
        db_session.add(wc)
        db_session.flush()
        ev = EvidenceItem(workspace_id=ws.id, title="Approved Ev", source_type="manual",
                          approval_status="approved")
        db_session.add(ev)
        db_session.flush()
        link = ControlEvidenceLink(control_id=wc.id, evidence_id=ev.id, confidence_score=0.85, verified=True)
        db_session.add(link)
        db_session.flush()
        db_session.commit()
        result = svc.compose_citations(db_session, ws.id, wc.id)
        assert len(result["approved_evidence"]) >= 1
        assert result["citation_strength"] != "none"

    def test_compose_answer_citations(self, db_session):
        ws = db_session.query(Workspace).first()
        wc = db_session.query(WorkspaceControl).filter(WorkspaceControl.workspace_id == ws.id).first()
        if not wc:
            wc = WorkspaceControl(workspace_id=ws.id, custom_name="Ans Citation", status="implemented")
            db_session.add(wc)
            db_session.flush()
        db_session.commit()
        result = svc.compose_answer_citations(db_session, ws.id, "We use encryption...", [wc.id])
        assert "controls_referenced" in result
        assert result["controls_referenced"] >= 1


class TestCitationComposerAPI:
    def test_compose_for_control(self, admin_client):
        r = admin_client.get("/api/citations/control/1")
        assert r.status_code in (200, 404)

    def test_compose_for_answer(self, admin_client):
        r = admin_client.post("/api/citations/answer", json={
            "answer_text": "We use AES-256 encryption",
            "control_ids": [1],
        })
        assert r.status_code == 200
        assert "controls_referenced" in r.json()
