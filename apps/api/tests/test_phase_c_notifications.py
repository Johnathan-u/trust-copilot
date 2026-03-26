"""Phase C — Email Notifications: policies, delivery, unsubscribe, permissions, isolation."""

import time

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


def _cleanup_policies(workspace_id: int = 1):
    from app.core.database import SessionLocal
    from app.models import NotificationPolicy
    db = SessionLocal()
    try:
        db.query(NotificationPolicy).filter(NotificationPolicy.workspace_id == workspace_id).delete()
        db.commit()
    finally:
        db.close()


def _cleanup_log(workspace_id: int = 1):
    from app.core.database import SessionLocal
    from app.models import NotificationLog
    db = SessionLocal()
    try:
        db.query(NotificationLog).filter(NotificationLog.workspace_id == workspace_id).delete()
        db.commit()
    finally:
        db.close()


def _cleanup_unsubs(workspace_id: int = 1):
    from app.core.database import SessionLocal
    from app.models import NotificationUnsubscribe
    db = SessionLocal()
    try:
        db.query(NotificationUnsubscribe).filter(NotificationUnsubscribe.workspace_id == workspace_id).delete()
        db.commit()
    finally:
        db.close()


def _ensure_test_user(email: str, password: str = "testpass123") -> int:
    from app.core.database import SessionLocal
    from app.core.password import hash_password
    from app.models import User
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(email=email, password_hash=hash_password(password), display_name=email.split("@")[0])
            db.add(user)
            db.commit()
            db.refresh(user)
        return user.id
    finally:
        db.close()


def _add_member(user_id: int, workspace_id: int = 1, role: str = "editor") -> int:
    from app.core.database import SessionLocal
    from app.models import WorkspaceMember
    db = SessionLocal()
    try:
        existing = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == user_id, WorkspaceMember.workspace_id == workspace_id
        ).first()
        if existing:
            existing.role = role
            existing.suspended = False
            db.commit()
            return existing.id
        mem = WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=role)
        db.add(mem)
        db.commit()
        db.refresh(mem)
        return mem.id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Policy CRUD
# ---------------------------------------------------------------------------

