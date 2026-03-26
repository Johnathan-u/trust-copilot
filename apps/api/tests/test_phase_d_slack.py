"""Phase D — Slack Notifications: connect, configure, delivery, isolation, audit."""

import json
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


def _cleanup_slack(workspace_id: int = 1):
    from app.core.database import SessionLocal
    from app.models import SlackIntegration
    db = SessionLocal()
    try:
        db.query(SlackIntegration).filter(SlackIntegration.workspace_id == workspace_id).delete()
        db.commit()
    finally:
        db.close()


def _cleanup_slack_log(workspace_id: int = 1):
    from app.core.database import SessionLocal
    from app.models import NotificationLog
    db = SessionLocal()
    try:
        db.query(NotificationLog).filter(NotificationLog.workspace_id == workspace_id, NotificationLog.channel == "slack").delete()
        db.commit()
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
# Connect / Disconnect
# ---------------------------------------------------------------------------

class TestSlackConnect:
    def test_connect_slack(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_slack()
        r = client.post("/api/slack/connect", json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": "C_TEST_001",
            "channel_name": "test-alerts",
            "event_types": ["member.invited", "export.completed"],
        })
        assert r.status_code == 200
        assert r.json()["connected"] is True

    def test_connect_rejects_short_token(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_slack()
        r = client.post("/api/slack/connect", json={"bot_token": "short", "channel_id": "C001"})
        assert r.status_code == 400

    def test_connect_rejects_missing_channel(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_slack()
        r = client.post("/api/slack/connect", json={"bot_token": "xoxb-test-token-fake-for-testing", "channel_id": ""})
        assert r.status_code == 400

    def test_status_shows_connected(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_slack()
        client.post("/api/slack/connect", json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": "C_TEST_001", "channel_name": "alerts",
        })
        r = client.get("/api/slack/status")
        assert r.status_code == 200
        d = r.json()
        assert d["connected"] is True
        assert d["channel_id"] == "C_TEST_001"
        assert d["enabled"] is True

    def test_disconnect(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_slack()
        client.post("/api/slack/connect", json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": "C_TEST_001",
        })
        r = client.delete("/api/slack/disconnect")
        assert r.status_code == 200
        r2 = client.get("/api/slack/status")
        assert r2.json()["connected"] is False

    def test_connect_audit_logged(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_slack()
        client.post("/api/slack/connect", json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": "C_TEST_001",
        })
        events = _get_audit_events("slack.connected")
        assert len(events) > 0

    def test_disconnect_audit_logged(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_slack()
        client.post("/api/slack/connect", json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": "C_TEST_001",
        })
        client.delete("/api/slack/disconnect")
        events = _get_audit_events("slack.disconnected")
        assert len(events) > 0


# ---------------------------------------------------------------------------
# Configure
# ---------------------------------------------------------------------------

class TestSlackConfigure:
    def test_update_channel(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_slack()
        client.post("/api/slack/connect", json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": "C_OLD",
        })
        r = client.patch("/api/slack/configure", json={"channel_id": "C_NEW", "channel_name": "new-ch"})
        assert r.status_code == 200
        assert r.json()["channel_id"] == "C_NEW"

    def test_toggle_enabled(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_slack()
        client.post("/api/slack/connect", json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": "C_TEST",
        })
        r = client.patch("/api/slack/configure", json={"enabled": False})
        assert r.status_code == 200
        assert r.json()["enabled"] is False
        r2 = client.patch("/api/slack/configure", json={"enabled": True})
        assert r2.json()["enabled"] is True

    def test_set_event_types(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_slack()
        client.post("/api/slack/connect", json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": "C_TEST",
        })
        r = client.patch("/api/slack/configure", json={"event_types": ["member.invited", "export.completed"]})
        assert r.status_code == 200
        assert set(r.json()["event_types"]) == {"member.invited", "export.completed"}

    def test_configure_audit_logged(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_slack()
        client.post("/api/slack/connect", json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": "C_TEST",
        })
        client.patch("/api/slack/configure", json={"enabled": False})
        events = _get_audit_events("slack.configured")
        assert len(events) > 0

    def test_settings_persist(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_slack()
        client.post("/api/slack/connect", json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": "C_PERSIST", "channel_name": "persist-ch",
            "event_types": ["member.suspended"],
        })
        r = client.get("/api/slack/status")
        d = r.json()
        assert d["channel_id"] == "C_PERSIST"
        assert d["channel_name"] == "persist-ch"
        assert "member.suspended" in d.get("event_types", [])


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

class TestSlackDelivery:
    def test_test_message(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_slack()
        _cleanup_slack_log()
        client.post("/api/slack/connect", json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": "C_TEST",
        })
        r = client.post("/api/slack/test")
        assert r.status_code == 200
        # Check delivery log
        r2 = client.get("/api/notifications/log?page_size=10")
        entries = r2.json().get("entries", [])
        slack_entries = [e for e in entries if e.get("channel") == "slack"]
        assert len(slack_entries) > 0
        assert slack_entries[0]["status"] == "sent"

    def test_event_fires_to_slack(self, client: TestClient) -> None:
        """When Slack is connected and an event fires, it appears in the delivery log."""
        from app.services.slack_service import _slack_dedup
        _slack_dedup.clear()
        _login_admin(client)
        _cleanup_slack()
        _cleanup_slack_log()
        client.post("/api/slack/connect", json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": "C_FIRE", "channel_name": "fire-ch",
        })
        from app.core.database import SessionLocal
        from app.models import NotificationPolicy
        from app.services.notification_service import _recent_sends, fire_notification
        _recent_sends.clear()
        db = SessionLocal()
        db.query(NotificationPolicy).filter(NotificationPolicy.workspace_id == 1, NotificationPolicy.event_type == "member.invited").delete()
        db.add(NotificationPolicy(workspace_id=1, event_type="member.invited", enabled=True, recipient_type="admins"))
        db.commit()
        _recent_sends.clear()
        _slack_dedup.clear()
        try:
            fire_notification(db, 1, "member.invited", detail="slack_fire@test.local invited as editor", workspace_name="Test")
            db.commit()
        finally:
            db.close()
        r2 = client.get("/api/notifications/log?page_size=20")
        entries = r2.json().get("entries", [])
        slack_invited = [e for e in entries if e.get("channel") == "slack" and e["event_type"] == "member.invited"]
        assert len(slack_invited) > 0, f"Expected Slack log entry, got {[e.get('channel') for e in entries]}"

    def test_disabled_slack_does_not_fire(self, client: TestClient) -> None:
        from app.services.slack_service import _slack_dedup
        _slack_dedup.clear()
        _login_admin(client)
        _cleanup_slack()
        _cleanup_slack_log()
        client.post("/api/slack/connect", json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": "C_DISABLED",
        })
        client.patch("/api/slack/configure", json={"enabled": False})
        # Trigger event
        from app.core.database import SessionLocal
        from app.models import NotificationPolicy
        from app.services.notification_service import _recent_sends
        _recent_sends.clear()
        db = SessionLocal()
        db.query(NotificationPolicy).filter(NotificationPolicy.workspace_id == 1, NotificationPolicy.event_type == "member.role_changed").delete()
        db.add(NotificationPolicy(workspace_id=1, event_type="member.role_changed", enabled=True, recipient_type="admins"))
        db.commit()
        db.close()
        from app.models import User, WorkspaceMember
        db2 = SessionLocal()
        u = db2.query(User).filter(User.email != "demo@trust.local").first()
        if u:
            mem = db2.query(WorkspaceMember).filter(WorkspaceMember.user_id == u.id, WorkspaceMember.workspace_id == 1).first()
            if mem:
                client.patch(f"/api/members/{mem.id}", json={"role": "editor"})
        db2.close()
        r = client.get("/api/notifications/log?page_size=20")
        entries = r.json().get("entries", [])
        slack_role = [e for e in entries if e.get("channel") == "slack" and e["event_type"] == "member.role_changed"]
        assert len(slack_role) == 0

    def test_event_type_filter_respected(self, client: TestClient) -> None:
        """When event_types are set, only matching events go to Slack."""
        from app.services.slack_service import _slack_dedup
        _slack_dedup.clear()
        _login_admin(client)
        _cleanup_slack()
        _cleanup_slack_log()
        client.post("/api/slack/connect", json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": "C_FILTER",
            "event_types": ["export.completed"],
        })
        from app.core.database import SessionLocal
        from app.models import NotificationPolicy
        from app.services.notification_service import _recent_sends
        _recent_sends.clear()
        db = SessionLocal()
        db.query(NotificationPolicy).filter(NotificationPolicy.workspace_id == 1, NotificationPolicy.event_type == "member.role_changed").delete()
        db.add(NotificationPolicy(workspace_id=1, event_type="member.role_changed", enabled=True, recipient_type="admins"))
        db.commit()
        db.close()
        from app.models import User, WorkspaceMember
        db2 = SessionLocal()
        u = db2.query(User).filter(User.email != "demo@trust.local").first()
        if u:
            mem = db2.query(WorkspaceMember).filter(WorkspaceMember.user_id == u.id, WorkspaceMember.workspace_id == 1).first()
            if mem:
                client.patch(f"/api/members/{mem.id}", json={"role": "reviewer"})
        db2.close()
        r = client.get("/api/notifications/log?page_size=20")
        entries = r.json().get("entries", [])
        slack_role = [e for e in entries if e.get("channel") == "slack" and e["event_type"] == "member.role_changed"]
        assert len(slack_role) == 0


