"""Phase C — Email Notifications: policies, delivery, unsubscribe, permissions, isolation."""

import time  # noqa: F401

import pytest  # noqa: F401
from fastapi.testclient import TestClient


def _login_admin(client: TestClient) -> dict:
    from app.core.database import SessionLocal
    from app.models import WorkspaceMember, User

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        uid = user.id
        mem = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.user_id == uid, WorkspaceMember.workspace_id == 1)
            .first()
        )
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
        db.query(NotificationPolicy).filter(
            NotificationPolicy.workspace_id == workspace_id
        ).delete()
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
        db.query(NotificationUnsubscribe).filter(
            NotificationUnsubscribe.workspace_id == workspace_id
        ).delete()
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
            user = User(
                email=email, password_hash=hash_password(password), display_name=email.split("@")[0]
            )
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
        existing = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.user_id == user_id, WorkspaceMember.workspace_id == workspace_id
            )
            .first()
        )
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
        r = client.post(
            "/api/notifications/policies",
            json={
                "event_type": "member.invited",
                "recipient_type": "admins",
            },
        )
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
        r = client.post(
            "/api/notifications/policies",
            json={"event_type": "member.joined", "recipient_type": "admins"},
        )
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
        client.post(
            "/api/notifications/policies",
            json={"event_type": "member.suspended", "recipient_type": "all"},
        )
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
        from app.services.notification_service import fire_notification

        _login_admin(client)
        _cleanup_policies()
        _cleanup_log()
        client.post(
            "/api/notifications/policies",
            json={"event_type": "member.invited", "recipient_type": "admins"},
        )
        from app.core.database import SessionLocal

        db = SessionLocal()
        try:
            fire_notification(
                db,
                1,
                "member.invited",
                detail="notif_test@test.local invited as editor",
                workspace_name="Test",
            )
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
        r = client.post(
            "/api/notifications/policies",
            json={"event_type": "member.role_changed", "recipient_type": "admins"},
        )
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
        client.post(
            "/api/notifications/policies",
            json={
                "event_type": "member.removed",
                "recipient_type": "role",
                "recipient_value": "admin",
            },
        )
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
        client.post(
            "/api/notifications/policies",
            json={"event_type": "member.suspended", "recipient_type": "all"},
        )
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
        client.post(
            "/api/notifications/policies",
            json={"event_type": "member.invited", "recipient_type": "admins"},
        )
        client.post("/api/notifications/unsubscribes", json={"event_type": "member.invited"})
        from app.core.database import SessionLocal
        from app.models import Invite, WorkspaceMember

        db = SessionLocal()
        db.query(Invite).filter(
            Invite.email == "unsub_test@test.local", Invite.workspace_id == 1
        ).delete()
        uid = _ensure_test_user("unsub_test@test.local")
        db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == uid, WorkspaceMember.workspace_id == 1
        ).delete()
        db.commit()
        db.close()
        client.post(
            "/api/members/invites", json={"email": "unsub_test@test.local", "role": "editor"}
        )
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
        """Workspace B cannot read workspace A's log rows or delivery attempts, and the reverse.

        Covers the list and status filter, a foreign workspace_id query, an admin
        session, and an admin API key. Guessing the other workspace's id is a 404
        with no row body.
        """
        from app.core.database import SessionLocal
        from app.core.password import hash_password
        from app.models import (
            ApiKey,
            InAppNotification,
            NotificationDeliveryAttempt,
            NotificationLog,
            User,
            WorkspaceMember,
        )

        marker_a = "bug007-marker-workspace-a"
        marker_b = "bug007-marker-workspace-b"
        raw_key_a = "fake-bug007-workspace-a"
        raw_key_b = "fake-bug007-workspace-b"
        email_a = "bug007-a@example.com"
        email_b = "bug007-b@example.com"

        def _user(db, email: str) -> User:
            user = db.query(User).filter(User.email == email).one_or_none()
            if user is None:
                user = User(
                    email=email,
                    password_hash=hash_password("j"),
                    display_name=email,
                )
                db.add(user)
                db.flush()
            return user

        def _admin(db, user: User, workspace_id: int) -> None:
            mem = (
                db.query(WorkspaceMember)
                .filter(
                    WorkspaceMember.user_id == user.id,
                    WorkspaceMember.workspace_id == workspace_id,
                )
                .one_or_none()
            )
            if mem is None:
                db.add(WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role="admin"))
            else:
                mem.role = "admin"

        db = SessionLocal()
        try:
            user_a = _user(db, email_a)
            user_b = _user(db, email_b)
            _admin(db, user_a, 1)
            _admin(db, user_b, 2)
            note_a = InAppNotification(
                workspace_id=1,
                user_id=user_a.id,
                title="Workspace A",
                body=marker_a,
                is_read=False,
            )
            note_b = InAppNotification(
                workspace_id=2,
                user_id=user_b.id,
                title="Workspace B",
                body=marker_b,
                is_read=True,
            )
            db.add(note_a)
            db.add(note_b)
            db.flush()
            log_a = NotificationLog(
                workspace_id=1,
                event_type="bug007.isolation",
                channel="email",
                recipient_email="a@example.com",
                subject=marker_a,
                status="sent",
            )
            log_b = NotificationLog(
                workspace_id=2,
                event_type="bug007.isolation",
                channel="email",
                recipient_email="b@example.com",
                subject=marker_b,
                status="failed",
            )
            db.add(log_a)
            db.add(log_b)
            db.flush()
            own_attempt = NotificationDeliveryAttempt(
                workspace_id=1,
                event_type="bug007.isolation",
                channel="in_app",
                recipient=marker_a,
                user_id=user_a.id,
                dedupe_key="bug007:1:own",
                state="sent",
                rendered_subject=marker_a,
                rendered_body=marker_a,
                in_app_notification_id=note_a.id,
                notification_log_id=log_a.id,
            )
            poisoned = NotificationDeliveryAttempt(
                workspace_id=1,
                event_type="bug007.isolation",
                channel="in_app",
                recipient=marker_a,
                user_id=user_a.id,
                dedupe_key="bug007:1:poison",
                state="sent",
                rendered_subject=marker_a,
                rendered_body=marker_a,
                in_app_notification_id=note_b.id,
            )
            attempt_b = NotificationDeliveryAttempt(
                workspace_id=2,
                event_type="bug007.isolation",
                channel="email",
                recipient=marker_b,
                user_id=user_b.id,
                dedupe_key="bug007:2:own",
                state="dead-lettered",
                rendered_subject=marker_b,
                rendered_body=marker_b,
                notification_log_id=log_b.id,
            )
            db.add(own_attempt)
            db.add(poisoned)
            db.add(attempt_b)
            import hashlib

            for raw, workspace_id in ((raw_key_a, 1), (raw_key_b, 2)):
                digest = hashlib.sha256(raw.encode()).hexdigest()
                existing = db.query(ApiKey).filter(ApiKey.key_hash == digest).one_or_none()
                if existing is None:
                    db.add(
                        ApiKey(
                            workspace_id=workspace_id,
                            key_hash=digest,
                            label="fake-bug007",
                            role="admin",
                        )
                    )
                else:
                    existing.workspace_id = workspace_id
                    existing.role = "admin"
            db.commit()
            ids = {
                "log_a": log_a.id,
                "log_b": log_b.id,
                "attempt_a": own_attempt.id,
                "poison": poisoned.id,
                "attempt_b": attempt_b.id,
            }
        finally:
            db.close()

        def _assert_isolated(response_log, response_attempts, own: str, other: str) -> None:
            assert response_log.status_code == 200, response_log.text
            assert response_attempts.status_code == 200, response_attempts.text
            assert own in response_log.text
            assert other not in response_log.text
            assert own in response_attempts.text
            assert other not in response_attempts.text

        def _lists(actor: TestClient, foreign_workspace_id: int, headers: dict | None = None):
            log = actor.get(
                f"/api/notifications/log?page_size=200&workspace_id={foreign_workspace_id}",
                headers=headers,
            )
            attempts = actor.get(
                "/api/notifications/delivery-attempts"
                f"?page_size=200&workspace_id={foreign_workspace_id}",
                headers=headers,
            )
            return log, attempts

        try:
            logged_a = client.post("/api/auth/login", json={"email": email_a, "password": "j"})
            assert logged_a.status_code == 200, logged_a.text
            log_a_resp, attempts_a = _lists(client, 2)
            _assert_isolated(log_a_resp, attempts_a, marker_a, marker_b)
            failed = client.get("/api/notifications/log?page_size=200&status=failed")
            assert failed.status_code == 200
            assert marker_b not in failed.text
            attempts_body = attempts_a.json()["attempts"]
            own_row = next(row for row in attempts_body if row["id"] == ids["attempt_a"])
            poison_row = next(row for row in attempts_body if row["id"] == ids["poison"])
            assert own_row["is_read"] is False
            assert poison_row["is_read"] is None
            assert marker_b not in str(poison_row)

            for path in (
                f"/api/notifications/log/{ids['log_b']}",
                f"/api/notifications/delivery-attempts/{ids['attempt_b']}",
            ):
                guessed = client.get(path)
                assert guessed.status_code == 404, guessed.text
                assert guessed.status_code != 403
                assert marker_b not in guessed.text
                assert marker_a not in guessed.text

            client.cookies.clear()
            logged_b = client.post("/api/auth/login", json={"email": email_b, "password": "j"})
            assert logged_b.status_code == 200, logged_b.text
            assert logged_b.json()["workspace_id"] == 2
            log_b_resp, attempts_b = _lists(client, 1)
            _assert_isolated(log_b_resp, attempts_b, marker_b, marker_a)
            sent = client.get("/api/notifications/log?page_size=200&status=sent")
            assert sent.status_code == 200
            assert marker_a not in sent.text
            for path in (
                f"/api/notifications/log/{ids['log_a']}",
                f"/api/notifications/delivery-attempts/{ids['attempt_a']}",
                f"/api/notifications/delivery-attempts/{ids['poison']}",
            ):
                guessed = client.get(path)
                assert guessed.status_code == 404, guessed.text
                assert marker_a not in guessed.text

            client.cookies.clear()
            from app.main import app

            key_client = TestClient(
                app, base_url="http://localhost", headers={"Origin": "http://localhost"}
            )
            log_key_a, attempts_key_a = _lists(
                key_client, 2, headers={"Authorization": f"Bearer {raw_key_a}"}
            )
            _assert_isolated(log_key_a, attempts_key_a, marker_a, marker_b)
            log_key_b, attempts_key_b = _lists(
                key_client, 1, headers={"Authorization": f"Bearer {raw_key_b}"}
            )
            _assert_isolated(log_key_b, attempts_key_b, marker_b, marker_a)
            guessed_key = key_client.get(
                f"/api/notifications/log/{ids['log_a']}",
                headers={"Authorization": f"Bearer {raw_key_b}"},
            )
            assert guessed_key.status_code == 404
            assert marker_a not in guessed_key.text
        finally:
            db = SessionLocal()
            try:
                db.query(NotificationDeliveryAttempt).filter(
                    NotificationDeliveryAttempt.dedupe_key.in_(
                        ["bug007:1:own", "bug007:1:poison", "bug007:2:own"]
                    )
                ).delete(synchronize_session=False)
                db.query(NotificationLog).filter(
                    NotificationLog.event_type == "bug007.isolation"
                ).delete(synchronize_session=False)
                db.query(InAppNotification).filter(
                    InAppNotification.body.in_([marker_a, marker_b])
                ).delete(synchronize_session=False)
                db.query(ApiKey).filter(ApiKey.label == "fake-bug007").delete(
                    synchronize_session=False
                )
                db.commit()
            finally:
                db.close()
