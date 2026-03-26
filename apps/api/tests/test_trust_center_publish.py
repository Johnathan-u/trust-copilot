"""Tests for Trust Center auto-publish (P1-64)."""

import pytest
from app.models.workspace import Workspace
from app.services import trust_center_publish_service as tcp


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


class TestTrustCenterPublishService:
    def test_auto_publish(self, db_session):
        ws = db_session.query(Workspace).first()
        result = tcp.auto_publish_approved_controls(db_session, ws.id)
        db_session.commit()
        assert "total_controls" in result
        assert "articles_created" in result
        assert "articles_updated" in result

    def test_get_published(self, db_session):
        ws = db_session.query(Workspace).first()
        articles = tcp.get_published_controls(db_session, ws.id)
        assert isinstance(articles, list)


class TestTrustCenterPublishAPI:
    def test_auto_publish(self, admin_client):
        r = admin_client.post("/api/trust-center/publish")
        assert r.status_code == 200
        assert "total_controls" in r.json()

    def test_list_published(self, admin_client):
        r = admin_client.get("/api/trust-center/publish")
        assert r.status_code == 200
        assert "articles" in r.json()

    def test_editor_can_read(self, editor_client):
        r = editor_client.get("/api/trust-center/publish")
        assert r.status_code == 200

    def test_editor_cannot_publish(self, editor_client):
        r = editor_client.post("/api/trust-center/publish")
        assert r.status_code == 403
