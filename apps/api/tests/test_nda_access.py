"""Tests for NDA-gated access requests (P1-65)."""

import pytest
from app.models.workspace import Workspace
from app.services import nda_access_service as nda


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


class TestNdaAccessService:
    def test_request_access(self, db_session):
        ws = db_session.query(Workspace).first()
        result = nda.request_access(
            db_session, ws.id,
            requester_name="Jane Buyer",
            requester_email="jane@acme.com",
            nda_accepted=True,
            requester_company="Acme Corp",
            purpose="Security review",
        )
        db_session.commit()
        assert result["status"] == "pending"
        assert result["nda_accepted"] is True

    def test_request_without_nda_rejected(self, db_session):
        ws = db_session.query(Workspace).first()
        result = nda.request_access(
            db_session, ws.id,
            requester_name="No NDA",
            requester_email="no@nda.com",
            nda_accepted=False,
        )
        assert "error" in result

    def test_approve_generates_token(self, db_session):
        ws = db_session.query(Workspace).first()
        req = nda.request_access(
            db_session, ws.id,
            requester_name="Token Test",
            requester_email="token@test.com",
            nda_accepted=True,
        )
        db_session.commit()
        approved = nda.approve_request(db_session, req["id"], approved_by_user_id=1)
        db_session.commit()
        assert approved["status"] == "approved"
        assert approved["access_token"] is not None
        assert approved["expires_at"] is not None

    def test_validate_token(self, db_session):
        ws = db_session.query(Workspace).first()
        req = nda.request_access(
            db_session, ws.id,
            requester_name="Validate",
            requester_email="validate@test.com",
            nda_accepted=True,
        )
        db_session.commit()
        approved = nda.approve_request(db_session, req["id"], approved_by_user_id=1)
        db_session.commit()
        valid = nda.validate_access_token(db_session, approved["access_token"])
        assert valid["valid"] is True
        assert valid["requester_email"] == "validate@test.com"

    def test_reject_request(self, db_session):
        ws = db_session.query(Workspace).first()
        req = nda.request_access(
            db_session, ws.id,
            requester_name="Reject",
            requester_email="reject@test.com",
            nda_accepted=True,
        )
        db_session.commit()
        rejected = nda.reject_request(db_session, req["id"])
        db_session.commit()
        assert rejected["status"] == "rejected"

    def test_revoke_access(self, db_session):
        ws = db_session.query(Workspace).first()
        req = nda.request_access(
            db_session, ws.id,
            requester_name="Revoke",
            requester_email="revoke@test.com",
            nda_accepted=True,
        )
        db_session.commit()
        nda.approve_request(db_session, req["id"], approved_by_user_id=1)
        db_session.commit()
        revoked = nda.revoke_access(db_session, req["id"])
        db_session.commit()
        assert revoked["status"] == "revoked"

    def test_validate_revoked_token_fails(self, db_session):
        ws = db_session.query(Workspace).first()
        req = nda.request_access(
            db_session, ws.id,
            requester_name="Revoke Check",
            requester_email="rcheck@test.com",
            nda_accepted=True,
        )
        db_session.commit()
        approved = nda.approve_request(db_session, req["id"], approved_by_user_id=1)
        db_session.commit()
        nda.revoke_access(db_session, req["id"])
        db_session.commit()
        valid = nda.validate_access_token(db_session, approved["access_token"])
        assert valid["valid"] is False

    def test_list_requests(self, db_session):
        ws = db_session.query(Workspace).first()
        nda.request_access(db_session, ws.id, "List", "list@t.com", True)
        db_session.commit()
        items = nda.list_requests(db_session, ws.id)
        assert len(items) >= 1


class TestNdaAccessAPI:
    def test_request_access_public(self, client):
        r = client.post("/api/nda-access/request", json={
            "requester_name": "API Buyer",
            "requester_email": "api@buyer.com",
            "nda_accepted": True,
            "requester_company": "API Corp",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "pending"

    def test_request_without_nda(self, client):
        r = client.post("/api/nda-access/request", json={
            "requester_name": "No NDA",
            "requester_email": "no@nda.com",
            "nda_accepted": False,
        })
        assert r.status_code == 400

    def test_list_requests(self, admin_client):
        r = admin_client.get("/api/nda-access/requests")
        assert r.status_code == 200
        assert "requests" in r.json()

    def test_approve_and_validate(self, admin_client, client):
        r = client.post("/api/nda-access/request", json={
            "requester_name": "Approve Test",
            "requester_email": "approve@test.com",
            "nda_accepted": True,
        })
        req_id = r.json()["id"]
        r = admin_client.post(f"/api/nda-access/approve/{req_id}")
        assert r.status_code == 200
        token = r.json()["access_token"]

        r = client.get(f"/api/nda-access/validate?token={token}")
        assert r.status_code == 200
        assert r.json()["valid"] is True

    def test_editor_cannot_approve(self, editor_client, client):
        r = client.post("/api/nda-access/request", json={
            "requester_name": "Editor Test",
            "requester_email": "editor@test.com",
            "nda_accepted": True,
        })
        req_id = r.json()["id"]
        r = editor_client.post(f"/api/nda-access/approve/{req_id}")
        assert r.status_code == 403