# ---------------------------------------------------------------------------
# Permissions / Isolation
# ---------------------------------------------------------------------------

class TestSlackPermissions:
    def test_unauthenticated_cannot_access(self, client: TestClient) -> None:
        r = client.get("/api/slack/status")
        assert r.status_code == 401

    def test_unauthenticated_cannot_connect(self, client: TestClient) -> None:
        r = client.post("/api/slack/connect", json={"bot_token": "x" * 30, "channel_id": "C001"})
        assert r.status_code == 401

    def test_non_admin_cannot_connect(self, client: TestClient) -> None:
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
            r = client.post("/api/slack/connect", json={"bot_token": "x" * 30, "channel_id": "C001"})
            assert r.status_code == 403
        finally:
            db2 = SessionLocal()
            m2 = db2.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid, WorkspaceMember.workspace_id == 1).first()
            m2.role = orig
            db2.commit()
            db2.close()

    def test_cross_workspace_isolation(self, client: TestClient) -> None:
        """Slack integration in workspace 1 is not visible from workspace 2 context."""
        _login_admin(client)
        _cleanup_slack(1)
        _cleanup_slack(2)
        client.post("/api/slack/connect", json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": "C_WS1",
        })
        from app.core.database import SessionLocal
        from app.models import SlackIntegration
        db = SessionLocal()
        try:
            ws1 = db.query(SlackIntegration).filter(SlackIntegration.workspace_id == 1).first()
            assert ws1 is not None
            ws2 = db.query(SlackIntegration).filter(SlackIntegration.workspace_id == 2).first()
            assert ws2 is None
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Token safety
# ---------------------------------------------------------------------------

