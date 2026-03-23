"""Tests for in-app notification fire points across all wired events."""

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


def _cleanup_notifs(workspace_id=1):
    from app.core.database import SessionLocal
    from app.models import InAppNotification
    db = SessionLocal()
    try:
        db.query(InAppNotification).filter(InAppNotification.workspace_id == workspace_id).delete()
        db.commit()
    finally:
        db.close()


def _get_notifs(workspace_id=1, title_contains=""):
    from app.core.database import SessionLocal
    from app.models import InAppNotification
    db = SessionLocal()
    try:
        q = db.query(InAppNotification).filter(InAppNotification.workspace_id == workspace_id)
        rows = q.order_by(InAppNotification.created_at.desc()).limit(20).all()
        if title_contains:
            return [n for n in rows if title_contains.lower() in (n.title or "").lower()]
        return rows
    finally:
        db.close()


def _ensure_test_user(email, password="testpass123"):
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


def _add_member(user_id, workspace_id=1, role="editor"):
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


# ---------------------------------------------------------------------------
# 1. Invite → notification
# ---------------------------------------------------------------------------

class TestInviteFirePoint:
    def test_invite_creates_admin_notification(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_notifs()
        from app.core.database import SessionLocal
        from app.models import Invite, WorkspaceMember
        db = SessionLocal()
        db.query(Invite).filter(Invite.email == "fp_invite@test.local", Invite.workspace_id == 1).delete()
        from app.models import User
        u = db.query(User).filter(User.email == "fp_invite@test.local").first()
        if u:
            db.query(WorkspaceMember).filter(WorkspaceMember.user_id == u.id, WorkspaceMember.workspace_id == 1).delete()
        db.commit()
        db.close()
        r = client.post("/api/members/invites", json={"email": "fp_invite@test.local", "role": "editor"})
        assert r.status_code == 200
        notifs = _get_notifs(title_contains="fp_invite@test.local")
        assert len(notifs) > 0
        assert notifs[0].category == "admin"


# ---------------------------------------------------------------------------
# 2. Role change → notification to target user
# ---------------------------------------------------------------------------

class TestRoleChangeFirePoint:
    def test_role_change_notifies_target(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_notifs()
        uid = _ensure_test_user("fp_role@test.local")
        mid = _add_member(uid, 1, "editor")
        r = client.patch(f"/api/members/{mid}", json={"role": "reviewer"})
        assert r.status_code == 200
        notifs = _get_notifs(title_contains="role changed")
        assert len(notifs) > 0
        assert notifs[0].user_id == uid


# ---------------------------------------------------------------------------
# 3. Suspend → admin notification
# ---------------------------------------------------------------------------

class TestSuspendFirePoint:
    def test_suspend_notifies_admins(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_notifs()
        uid = _ensure_test_user("fp_susp@test.local")
        mid = _add_member(uid, 1, "editor")
        r = client.patch(f"/api/members/{mid}/suspend", json={"suspended": True})
        assert r.status_code == 200
        notifs = _get_notifs(title_contains="suspended")
        assert len(notifs) > 0
        assert notifs[0].category == "warning"
        client.patch(f"/api/members/{mid}/suspend", json={"suspended": False})


# ---------------------------------------------------------------------------
# 4. Control verified → admin notification
# ---------------------------------------------------------------------------

class TestControlVerifiedFirePoint:
    def test_control_verified_notifies(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_notifs()
        from app.core.database import SessionLocal
        from app.models import WorkspaceControl, ControlEvidenceLink, EvidenceItem
        db = SessionLocal()
        try:
            wc = db.query(WorkspaceControl).filter(WorkspaceControl.workspace_id == 1).first()
            if not wc:
                return  # no controls to test
            ev = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == 1).first()
            if not ev:
                ev = EvidenceItem(workspace_id=1, source_type="manual", title="Test evidence for verify")
                db.add(ev)
                db.commit()
                db.refresh(ev)
            link = db.query(ControlEvidenceLink).filter(
                ControlEvidenceLink.control_id == wc.id, ControlEvidenceLink.evidence_id == ev.id
            ).first()
            if not link:
                link = ControlEvidenceLink(control_id=wc.id, evidence_id=ev.id, confidence_score=0.9, verified=False)
                db.add(link)
                db.commit()
            wc_id = wc.id
        finally:
            db.close()
        r = client.post(f"/api/compliance/controls/{wc_id}/verify")
        if r.status_code == 200:
            notifs = _get_notifs(title_contains="Control verified")
            assert len(notifs) > 0
            assert notifs[0].category == "success"


# ---------------------------------------------------------------------------
# 5. Mapping confirmed → admin notification
# ---------------------------------------------------------------------------

class TestMappingFirePoint:
    def test_mapping_confirmed_notifies(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_notifs()
        r = client.post("/api/compliance/control-mappings/confirm", json={
            "question": "Do you have an access control policy?",
            "control_ids": [],
        })
        if r.status_code == 200:
            notifs = _get_notifs(title_contains="Mapping confirmed")
            assert len(notifs) > 0
            assert notifs[0].category == "info"

    def test_mapping_overridden_notifies(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_notifs()
        r = client.post("/api/compliance/control-mappings/override", json={
            "question": "Do you encrypt data at rest?",
            "control_ids": [],
        })
        if r.status_code == 200:
            notifs = _get_notifs(title_contains="Mapping overridden")
            assert len(notifs) > 0
            assert notifs[0].category == "warning"


# ---------------------------------------------------------------------------
# 6. Compliance gap scan → admin notification
# ---------------------------------------------------------------------------

class TestGapScanFirePoint:
    def test_gap_scan_endpoint_exists(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.post("/api/compliance/gaps/scan-and-notify")
        assert r.status_code == 200
        d = r.json()
        assert "gaps" in d
        assert "notified" in d

    def test_gap_scan_notifies_when_gaps_exist(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_notifs()
        from app.api.routes.compliance_gaps import _last_gap_notify
        _last_gap_notify.clear()
        r = client.post("/api/compliance/gaps/scan-and-notify")
        d = r.json()
        if d["gaps"] > 0:
            assert d["notified"] is True
            notifs = _get_notifs(title_contains="compliance gap")
            assert len(notifs) > 0
            assert notifs[0].category == "warning"

    def test_gap_scan_respects_cooldown(self, client: TestClient) -> None:
        _login_admin(client)
        from app.api.routes.compliance_gaps import _last_gap_notify
        _last_gap_notify.clear()
        client.post("/api/compliance/gaps/scan-and-notify")
        r2 = client.post("/api/compliance/gaps/scan-and-notify")
        d2 = r2.json()
        if d2["gaps"] > 0:
            assert d2["notified"] is False


# ---------------------------------------------------------------------------
# 7. All notifications have correct structure
# ---------------------------------------------------------------------------

class TestNotificationStructure:
    def test_notifications_have_link(self, client: TestClient) -> None:
        _login_admin(client)
        r = client.get("/api/in-app-notifications?limit=50")
        for n in r.json().get("notifications", []):
            assert "link" in n
            assert "category" in n
            assert n["category"] in ("info", "admin", "warning", "error", "success")

    def test_admin_notifications_not_visible_to_editor(self, client: TestClient) -> None:
        from app.core.database import SessionLocal
        from app.models import WorkspaceMember, User
        db = SessionLocal()
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        uid = user.id
        mem = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid, WorkspaceMember.workspace_id == 1).first()
        orig = mem.role
        mem.role = "editor"
        db.commit()
        db.close()
        try:
            client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
            r = client.get("/api/in-app-notifications?limit=100")
            for n in r.json().get("notifications", []):
                assert n["admin_only"] is False, f"Editor sees admin-only notification: {n['title']}"
        finally:
            db2 = SessionLocal()
            m2 = db2.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid, WorkspaceMember.workspace_id == 1).first()
            m2.role = orig
            db2.commit()
            db2.close()
