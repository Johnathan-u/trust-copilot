"""Tests for Trust Center auto-publish (P1-64)."""

import uuid

import pytest
from sqlalchemy import func, text

from app.models.workspace import Workspace
from app.models.workspace_control import WorkspaceControl
from app.services import trust_center_publish_service as tcp


def _workspace(db_session, label: str) -> Workspace:
    suffix = uuid.uuid4().hex[:8]
    next_id = (db_session.query(func.max(Workspace.id)).scalar() or 0) + 1
    ws = Workspace(id=next_id, name=f"Synthetic {label}", slug=f"bug019-{label}-{suffix}")
    db_session.add(ws)
    db_session.flush()
    db_session.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('workspaces', 'id'), (SELECT MAX(id) FROM workspaces))"
        )
    )
    return ws


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
        ws = _workspace(db_session, "publish")
        db_session.add(
            WorkspaceControl(workspace_id=ws.id, custom_name="cov", status="implemented")
        )
        db_session.flush()
        result = tcp.auto_publish_approved_controls(db_session, ws.id)
        db_session.flush()
        assert result["total_controls"] == 1
        assert result["articles_created"] == 1
        assert result["articles_updated"] == 0
        articles = tcp.get_published_controls(db_session, ws.id)
        assert [article["slug"] for article in articles] == ["control-cov"]

    def test_get_published(self, db_session):
        ws = _workspace(db_session, "empty")
        articles = tcp.get_published_controls(db_session, ws.id)
        assert articles == []


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
