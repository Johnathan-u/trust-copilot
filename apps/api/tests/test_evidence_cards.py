"""Tests for evidence cards (P1-41)."""

import pytest
from app.models.workspace import Workspace
from app.models.workspace_control import WorkspaceControl
from app.services import evidence_cards_service as ec


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


class TestEvidenceCardsService:
    def test_all_cards(self, db_session):
        ws = db_session.query(Workspace).first()
        cards = ec.get_all_evidence_cards(db_session, ws.id)
        assert isinstance(cards, list)

    def test_single_card(self, db_session):
        ws = db_session.query(Workspace).first()
        ctrl = db_session.query(WorkspaceControl).filter(WorkspaceControl.workspace_id == ws.id).first()
        if not ctrl:
            pytest.skip("No workspace controls")
        card = ec.get_evidence_card(db_session, ws.id, ctrl.id)
        assert "control_id" in card
        assert "evidence_count" in card
        assert "coverage" in card

    def test_not_found(self, db_session):
        ws = db_session.query(Workspace).first()
        card = ec.get_evidence_card(db_session, ws.id, 99999)
        assert "error" in card


class TestEvidenceCardsAPI:
    def test_list_cards(self, admin_client):
        r = admin_client.get("/api/evidence-cards")
        assert r.status_code == 200
        assert "cards" in r.json()

    def test_editor_can_access(self, editor_client):
        r = editor_client.get("/api/evidence-cards")
        assert r.status_code == 200