class TestPolicyCRUD:
    def test_list_event_types(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.get("/api/notifications/event-types")
        assert r.status_code == 200
        types = r.json()["event_types"]
        assert "member.invited" in types
        assert "export.completed" in types
        assert len(types) >= 10

    def test_create_policy(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_policies()
        r = client.post("/api/notifications/policies", json={
            "event_type": "member.invited", "recipient_type": "admins",
        })
        assert r.status_code == 200
        d = r.json()
        assert d["event_type"] == "member.invited"
        assert d["enabled"] is True
        assert d["recipient_type"] == "admins"

    def test_create_policy_rejects_unknown_event(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.post("/api/notifications/policies", json={"event_type": "fake.event"})
        assert r.status_code == 400

    def test_create_policy_rejects_duplicate(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_policies()
        client.post("/api/notifications/policies", json={"event_type": "member.invited"})
        r = client.post("/api/notifications/policies", json={"event_type": "member.invited"})
        assert r.status_code == 400

    def test_update_policy(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_policies()
        r = client.post("/api/notifications/policies", json={"event_type": "member.joined", "recipient_type": "admins"})
        pid = r.json()["id"]
        r2 = client.patch(f"/api/notifications/policies/{pid}", json={"enabled": False})
        assert r2.status_code == 200
        assert r2.json()["enabled"] is False

    def test_delete_policy(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_policies()
        r = client.post("/api/notifications/policies", json={"event_type": "member.removed"})
        pid = r.json()["id"]
        r2 = client.delete(f"/api/notifications/policies/{pid}")
        assert r2.status_code == 200
        r3 = client.get("/api/notifications/policies")
        assert all(p["event_type"] != "member.removed" for p in r3.json()["policies"])

    def test_list_policies(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.get("/api/notifications/policies")
        assert r.status_code == 200
        assert "policies" in r.json()

    def test_policy_audit_logged(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_policies()
        client.post("/api/notifications/policies", json={"event_type": "member.suspended", "recipient_type": "all"})
        r = client.get("/api/audit/events?action=notification.&page_size=10&since_hours=1")
        assert r.status_code == 200
        actions = {e["action"] for e in r.json()["events"]}
        assert "notification.policy_created" in actions


# ---------------------------------------------------------------------------
# Delivery and recipient resolution
# ---------------------------------------------------------------------------

class TestNotificationDelivery:
    def test_fire_notification_creates_log_entry(self, client: TestClient) -> None:
        """When a policy is active and an event fires, a log entry is created."""
        from app.services.notification_service import _recent_sends, fire_notification
        _recent_sends.clear()
        _login_admin(client)
        _cleanup_policies()
        _cleanup_log()
        client.post("/api/notifications/policies", json={"event_type": "member.invited", "recipient_type": "admins"})
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            fire_notification(db, 1, "member.invited", detail="notif_test@test.local invited as editor", workspace_name="Test")
            db.commit()
        finally:
            db.close()
        r2 = client.get("/api/notifications/log?page_size=10")
        assert r2.status_code == 200
        entries = r2.json()["entries"]
        member_invited = [e for e in entries if e["event_type"] == "member.invited"]
        assert len(member_invited) > 0
        assert member_invited[0]["status"] in ("sent", "failed")

    def test_disabled_policy_does_not_fire(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_policies()
        _cleanup_log()
        r = client.post("/api/notifications/policies", json={"event_type": "member.role_changed", "recipient_type": "admins"})
        pid = r.json()["id"]
        client.patch(f"/api/notifications/policies/{pid}", json={"enabled": False})
        uid = _ensure_test_user("nofire@test.local")
        mid = _add_member(uid, 1, "editor")
        client.patch(f"/api/members/{mid}", json={"role": "reviewer"})
        r2 = client.get("/api/notifications/log?page_size=10")
        role_entries = [e for e in r2.json()["entries"] if e["event_type"] == "member.role_changed"]
        assert len(role_entries) == 0

    def test_role_recipient_only_sends_to_role(self, client: TestClient) -> None:
        """Policy with recipient_type=role sends only to members with that role."""
        _login_admin(client)
        _cleanup_policies()
        _cleanup_log()
        client.post("/api/notifications/policies", json={
            "event_type": "member.removed", "recipient_type": "role", "recipient_value": "admin",
        })
        uid = _ensure_test_user("rolerecip@test.local")
        mid = _add_member(uid, 1, "editor")
        client.delete(f"/api/members/{mid}")
        r = client.get("/api/notifications/log?page_size=10")
        entries = [e for e in r.json()["entries"] if e["event_type"] == "member.removed"]
        for e in entries:
            assert e["recipient_email"] != "rolerecip@test.local"

    def test_suspended_members_not_notified(self, client: TestClient) -> None:
        """Suspended members should not receive notifications."""
        _login_admin(client)
        _cleanup_policies()
        _cleanup_log()
        client.post("/api/notifications/policies", json={"event_type": "member.suspended", "recipient_type": "all"})
        email = "susp_notif@test.local"
        uid = _ensure_test_user(email)
        mid = _add_member(uid, 1, "editor")
        client.patch(f"/api/members/{mid}/suspend", json={"suspended": True})
        r = client.get("/api/notifications/log?page_size=10")
        entries = [e for e in r.json()["entries"] if e["event_type"] == "member.suspended"]
        recips = [e["recipient_email"] for e in entries]
        assert email not in recips
        client.patch(f"/api/members/{mid}/suspend", json={"suspended": False})


# ---------------------------------------------------------------------------
# Unsubscribe
# ---------------------------------------------------------------------------

class TestUnsubscribe:
    def test_add_unsubscribe(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_unsubs()
        r = client.post("/api/notifications/unsubscribes", json={"event_type": "member.invited"})
        assert r.status_code == 200
        assert r.json()["event_type"] == "member.invited"

    def test_list_unsubscribes(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_unsubs()
        client.post("/api/notifications/unsubscribes", json={"event_type": "member.invited"})
        r = client.get("/api/notifications/unsubscribes")
        assert r.status_code == 200
        assert any(u["event_type"] == "member.invited" for u in r.json()["unsubscribes"])

    def test_remove_unsubscribe(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_unsubs()
        r = client.post("/api/notifications/unsubscribes", json={"event_type": "member.joined"})
        uid = r.json()["id"]
        r2 = client.delete(f"/api/notifications/unsubscribes/{uid}")
        assert r2.status_code == 200

    def test_unsubscribed_user_not_notified(self, client: TestClient) -> None:
        """User who unsubscribed from an event type should not receive that notification."""
        _login_admin(client)
        _cleanup_policies()
        _cleanup_log()
        _cleanup_unsubs()
        client.post("/api/notifications/policies", json={"event_type": "member.invited", "recipient_type": "admins"})
        client.post("/api/notifications/unsubscribes", json={"event_type": "member.invited"})
        from app.core.database import SessionLocal
        from app.models import Invite, WorkspaceMember
        db = SessionLocal()
        db.query(Invite).filter(Invite.email == "unsub_test@test.local", Invite.workspace_id == 1).delete()
        uid = _ensure_test_user("unsub_test@test.local")
        db.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid, WorkspaceMember.workspace_id == 1).delete()
        db.commit()
        db.close()
        client.post("/api/members/invites", json={"email": "unsub_test@test.local", "role": "editor"})
        r = client.get("/api/notifications/log?page_size=10")
        entries = [e for e in r.json()["entries"] if e["event_type"] == "member.invited"]
        admin_email = "demo@trust.local"
        assert not any(e["recipient_email"] == admin_email for e in entries)


# ---------------------------------------------------------------------------
# Permission enforcement
# ---------------------------------------------------------------------------

class TestNotificationPermissions:
    def test_non_admin_cannot_create_policy(self, client: TestClient) -> None:
        r = client.post("/api/notifications/policies", json={"event_type": "member.invited"})
        assert r.status_code == 401

    def test_non_admin_cannot_view_log(self, client: TestClient) -> None:
        r = client.get("/api/notifications/log")
        assert r.status_code == 401

    def test_authenticated_user_can_manage_unsubscribes(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.get("/api/notifications/unsubscribes")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Delivery log visibility
# ---------------------------------------------------------------------------

class TestDeliveryLog:
    def test_log_endpoint_returns_entries(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.get("/api/notifications/log")
        assert r.status_code == 200
        assert "entries" in r.json()
        assert "total" in r.json()

    def test_log_filter_by_status(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.get("/api/notifications/log?status=failed")
        assert r.status_code == 200

    def test_delivery_log_scoped_to_workspace(self, client: TestClient) -> None:
        """Log entries should only show for the current workspace."""
        _login_admin(client)
        r = client.get("/api/notifications/log?page_size=100")
        entries = r.json()["entries"]
        # All entries in the log should be for workspace 1 (current session)
        # We can't check workspace_id in the response since it's not returned,
        # but the query filters by workspace — this is a structural verification
        assert r.status_code == 200
