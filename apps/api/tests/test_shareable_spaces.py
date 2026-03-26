"""Tests for shareable spaces (P1-66, P1-70)."""

import pytest
from app.models.workspace import Workspace
from app.services import shareable_space_service as ss


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


class TestShareableSpaceService:
    def test_create_space(self, db_session):
        ws = db_session.query(Workspace).first()
        result = ss.create_space(db_session, ws.id, "Acme Deal Room", 1,
                                  buyer_company="Acme Corp", article_ids=[1, 2])
        db_session.commit()
        assert result["name"] == "Acme Deal Room"
        assert result["access_token"] is not None

    def test_access_by_token(self, db_session):
        ws = db_session.query(Workspace).first()
        space = ss.create_space(db_session, ws.id, "Token Test", 1)
        db_session.commit()
        result = ss.access_space_by_token(db_session, space["access_token"])
        assert result["valid"] is True

    def test_deactivate(self, db_session):
        ws = db_session.query(Workspace).first()
        space = ss.create_space(db_session, ws.id, "Deactivate Test", 1)
        db_session.commit()
        ss.deactivate_space(db_session, space["id"])
        db_session.commit()
        result = ss.access_space_by_token(db_session, space["access_token"])
        assert result["valid"] is False

    def test_list_spaces(self, db_session):
        ws = db_session.query(Workspace).first()
        ss.create_space(db_session, ws.id, "List Test", 1)
        db_session.commit()
        items = ss.list_spaces(db_session, ws.id)
        assert len(items) >= 1


class TestShareableSpaceAPI:
    def test_create(self, admin_client):
        r = admin_client.post("/api/shareable-spaces", json={
            "name": "API Space",
            "buyer_company": "Test Corp",
        })
        assert r.status_code == 200
        assert r.json()["access_token"] is not None

    def test_list(self, admin_client):
        r = admin_client.get("/api/shareable-spaces")
        assert r.status_code == 200
        assert "spaces" in r.json()

    def test_access(self, admin_client, client):
        r = admin_client.post("/api/shareable-spaces", json={"name": "Access Test"})
        token = r.json()["access_token"]
        r = client.get(f"/api/shareable-spaces/access?token={token}")
        assert r.status_code == 200
        assert r.json()["valid"] is True

    def test_editor_cannot_create(self, editor_client):
        r = editor_client.post("/api/shareable-spaces", json={"name": "X"})
        assert r.status_code == 403
