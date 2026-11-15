"""Slack channel post when every recipient has opted out.

No network and no Slack workspace. The recording provider replaces the
development stub after connect, so send_message is observable and is not a
Slack API call.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

EVENT = "member.invited"
SKIP_STATE = "skipped_all_opted_out"
SKIP_AUDIT = "notification.slack_skipped_all_opted_out"
CHANNEL_ID = "C_PREF"
CHANNEL_NAME = "prefs"


class _RecordingSlack:
    """In-process stand-in. Counts posts and does not call Slack."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def send_message(self, bot_token: str, channel_id: str, text: str, on_attempt=None) -> dict:
        del bot_token, text, on_attempt
        self.calls.append(channel_id)
        return {
            "ok": True,
            "ts": "1.0",
            "provider": "slack",
            "provider_mode": "dev-stub",
            "delivered_to_provider": False,
        }


def _login_admin(client: TestClient) -> None:
    from app.core.database import SessionLocal
    from app.models import User, WorkspaceMember

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@trust.local").one()
        mem = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == 1)
            .one()
        )
        if mem.role != "admin":
            mem.role = "admin"
            db.commit()
    finally:
        db.close()
    response = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert response.status_code == 200, response.text


def _reset_delivery() -> None:
    from app.core.database import SessionLocal
    from app.models import (
        InAppNotification,
        NotificationChannelPreference,
        NotificationDedupeClaim,
        NotificationDeliveryAttempt,
        NotificationLog,
        NotificationPolicy,
        NotificationUnsubscribe,
        SlackIntegration,
    )

    db = SessionLocal()
    try:
        db.query(NotificationDedupeClaim).delete(synchronize_session=False)
        db.query(NotificationDeliveryAttempt).filter(
            NotificationDeliveryAttempt.workspace_id == 1
        ).delete()
        db.query(NotificationLog).filter(NotificationLog.workspace_id == 1).delete()
        db.query(InAppNotification).filter(InAppNotification.workspace_id == 1).delete()
        db.query(NotificationChannelPreference).filter(
            NotificationChannelPreference.workspace_id == 1
        ).delete()
        db.query(NotificationUnsubscribe).filter(NotificationUnsubscribe.workspace_id == 1).delete()
        db.query(NotificationPolicy).filter(
            NotificationPolicy.workspace_id == 1,
            NotificationPolicy.event_type == EVENT,
        ).delete()
        db.query(SlackIntegration).filter(SlackIntegration.workspace_id == 1).delete()
        db.commit()
    finally:
        db.close()


def _add_member(role: str) -> tuple[int, str]:
    from app.core.database import SessionLocal
    from app.core.password import hash_password
    from app.models import User, WorkspaceMember

    email = f"slack-opt-{uuid4().hex}@test.local"
    db = SessionLocal()
    try:
        user = User(
            email=email,
            password_hash=hash_password("testpass123"),
            display_name="Slack opt-out",
            email_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.add(WorkspaceMember(workspace_id=1, user_id=user.id, role=role))
        db.commit()
        return int(user.id), email
    finally:
        db.close()


def _policy(role: str) -> None:
    from app.core.database import SessionLocal
    from app.models import NotificationPolicy

    db = SessionLocal()
    try:
        db.add(
            NotificationPolicy(
                workspace_id=1,
                event_type=EVENT,
                enabled=True,
                recipient_type="role",
                recipient_value=role,
            )
        )
        db.commit()
    finally:
        db.close()


def _disable_slack(user_id: int) -> None:
    from app.core.database import SessionLocal
    from app.models import NotificationChannelPreference

    db = SessionLocal()
    try:
        db.add(
            NotificationChannelPreference(
                workspace_id=1,
                user_id=user_id,
                channel="slack",
                event_type="",
                enabled=False,
            )
        )
        db.commit()
    finally:
        db.close()


def _unsubscribe(user_id: int) -> None:
    from app.core.database import SessionLocal
    from app.models import NotificationUnsubscribe

    db = SessionLocal()
    try:
        db.add(NotificationUnsubscribe(workspace_id=1, user_id=user_id, event_type=EVENT))
        db.commit()
    finally:
        db.close()


def _connect(client: TestClient) -> None:
    connected = client.post(
        "/api/slack/connect",
        json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": CHANNEL_ID,
            "channel_name": CHANNEL_NAME,
        },
    )
    assert connected.status_code == 200, connected.text