class TestTokenSafety:
    def test_token_not_in_status_response(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_slack()
        client.post("/api/slack/connect", json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": "C_SEC",
        })
        r = client.get("/api/slack/status")
        body = r.text
        assert "xoxb-test-token" not in body
        assert "bot_token" not in body

    def test_token_encrypted_in_db(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_slack()
        client.post("/api/slack/connect", json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": "C_ENC",
        })
        from app.core.database import SessionLocal
        from app.models import SlackIntegration
        db = SessionLocal()
        try:
            si = db.query(SlackIntegration).filter(SlackIntegration.workspace_id == 1).first()
            assert si is not None
            assert "xoxb-test-token" not in si.bot_token_encrypted
            assert len(si.bot_token_encrypted) > 50
        finally:
            db.close()


# ---------------------------------------------------------------------------
# List channels
# ---------------------------------------------------------------------------

class TestSlackChannels:
    def test_list_channels(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_slack()
        client.post("/api/slack/connect", json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": "C_TEST",
        })
        r = client.get("/api/slack/channels")
        assert r.status_code == 200
        channels = r.json().get("channels", [])
        assert len(channels) > 0
        assert "id" in channels[0]
        assert "name" in channels[0]

    def test_channels_requires_connection(self, client: TestClient) -> None:
        _login_admin(client)
        _cleanup_slack()
        r = client.get("/api/slack/channels")
        assert r.status_code == 404
