"""Tests for evidence approval workflows (P1-47)."""

import pytest
from app.models.evidence_item import EvidenceItem
from app.models.workspace import Workspace
from app.services import evidence_approval_service as svc


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


class TestEvidenceApprovalService:
    def _make_evidence(self, db_session):
        ws = db_session.query(Workspace).first()
        ev = EvidenceItem(workspace_id=ws.id, title="Test Evidence", source_type="manual")
        db_session.add(ev)
        db_session.flush()
        return ev

    def test_approve(self, db_session):
        ev = self._make_evidence(db_session)
        db_session.commit()
        result = svc.approve_evidence(db_session, ev.id, 1)
        db_session.commit()
        assert result["approval_status"] == "approved"
        assert result["approved_by_user_id"] == 1

    def test_reject(self, db_session):
        ev = self._make_evidence(db_session)
        db_session.commit()
        result = svc.reject_evidence(db_session, ev.id, 1, "Bad quality")
        db_session.commit()
        assert result["approval_status"] == "rejected"
        assert result["rejection_reason"] == "Bad quality"

    def test_reset_to_pending(self, db_session):
        ev = self._make_evidence(db_session)
        db_session.commit()
        svc.approve_evidence(db_session, ev.id, 1)
        db_session.commit()
        result = svc.reset_to_pending(db_session, ev.id)
        db_session.commit()
        assert result["approval_status"] == "pending"
        assert result["approved_by_user_id"] is None

    def test_get_pending(self, db_session):
        ev = self._make_evidence(db_session)
        db_session.commit()
        ws = db_session.query(Workspace).first()
        pending = svc.get_pending(db_session, ws.id)
        assert len(pending) >= 1

    def test_bulk_approve(self, db_session):
        ids = []
        for _ in range(3):
            ev = self._make_evidence(db_session)
            db_session.commit()
            ids.append(ev.id)
        result = svc.bulk_approve(db_session, ids, 1)
        db_session.commit()
        assert len(result["approved"]) == 3


class TestEvidenceApprovalAPI:
    def test_pending(self, admin_client):
        r = admin_client.get("/api/evidence-approval/pending")
        assert r.status_code == 200
        assert "items" in r.json()

    def test_approved_list(self, admin_client):
        r = admin_client.get("/api/evidence-approval/approved")
        assert r.status_code == 200
        assert "items" in r.json()

    def test_editor_can_approve(self, editor_client):
        r = editor_client.post("/api/evidence-approval/1/approve")
        assert r.status_code in (200, 404)