def _fire() -> int:
    from app.core.database import SessionLocal
    from app.services.notification_service import fire_notification

    db = SessionLocal()
    try:
        return fire_notification(db, 1, EVENT, "plain detail", "Workspace")
    finally:
        db.close()


def _attempts(client: TestClient) -> list[dict]:
    listed = client.get("/api/notifications/delivery-attempts?page_size=50")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["schema_version"] == 1
    return [row for row in body["attempts"] if row["event_type"] == EVENT]


def _slack_logs() -> list:
    from app.core.database import SessionLocal
    from app.models import NotificationLog

    db = SessionLocal()
    try:
        return (
            db.query(NotificationLog)
            .filter(NotificationLog.workspace_id == 1, NotificationLog.channel == "slack")
            .all()
        )
    finally:
        db.close()


def _skip_audits() -> list:
    from app.core.database import SessionLocal
    from app.models import AuditEvent

    db = SessionLocal()
    try:
        return (
            db.query(AuditEvent)
            .filter(AuditEvent.workspace_id == 1, AuditEvent.action == SKIP_AUDIT)
            .all()
        )
    finally:
        db.close()


def _cleanup(user_ids: list[int]) -> None:
    from app.core.database import SessionLocal
    from app.models import AuditEvent, User, WorkspaceMember
    from app.services.slack_service import reset_slack_provider

    reset_slack_provider()
    _reset_delivery()
    db = SessionLocal()
    try:
        db.query(AuditEvent).filter(
            AuditEvent.workspace_id == 1, AuditEvent.action == SKIP_AUDIT
        ).delete(synchronize_session=False)
        if user_ids:
            db.query(WorkspaceMember).filter(WorkspaceMember.user_id.in_(user_ids)).delete(
                synchronize_session=False
            )
            db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _install_recorder() -> _RecordingSlack:
    from app.services.slack_service import set_slack_provider

    recorder = _RecordingSlack()
    set_slack_provider(recorder)
    return recorder


def test_every_opted_out_recipient_skips_the_slack_channel_post(client: TestClient):
    """A channel disable and an unsubscribe both count as opted out.

    When every resolved recipient opted out, the workspace post is not sent.
    Each person still has a suppressed attempt. The channel attempt and the
    audit row use skipped_all_opted_out, and the attempt is on the admin
    delivery-attempts list. Slack opt-out does not suppress that person's email.
    An event unsubscribe still suppresses every channel for that person.
    """
    _login_admin(client)
    _reset_delivery()
    role = f"opt{uuid4().hex[:8]}"
    user_ids: list[int] = []
    try:
        preference_off, _preference_email = _add_member(role)
        unsubscribed, _unsubscribed_email = _add_member(role)
        user_ids.extend([preference_off, unsubscribed])
        _policy(role)
        _connect(client)
        _disable_slack(preference_off)
        _unsubscribe(unsubscribed)
        recorder = _install_recorder()

        sent = _fire()

        attempts = _attempts(client)
        slack = [row for row in attempts if row["channel"] == "slack"]
        states = [row["state"] for row in slack]
        audits = _skip_audits()
        assert recorder.calls == []
        assert _slack_logs() == []
        assert sent == 1
        suppressed = [row for row in slack if row["state"] == "suppressed-by-preference"]
        assert {row["user_id"] for row in suppressed} == {preference_off, unsubscribed}
        email_by_user = {
            row["user_id"]: row["state"]
            for row in attempts
            if row["channel"] == "email" and row["state"] in {"sent", "suppressed-by-preference"}
        }
        assert email_by_user[preference_off] == "sent"
        assert email_by_user[unsubscribed] == "suppressed-by-preference"
        skip = [row for row in slack if row["state"] == SKIP_STATE]
        assert skip and audits, {
            "slack_states": states,
            "skip_rows": len(skip),
            "audit_rows": len(audits),
            "slack_calls": recorder.calls,
        }
        assert len(skip) == 1
        row = skip[0]
        assert row["error_code"] == SKIP_STATE
        assert row["user_id"] is None
        assert row["recipient"] == f"#{CHANNEL_NAME}"
        assert row["destination"] == CHANNEL_ID
        assert row["delivered_to_provider"] is False
        assert row["template_key"] == f"{EVENT}:slack"
        assert row["error"] is None
        assert audits[0].action == SKIP_AUDIT
        assert SKIP_STATE in (audits[0].details or "")
        assert "plain detail" not in (audits[0].details or "")
    finally:
        _cleanup(user_ids)


