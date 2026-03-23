"""In-app notification center: API tests for list, unread count, mark read, permissions, isolation."""

import pytest
from fastapi.testclient import TestClient


def _login_admin(client: TestClient) -> dict:
    from app.core.database import SessionLocal
    from app.models import WorkspaceMember, User
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        uid = user.id
        mem = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == uid, WorkspaceMember.workspace_id == 1
        ).first()
        if mem.role != "admin":
            mem.role = "admin"
            db.commit()
    finally:
        db.close()
    r = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert r.status_code == 200
    return r.json()


def _seed_notification(workspace_id=1, user_id=None, title="Test notification", category="info", admin_only=False, is_read=False):
    from app.core.database import SessionLocal
    from app.models import InAppNotification
    db = SessionLocal()
    try:
        n = InAppNotification(
            workspace_id=workspace_id, user_id=user_id, title=title,
            body="Test body", category=category, admin_only=admin_only, is_read=is_read,
        )
        db.add(n)
        db.commit()
        db.refresh(n)
        return n.id
    finally:
        db.close()


def _cleanup(workspace_id=1):
    from app.core.database import SessionLocal
    from app.models import InAppNotification
    db = SessionLocal()
    try:
        db.query(InAppNotification).filter(InAppNotification.workspace_id == workspace_id).delete()
        db.commit()
    finally:
        db.close()


def _get_admin_user_id():
    from app.core.database import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == "demo@trust.local").first()
        return u.id
    finally:
        db.close()


class TestListNotifications:
    def test_list_returns_notifications(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup()
        uid = _get_admin_user_id()
        _seed_notification(user_id=uid, title="Hello admin")
        r = client.get("/api/in-app-notifications?limit=10")
        assert r.status_code == 200
        d = r.json()
        assert d["total"] >= 1
        assert any(n["title"] == "Hello admin" for n in d["notifications"])

    def test_list_empty_state(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup()
        r = client.get("/api/in-app-notifications")
        assert r.status_code == 200
        assert r.json()["total"] == 0
        assert r.json()["notifications"] == []

    def test_notification_fields(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup()
        uid = _get_admin_user_id()
        _seed_notification(user_id=uid, title="Field check", category="warning")
        r = client.get("/api/in-app-notifications?limit=1")
        n = r.json()["notifications"][0]
        assert "id" in n
        assert "title" in n
        assert "body" in n
        assert "category" in n
        assert "is_read" in n
        assert "created_at" in n
        assert n["category"] == "warning"


class TestUnreadCount:
    def test_unread_count(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup()
        uid = _get_admin_user_id()
        _seed_notification(user_id=uid, title="Unread 1", is_read=False)
        _seed_notification(user_id=uid, title="Unread 2", is_read=False)
        _seed_notification(user_id=uid, title="Read 1", is_read=True)
        r = client.get("/api/in-app-notifications/unread-count")
        assert r.status_code == 200
        assert r.json()["count"] == 2

    def test_unread_count_zero(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup()
        r = client.get("/api/in-app-notifications/unread-count")
        assert r.status_code == 200
        assert r.json()["count"] == 0


class TestMarkRead:
    def test_mark_single_read(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup()
        uid = _get_admin_user_id()
        nid = _seed_notification(user_id=uid, title="Mark me", is_read=False)
        r = client.post(f"/api/in-app-notifications/{nid}/read")
        assert r.status_code == 200
        r2 = client.get("/api/in-app-notifications?limit=10")
        n = next((x for x in r2.json()["notifications"] if x["id"] == nid), None)
        assert n is not None
        assert n["is_read"] is True

    def test_mark_all_read(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup()
        uid = _get_admin_user_id()
        _seed_notification(user_id=uid, title="All 1", is_read=False)
        _seed_notification(user_id=uid, title="All 2", is_read=False)
        r = client.post("/api/in-app-notifications/read-all")
        assert r.status_code == 200
        assert r.json()["updated"] >= 2
        r2 = client.get("/api/in-app-notifications/unread-count")
        assert r2.json()["count"] == 0


class TestPermissions:
    def test_unauthenticated_returns_401(self, client: TestClient) -> None:
        r = client.get("/api/in-app-notifications")
        assert r.status_code == 401

    def test_unauthenticated_unread_count_401(self, client: TestClient) -> None:
        r = client.get("/api/in-app-notifications/unread-count")
        assert r.status_code == 401

    def test_admin_only_hidden_from_non_admin(self, client: TestClient) -> None:
        from app.core.database import SessionLocal
        from app.models import WorkspaceMember, User
        db = SessionLocal()
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        uid = user.id
        mem = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid, WorkspaceMember.workspace_id == 1).first()
        orig = mem.role
        db.close()
        _cleanup()
        _seed_notification(user_id=uid, title="Admin secret", admin_only=True)
        _seed_notification(user_id=uid, title="Public note", admin_only=False)
        # As editor
        db2 = SessionLocal()
        m2 = db2.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid, WorkspaceMember.workspace_id == 1).first()
        m2.role = "editor"
        db2.commit()
        db2.close()
        try:
            client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
            r = client.get("/api/in-app-notifications?limit=50")
            titles = [n["title"] for n in r.json()["notifications"]]
            assert "Public note" in titles
            assert "Admin secret" not in titles
        finally:
            db3 = SessionLocal()
            m3 = db3.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid, WorkspaceMember.workspace_id == 1).first()
            m3.role = orig
            db3.commit()
            db3.close()

    def test_cannot_read_other_users_notification(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup()
        from app.core.database import SessionLocal
        from app.core.password import hash_password
        from app.models import User
        db = SessionLocal()
        other = db.query(User).filter(User.email != "demo@trust.local").first()
        if not other:
            other = User(email="other_notif@test.local", password_hash=hash_password("x"), display_name="Other")
            db.add(other)
            db.commit()
            db.refresh(other)
        other_id = other.id
        db.close()
        nid = _seed_notification(user_id=other_id, title="Not mine")
        r = client.post(f"/api/in-app-notifications/{nid}/read")
        assert r.status_code == 404


class TestWorkspaceIsolation:
    def test_notifications_scoped_to_workspace(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup()
        _cleanup(2)
        uid = _get_admin_user_id()
        _seed_notification(workspace_id=1, user_id=uid, title="WS1 note")
        _seed_notification(workspace_id=2, user_id=uid, title="WS2 note")
        r = client.get("/api/in-app-notifications?limit=50")
        titles = [n["title"] for n in r.json()["notifications"]]
        assert "WS1 note" in titles
        assert "WS2 note" not in titles


class TestFirePoints:
    def test_invite_creates_notification(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup()
        from app.core.database import SessionLocal
        from app.models import Invite, WorkspaceMember
        db = SessionLocal()
        db.query(Invite).filter(Invite.email == "notif_bell@test.local", Invite.workspace_id == 1).delete()
        from app.models import User
        u = db.query(User).filter(User.email == "notif_bell@test.local").first()
        if u:
            db.query(WorkspaceMember).filter(WorkspaceMember.user_id == u.id, WorkspaceMember.workspace_id == 1).delete()
        db.commit()
        db.close()
        r = client.post("/api/members/invites", json={"email": "notif_bell@test.local", "role": "editor"})
        assert r.status_code == 200
        r2 = client.get("/api/in-app-notifications?limit=10")
        titles = [n["title"] for n in r2.json()["notifications"]]
        assert any("notif_bell@test.local" in t for t in titles)
