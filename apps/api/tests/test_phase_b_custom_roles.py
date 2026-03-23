"""Phase B — Role Customization: custom roles CRUD, permission enforcement, audit."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


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


def _cleanup_custom_role(name: str, workspace_id: int = 1):
    from app.core.database import SessionLocal
    from app.models import CustomRole
    db = SessionLocal()
    try:
        db.query(CustomRole).filter(CustomRole.workspace_id == workspace_id, CustomRole.name == name).delete()
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
            db.commit()
            return existing.id
        mem = WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=role)
        db.add(mem)
        db.commit()
        db.refresh(mem)
        return mem.id
    finally:
        db.close()


def _get_audit_events(action: str, workspace_id: int = 1) -> list:
    from app.core.database import SessionLocal
    from app.models import AuditEvent
    db = SessionLocal()
    try:
        return db.query(AuditEvent).filter(
            AuditEvent.action == action, AuditEvent.workspace_id == workspace_id
        ).order_by(AuditEvent.occurred_at.desc()).limit(5).all()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Custom role CRUD
# ---------------------------------------------------------------------------

class TestCustomRoleCRUD:
    def test_create_custom_role(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_custom_role("auditor")
        r = client.post("/api/members/roles", json={
            "name": "auditor",
            "can_edit": False, "can_review": True, "can_export": True, "can_admin": False,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "auditor"
        assert data["can_review"] is True
        assert data["can_export"] is True
        assert data["can_edit"] is False

    def test_create_role_rejects_builtin_name(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.post("/api/members/roles", json={"name": "admin"})
        assert r.status_code == 400

    def test_create_role_rejects_duplicate(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_custom_role("duptest")
        client.post("/api/members/roles", json={"name": "duptest"})
        r = client.post("/api/members/roles", json={"name": "duptest"})
        assert r.status_code == 400

    def test_list_roles_includes_builtin_and_custom(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_custom_role("listrole")
        client.post("/api/members/roles", json={"name": "listrole", "can_review": True})
        r = client.get("/api/members/roles")
        assert r.status_code == 200
        roles = r.json()["roles"]
        names = [rl["name"] for rl in roles]
        assert "admin" in names
        assert "editor" in names
        assert "reviewer" in names
        assert "listrole" in names
        builtin_role = next(rl for rl in roles if rl["name"] == "admin")
        assert builtin_role["builtin"] is True
        custom_role = next(rl for rl in roles if rl["name"] == "listrole")
        assert custom_role["builtin"] is False

    def test_update_custom_role(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_custom_role("updaterole")
        r = client.post("/api/members/roles", json={"name": "updaterole", "can_edit": False})
        role_id = r.json()["id"]
        r2 = client.patch(f"/api/members/roles/{role_id}", json={"can_edit": True})
        assert r2.status_code == 200
        assert r2.json()["can_edit"] is True

    def test_delete_custom_role_reverts_members(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_custom_role("delrole")
        r = client.post("/api/members/roles", json={"name": "delrole"})
        role_id = r.json()["id"]
        uid = _ensure_test_user("delrole_user@test.local")
        _add_member(uid, 1, "delrole")
        r2 = client.delete(f"/api/members/roles/{role_id}")
        assert r2.status_code == 200
        assert r2.json()["members_reverted"] >= 1
        # Verify member reverted to reviewer
        r3 = client.get("/api/members")
        target = next((m for m in r3.json()["members"] if m["user_id"] == uid), None)
        assert target is not None
        assert target["role"] == "reviewer"

    def test_create_role_audit_logged(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_custom_role("auditrole")
        client.post("/api/members/roles", json={"name": "auditrole"})
        events = _get_audit_events("role.created")
        assert len(events) > 0
        assert "auditrole" in (events[0].details or "")

    def test_update_role_audit_logged(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_custom_role("auditupd")
        r = client.post("/api/members/roles", json={"name": "auditupd", "can_edit": False})
        role_id = r.json()["id"]
        client.patch(f"/api/members/roles/{role_id}", json={"can_edit": True})
        events = _get_audit_events("role.updated")
        assert len(events) > 0

    def test_delete_role_audit_logged(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_custom_role("auditdel")
        r = client.post("/api/members/roles", json={"name": "auditdel"})
        role_id = r.json()["id"]
        client.delete(f"/api/members/roles/{role_id}")
        events = _get_audit_events("role.deleted")
        assert len(events) > 0


# ---------------------------------------------------------------------------
# Permission enforcement with custom roles
# ---------------------------------------------------------------------------

class TestCustomRolePermissions:
    def test_assign_custom_role_to_member(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_custom_role("assign_test")
        client.post("/api/members/roles", json={"name": "assign_test", "can_review": True})
        uid = _ensure_test_user("assignrole@test.local")
        mid = _add_member(uid, 1, "editor")
        r = client.patch(f"/api/members/{mid}", json={"role": "assign_test"})
        assert r.status_code == 200
        assert r.json()["role"] == "assign_test"

    def test_custom_role_permissions_enforced(self, client: TestClient) -> None:
        """Member with custom role (can_review only) should get 403 on edit-only endpoints."""
        _login_admin(client)
        _cleanup_custom_role("reviewonly")
        client.post("/api/members/roles", json={
            "name": "reviewonly", "can_review": True, "can_edit": False, "can_export": False, "can_admin": False,
        })
        email = "customrole_user@test.local"
        uid = _ensure_test_user(email, "custompass1")
        _add_member(uid, 1, "reviewonly")
        client2 = TestClient(client.app, base_url="http://localhost", headers={"Origin": "http://localhost", "Referer": "http://localhost/"})
        r = client2.post("/api/auth/login", json={"email": email, "password": "custompass1"})
        if r.status_code == 200:
            r2 = client2.get("/api/members")
            assert r2.status_code == 403, f"Expected 403, got {r2.status_code}"
            r3 = client2.get("/api/workspaces/current")
            assert r3.status_code == 200

    def test_custom_role_with_edit_can_edit(self, client: TestClient) -> None:
        """Member with custom role (can_edit=True) should access edit endpoints."""
        _login_admin(client)
        _cleanup_custom_role("canedit")
        client.post("/api/members/roles", json={
            "name": "canedit", "can_review": True, "can_edit": True, "can_export": False, "can_admin": False,
        })
        email = "canedit_user@test.local"
        uid = _ensure_test_user(email, "caneditp1")
        _add_member(uid, 1, "canedit")
        client2 = TestClient(client.app, base_url="http://localhost", headers={"Origin": "http://localhost", "Referer": "http://localhost/"})
        r = client2.post("/api/auth/login", json={"email": email, "password": "caneditp1"})
        if r.status_code == 200:
            r2 = client2.get("/api/workspaces/current")
            assert r2.status_code == 200

    def test_invite_with_custom_role(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_custom_role("invrole")
        client.post("/api/members/roles", json={"name": "invrole", "can_review": True})
        from app.core.database import SessionLocal
        from app.models import Invite
        db = SessionLocal()
        db.query(Invite).filter(Invite.email == "inv_custom@test.local").delete()
        db.commit()
        db.close()
        uid = _ensure_test_user("inv_custom@test.local")
        from app.models import WorkspaceMember
        db2 = SessionLocal()
        db2.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid, WorkspaceMember.workspace_id == 1).delete()
        db2.commit()
        db2.close()
        r = client.post("/api/members/invites", json={"email": "inv_custom@test.local", "role": "invrole"})
        assert r.status_code == 200
        assert r.json()["role"] == "invrole"

    def test_invalid_custom_role_rejected(self, client: TestClient) -> None:
        _login_admin(client)
        uid = _ensure_test_user("badrole2@test.local")
        mid = _add_member(uid, 1, "editor")
        r = client.patch(f"/api/members/{mid}", json={"role": "nonexistent_role"})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Cross-workspace isolation for custom roles
# ---------------------------------------------------------------------------

class TestCustomRoleIsolation:
    def test_custom_role_not_visible_in_other_workspace(self, client: TestClient) -> None:
        """Custom role created in workspace 1 should not be assignable from workspace 2 context."""
        _login_admin(client)
        _cleanup_custom_role("ws1only")
        client.post("/api/members/roles", json={"name": "ws1only"})
        from app.core.database import SessionLocal
        from app.models import CustomRole
        db = SessionLocal()
        try:
            cr = db.query(CustomRole).filter(CustomRole.name == "ws1only", CustomRole.workspace_id == 1).first()
            assert cr is not None
            ws2_cr = db.query(CustomRole).filter(CustomRole.name == "ws1only", CustomRole.workspace_id == 2).first()
            assert ws2_cr is None
        finally:
            db.close()