def test_some_opted_out_recipients_still_post_to_slack(client: TestClient):
    """One opted-out recipient does not skip the workspace post.

    The opted-in recipient is unchanged: one channel post, their email is sent,
    and they have no suppressed Slack row. The opted-out recipient still gets
    email, because only Slack was disabled.
    """
    _login_admin(client)
    _reset_delivery()
    role = f"opt{uuid4().hex[:8]}"
    user_ids: list[int] = []
    try:
        opted_out, _out_email = _add_member(role)
        opted_in, _in_email = _add_member(role)
        user_ids.extend([opted_out, opted_in])
        _policy(role)
        _connect(client)
        _disable_slack(opted_out)
        recorder = _install_recorder()

        sent = _fire()

        attempts = _attempts(client)
        slack = [row for row in attempts if row["channel"] == "slack"]
        assert recorder.calls == [CHANNEL_ID]
        assert sent == 3
        assert [row.status for row in _slack_logs()] == ["sent"]
        assert _skip_audits() == []
        assert SKIP_STATE not in [row["state"] for row in slack]
        suppressed = [row for row in slack if row["state"] == "suppressed-by-preference"]
        assert [row["user_id"] for row in suppressed] == [opted_out]
        assert all(row["user_id"] != opted_in for row in suppressed)
        assert any(row["state"] == "sent" and row["user_id"] is None for row in slack)
        email_sent = {
            row["user_id"]
            for row in attempts
            if row["channel"] == "email" and row["state"] == "sent"
        }
        assert email_sent == {opted_out, opted_in}
    finally:
        _cleanup(user_ids)


def test_opted_in_recipients_still_receive_slack_and_email(client: TestClient):
    """Recipients with no opt-out still get the channel post and email."""
    _login_admin(client)
    _reset_delivery()
    role = f"opt{uuid4().hex[:8]}"
    user_ids: list[int] = []
    try:
        first, _first_email = _add_member(role)
        second, _second_email = _add_member(role)
        user_ids.extend([first, second])
        _policy(role)
        _connect(client)
        recorder = _install_recorder()

        sent = _fire()

        attempts = _attempts(client)
        slack = [row for row in attempts if row["channel"] == "slack"]
        assert recorder.calls == [CHANNEL_ID]
        assert sent == 3
        assert [row.status for row in _slack_logs()] == ["sent"]
        assert _skip_audits() == []
        assert SKIP_STATE not in [row["state"] for row in slack]
        assert "suppressed-by-preference" not in [row["state"] for row in slack]
        assert any(row["state"] == "sent" for row in slack)
        email_sent = {
            row["user_id"]
            for row in attempts
            if row["channel"] == "email" and row["state"] == "sent"
        }
        assert email_sent == {first, second}
    finally:
        _cleanup(user_ids)


def test_zero_recipients_does_not_record_a_skip(client: TestClient):
    """Zero resolved recipients is unchanged.

    fire_notification returns 0 before email, Slack, or in-app dispatch. No
    delivery attempt is written, the Slack fake is not called, and no
    skipped_all_opted_out audit row is stored. A connected Slack integration
    does not change that: there is no recipient list to opt out of, so this is
    not the all-opted-out skip.
    """
    _login_admin(client)
    _reset_delivery()
    role = f"opt{uuid4().hex[:8]}"
    try:
        _policy(role)
        _connect(client)
        recorder = _install_recorder()

        sent = _fire()

        assert sent == 0
        assert recorder.calls == []
        assert _attempts(client) == []
        assert _slack_logs() == []
        assert _skip_audits() == []
    finally:
        _cleanup([])
