"""Phase A — User Admin Foundation: comprehensive tests for invite, remove, suspend, roles, permissions, audit."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login_admin(client: TestClient) -> dict:
    """Log in as admin and return session info. Promotes demo user to admin for the test."""
    from app.core.database import SessionLocal
    from app.models import WorkspaceMember, User
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        mem = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == 1,
        ).first()
        if mem.role != "admin":
            mem.role = "admin"
            db.commit()
    finally:
        db.close()
    r = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert r.status_code == 200
    return r.json()


def _ensure_test_user(email: str, password: str = "testpass123") -> int:
    """Ensure a user exists; return user_id."""
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
    """Add user as workspace member; return member_id."""
    from app.core.database import SessionLocal
    from app.models import WorkspaceMember
    db = SessionLocal()
    try:
        existing = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.workspace_id == workspace_id,
        ).first()
        if existing:
            return existing.id
        mem = WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=role)
        db.add(mem)
        db.commit()
        db.refresh(mem)
        return mem.id
    finally:
        db.close()


def _remove_member_direct(user_id: int, workspace_id: int = 1) -> None:
    from app.core.database import SessionLocal
    from app.models import WorkspaceMember
    db = SessionLocal()
    try:
        db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.workspace_id == workspace_id,
        ).delete()
        db.commit()
    finally:
        db.close()


def _cleanup_invites(email: str, workspace_id: int = 1) -> None:
    from app.core.database import SessionLocal
    from app.models import Invite
    db = SessionLocal()
    try:
        db.query(Invite).filter(Invite.email == email, Invite.workspace_id == workspace_id).delete()
        db.commit()
    finally:
        db.close()


def _get_audit_events(action: str, workspace_id: int = 1) -> list:
    from app.core.database import SessionLocal
    from app.models import AuditEvent
    db = SessionLocal()
    try:
        return db.query(AuditEvent).filter(
            AuditEvent.action == action,
            AuditEvent.workspace_id == workspace_id,
        ).order_by(AuditEvent.occurred_at.desc()).limit(5).all()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Invite tests
# ---------------------------------------------------------------------------

class TestInviteFlow:
    def test_create_invite_returns_invite(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_invites("invitee@test.local")
        _remove_member_direct(_ensure_test_user("invitee@test.local"))
        r = client.post("/api/members/invites", json={"email": "invitee@test.local", "role": "editor"})
        assert r.status_code == 200
        data = r.json()
        assert data["email"] == "invitee@test.local"
        assert data["role"] == "editor"
        assert "id" in data

    def test_create_invite_rejects_duplicate(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_invites("dup@test.local")
        _remove_member_direct(_ensure_test_user("dup@test.local"))
        client.post("/api/members/invites", json={"email": "dup@test.local", "role": "editor"})
        r = client.post("/api/members/invites", json={"email": "dup@test.local", "role": "editor"})
        assert r.status_code == 400

    def test_create_invite_rejects_existing_member(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.post("/api/members/invites", json={"email": "demo@trust.local", "role": "editor"})
        assert r.status_code == 400

    def test_create_invite_rejects_invalid_role(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.post("/api/members/invites", json={"email": "norole@test.local", "role": "superadmin"})
        assert r.status_code == 400

    def test_create_invite_audit_logged(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_invites("auditinv@test.local")
        _remove_member_direct(_ensure_test_user("auditinv@test.local"))
        client.post("/api/members/invites", json={"email": "auditinv@test.local", "role": "reviewer"})
        events = _get_audit_events("auth.invite_created")
        assert len(events) > 0
        assert "auditinv@test.local" in (events[0].details or "")

    def test_revoke_invite(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_invites("revokeme@test.local")
        _remove_member_direct(_ensure_test_user("revokeme@test.local"))
        r = client.post("/api/members/invites", json={"email": "revokeme@test.local", "role": "editor"})
        inv_id = r.json()["id"]
        r2 = client.delete(f"/api/members/invites/{inv_id}")
        assert r2.status_code == 200
        events = _get_audit_events("auth.invite_revoked")
        assert len(events) > 0

    def test_list_invites(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.get("/api/members/invites")
        assert r.status_code == 200
        assert "invites" in r.json()

    def test_accept_invite_new_user(self, client: TestClient) -> None:
        """Full flow: create invite, verify code, accept as new user with password."""
        from unittest.mock import patch

        _login_admin(client)
        email = "newacceptee@test.local"
        _cleanup_invites(email)
        _remove_member_direct(_ensure_test_user(email))
        from app.core.database import SessionLocal
        from app.models import User

        db = SessionLocal()
        db.query(User).filter(User.email == email).delete()
        db.commit()
        db.close()

        captured: dict[str, str] = {}

        def _capture_send(to, inviter_name, workspace_name, verify_url, verification_code):
            captured["code"] = verification_code
            return True

        with patch("app.api.routes.members.send_invite_email", side_effect=_capture_send):
            r = client.post("/api/members/invites", json={"email": email, "role": "editor"})
        assert r.status_code == 200
        assert "code" in captured

        rv = client.post(
            "/api/auth/verify-invite-code",
            json={"email": email, "code": captured["code"]},
        )
        assert rv.status_code == 200
        token = rv.json().get("token")
        assert token and isinstance(token, str)

        ra = client.post(
            "/api/auth/accept-invite",
            json={"token": token, "password": "newacceptpass123"},
        )
        assert ra.status_code == 200
        login_r = client.post("/api/auth/login", json={"email": email, "password": "newacceptpass123"})
        assert login_r.status_code == 200


# ---------------------------------------------------------------------------
# Role change tests
# ---------------------------------------------------------------------------

class TestRoleChange:
    def test_update_role(self, client: TestClient) -> None:
        _login_admin(client)
        uid = _ensure_test_user("roletest@test.local")
        mid = _add_member(uid, 1, "editor")
        r = client.patch(f"/api/members/{mid}", json={"role": "reviewer"})
        assert r.status_code == 200
        assert r.json()["role"] == "reviewer"

    def test_update_role_audit_logged(self, client: TestClient) -> None:
        _login_admin(client)
        uid = _ensure_test_user("roleaudit@test.local")
        mid = _add_member(uid, 1, "editor")
        client.patch(f"/api/members/{mid}", json={"role": "admin"})
        events = _get_audit_events("auth.role_changed")
        assert len(events) > 0

    def test_update_role_rejects_invalid(self, client: TestClient) -> None:
        _login_admin(client)
        uid = _ensure_test_user("badrole@test.local")
        mid = _add_member(uid, 1, "editor")
        r = client.patch(f"/api/members/{mid}", json={"role": "owner"})
        assert r.status_code == 400

    def test_last_admin_cannot_demote_self(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.get("/api/members")
        members = r.json()["members"]
        from app.core.database import SessionLocal
        from app.models import User
        db = SessionLocal()
        admin_user = db.query(User).filter(User.email == "demo@trust.local").first()
        db.close()
        my_mem = next((m for m in members if m["user_id"] == admin_user.id), None)
        if my_mem:
            admin_count = sum(1 for m in members if m["role"] == "admin")
            if admin_count <= 1:
                r2 = client.patch(f"/api/members/{my_mem['id']}", json={"role": "editor"})
                assert r2.status_code == 400


# ---------------------------------------------------------------------------
# Remove member tests
# ---------------------------------------------------------------------------

class TestRemoveMember:
    def test_remove_member(self, client: TestClient) -> None:
        _login_admin(client)
        uid = _ensure_test_user("removeme@test.local")
        mid = _add_member(uid, 1, "editor")
        r = client.delete(f"/api/members/{mid}")
        assert r.status_code == 200

    def test_remove_member_audit_logged(self, client: TestClient) -> None:
        _login_admin(client)
        uid = _ensure_test_user("removeaudit@test.local")
        mid = _add_member(uid, 1, "editor")
        client.delete(f"/api/members/{mid}")
        events = _get_audit_events("auth.member_removed")
        assert len(events) > 0

    def test_last_admin_cannot_remove_self(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.get("/api/members")
        members = r.json()["members"]
        from app.core.database import SessionLocal
        from app.models import User
        db = SessionLocal()
        admin_user = db.query(User).filter(User.email == "demo@trust.local").first()
        db.close()
        my_mem = next((m for m in members if m["user_id"] == admin_user.id), None)
        if my_mem:
            admin_count = sum(1 for m in members if m["role"] == "admin")
            if admin_count <= 1:
                r2 = client.delete(f"/api/members/{my_mem['id']}")
                assert r2.status_code == 400


# ---------------------------------------------------------------------------
# Suspend tests
# ---------------------------------------------------------------------------

class TestSuspendMember:
    def test_suspend_member(self, client: TestClient) -> None:
        _login_admin(client)
        uid = _ensure_test_user("suspendme@test.local")
        mid = _add_member(uid, 1, "editor")
        r = client.patch(f"/api/members/{mid}/suspend", json={"suspended": True})
        assert r.status_code == 200
        assert r.json()["suspended"] is True

    def test_unsuspend_member(self, client: TestClient) -> None:
        _login_admin(client)
        uid = _ensure_test_user("unsuspend@test.local")
        mid = _add_member(uid, 1, "editor")
        client.patch(f"/api/members/{mid}/suspend", json={"suspended": True})
        r = client.patch(f"/api/members/{mid}/suspend", json={"suspended": False})
        assert r.status_code == 200
        assert r.json()["suspended"] is False

    def test_cannot_suspend_self(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.get("/api/members")
        members = r.json()["members"]
        from app.core.database import SessionLocal
        from app.models import User
        db = SessionLocal()
        admin_user = db.query(User).filter(User.email == "demo@trust.local").first()
        db.close()
        my_mem = next((m for m in members if m["user_id"] == admin_user.id), None)
        if my_mem:
            r2 = client.patch(f"/api/members/{my_mem['id']}/suspend", json={"suspended": True})
            assert r2.status_code == 400

    def test_suspend_audit_logged(self, client: TestClient) -> None:
        _login_admin(client)
        uid = _ensure_test_user("suspendaudit@test.local")
        mid = _add_member(uid, 1, "editor")
        client.patch(f"/api/members/{mid}/suspend", json={"suspended": True})
        events = _get_audit_events("auth.member_suspended")
        assert len(events) > 0

    def test_suspended_member_blocked(self, client: TestClient) -> None:
        """A suspended member should get 403 when trying to use the API."""
        from app.core.database import SessionLocal
        from app.core.password import hash_password
        from app.models import User, WorkspaceMember
        email = "suspended_user@test.local"
        uid = _ensure_test_user(email, "testpass1")
        mid = _add_member(uid, 1, "editor")
        _login_admin(client)
        client.patch(f"/api/members/{mid}/suspend", json={"suspended": True})
        client2 = TestClient(client.app, base_url="http://localhost", headers={"Origin": "http://localhost", "Referer": "http://localhost/"})
        r = client2.post("/api/auth/login", json={"email": email, "password": "testpass1"})
        if r.status_code == 200:
            r2 = client2.get("/api/workspaces/current")
            assert r2.status_code == 403

    def test_member_list_shows_suspended(self, client: TestClient) -> None:
        _login_admin(client)
        uid = _ensure_test_user("showsusp@test.local")
        mid = _add_member(uid, 1, "editor")
        client.patch(f"/api/members/{mid}/suspend", json={"suspended": True})
        r = client.get("/api/members")
        members = r.json()["members"]
        target = next((m for m in members if m["user_id"] == uid), None)
        assert target is not None
        assert target["suspended"] is True


# ---------------------------------------------------------------------------
# Permission enforcement tests
# ---------------------------------------------------------------------------

class TestPermissionEnforcement:
    def test_non_admin_cannot_list_members(self, client: TestClient) -> None:
        """Editor role should get 403 on admin-only endpoints."""
        from app.core.database import SessionLocal
        from app.models import WorkspaceMember, User
        db = SessionLocal()
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        user_id = user.id
        mem = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == user_id, WorkspaceMember.workspace_id == 1
        ).first()
        original_role = mem.role
        mem.role = "editor"
        db.commit()
        db.close()
        try:
            client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
            r = client.get("/api/members")
            assert r.status_code == 403
        finally:
            db2 = SessionLocal()
            mem2 = db2.query(WorkspaceMember).filter(
                WorkspaceMember.user_id == user_id, WorkspaceMember.workspace_id == 1
            ).first()
            mem2.role = original_role
            db2.commit()
            db2.close()

    def test_non_admin_cannot_invite(self, client: TestClient) -> None:
        from app.core.database import SessionLocal
        from app.models import WorkspaceMember, User
        db = SessionLocal()
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        user_id = user.id
        mem = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == user_id, WorkspaceMember.workspace_id == 1
        ).first()
        original_role = mem.role
        mem.role = "editor"
        db.commit()
        db.close()
        try:
            client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
            r = client.post("/api/members/invites", json={"email": "nope@test.local", "role": "editor"})
            assert r.status_code == 403
        finally:
            db2 = SessionLocal()
            mem2 = db2.query(WorkspaceMember).filter(
                WorkspaceMember.user_id == user_id, WorkspaceMember.workspace_id == 1
            ).first()
            mem2.role = original_role
            db2.commit()
            db2.close()

    def test_unauthenticated_cannot_access_members(self, client: TestClient) -> None:
        r = client.get("/api/members")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Audit log viewer tests
# ---------------------------------------------------------------------------

class TestAuditLogViewer:
    def test_audit_events_endpoint(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.get("/api/audit/events")
        assert r.status_code == 200
        data = r.json()
        assert "events" in data
        assert "total" in data
        assert "page" in data

    def test_audit_events_filter_by_action(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.get("/api/audit/events?action=auth.")
        assert r.status_code == 200
        for ev in r.json()["events"]:
            assert ev["action"].startswith("auth.")

    def test_audit_events_requires_admin(self, client: TestClient) -> None:
        r = client.get("/api/audit/events")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Cross-workspace isolation tests
# ---------------------------------------------------------------------------

class TestWorkspaceIsolation:
    def test_cannot_see_other_workspace_members(self, client: TestClient) -> None:
        """Members endpoint only returns members for session workspace."""
        _login_admin(client)
        uid = _ensure_test_user("ws2only@test.local")
        _add_member(uid, 2, "editor")
        _remove_member_direct(uid, 1)
        r = client.get("/api/members")
        members = r.json()["members"]
        emails = [m["email"] for m in members]
        assert "ws2only@test.local" not in emails

    def test_cannot_modify_other_workspace_member(self, client: TestClient) -> None:
        """Cannot change role of member in a different workspace."""
        _login_admin(client)
        uid = _ensure_test_user("ws2mod@test.local")
        mid = _add_member(uid, 2, "editor")
        r = client.patch(f"/api/members/{mid}", json={"role": "admin"})
        assert r.status_code == 404
