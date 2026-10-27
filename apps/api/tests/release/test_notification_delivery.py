"""TC-19-008 channel preferences and delivery states.

No network, no mailbox, and no Slack workspace. Email failures are a local
provider. Slack uses the labelled development stub already selected in tests.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.notification_redaction import redact_notification_text
from app.services.notification_templates import render_notification

EVENT = "member.invited"
SECRET_DETAIL = "invite token=xoxb-fake-1234567890abcdef evidence: source quote of the policy"


def _login_admin(client: TestClient) -> dict:
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
    r = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert r.status_code == 200, r.text
    return r.json()


def _demo_user_id() -> int:
    from app.core.database import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@trust.local").one()
        return int(user.id)
    finally:
        db.close()


def _reset_delivery(workspace_id: int = 1) -> None:
    from app.core.database import SessionLocal
    from app.models import (
        InAppNotification,
        NotificationChannelPreference,
        NotificationDeliveryAttempt,
        NotificationLog,
        NotificationPolicy,
        NotificationUnsubscribe,
        SlackIntegration,
    )
    from app.services.notification_service import _recent_sends
    from app.services.slack_service import _slack_dedup

    _recent_sends.clear()
    _slack_dedup.clear()
    db = SessionLocal()
    try:
        db.query(NotificationDeliveryAttempt).filter(
            NotificationDeliveryAttempt.workspace_id == workspace_id
        ).delete()
        db.query(NotificationLog).filter(NotificationLog.workspace_id == workspace_id).delete()
        db.query(InAppNotification).filter(InAppNotification.workspace_id == workspace_id).delete()
        db.query(NotificationChannelPreference).filter(
            NotificationChannelPreference.workspace_id == workspace_id
        ).delete()
        db.query(NotificationUnsubscribe).filter(
            NotificationUnsubscribe.workspace_id == workspace_id
        ).delete()
        db.query(NotificationPolicy).filter(
            NotificationPolicy.workspace_id == workspace_id,
            NotificationPolicy.event_type == EVENT,
        ).delete()
        db.query(SlackIntegration).filter(SlackIntegration.workspace_id == workspace_id).delete()
        db.commit()
    finally:
        db.close()


def _policy_for_user(user_id: int) -> None:
    from app.core.database import SessionLocal
    from app.models import NotificationPolicy

    db = SessionLocal()
    try:
        db.add(
            NotificationPolicy(
                workspace_id=1,
                event_type=EVENT,
                enabled=True,
                recipient_type="user",
                recipient_value=str(user_id),
            )
        )
        db.commit()
    finally:
        db.close()


def _states(channel: str | None = None) -> list[str]:
    from app.core.database import SessionLocal
    from app.models import NotificationDeliveryAttempt

    db = SessionLocal()
    try:
        q = db.query(NotificationDeliveryAttempt).filter(
            NotificationDeliveryAttempt.workspace_id == 1,
            NotificationDeliveryAttempt.event_type == EVENT,
        )
        if channel:
            q = q.filter(NotificationDeliveryAttempt.channel == channel)
        return [row.state for row in q.order_by(NotificationDeliveryAttempt.id).all()]
    finally:
        db.close()


def _stored_text() -> str:
    from app.core.database import SessionLocal
    from app.models import NotificationDeliveryAttempt, NotificationLog

    db = SessionLocal()
    try:
        parts: list[str] = []
        for row in db.query(NotificationDeliveryAttempt).all():
            parts.extend(
                [
                    row.recipient or "",
                    row.error_message or "",
                    row.rendered_subject or "",
                    row.rendered_body or "",
                    row.destination or "",
                    row.state or "",
                ]
            )
        for row in db.query(NotificationLog).all():
            parts.extend([row.subject or "", row.error or "", row.recipient_email or ""])
        return "\n".join(parts)
    finally:
        db.close()


def test_redaction_strips_secrets_and_evidence_and_keeps_the_recipient():
    text = redact_notification_text(
        "to demo@trust.local token=xoxb-fake-1234567890abcdef Bearer ya29.fake-secret "
        "sk_live_fakenotarealkey password=hunter2 evidence: the control quote"
    )
    assert "demo@trust.local" in text
    assert "xoxb-" not in text
    assert "ya29." not in text
    assert "sk_live_" not in text
    assert "hunter2" not in text
    assert "control quote" not in text
    assert "[redacted]" in text


def test_one_template_source_shares_the_label_and_redacts_detail():
    email = render_notification(EVENT, "email", "Workspace", SECRET_DETAIL)
    slack = render_notification(EVENT, "slack", "Workspace", SECRET_DETAIL)
    in_app = render_notification(EVENT, "in_app", "Workspace", SECRET_DETAIL)
    assert email.template_key == f"{EVENT}:email"
    assert slack.template_key == f"{EVENT}:slack"
    assert in_app.template_key == f"{EVENT}:in_app"
    assert email.label == slack.label == in_app.label == in_app.title == "New member invited"
    assert "xoxb-" not in email.subject
    assert "xoxb-" not in slack.slack_text
    assert "source quote" not in in_app.body_text
    assert email.label in email.subject
    assert email.label in slack.slack_text


def test_email_opt_out_is_suppressed_and_not_logged_as_sent(client: TestClient):
    _login_admin(client)
    user_id = _demo_user_id()
    _reset_delivery()
    _policy_for_user(user_id)
    saved = client.put(
        "/api/notifications/channel-preferences",
        json={"channel": "email", "enabled": False},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["schema_version"] == 1
    assert saved.json()["enabled"] is False

    from app.core.database import SessionLocal
    from app.services.notification_service import fire_notification

    db = SessionLocal()
    try:
        sent = fire_notification(db, 1, EVENT, "plain detail", "Workspace")
    finally:
        db.close()
    assert sent == 0
    assert "suppressed-by-preference" in _states("email")
    assert "sent" not in _states("email")
    from app.core.database import SessionLocal as SL
    from app.models import NotificationLog

    db = SL()
    try:
        logs = (
            db.query(NotificationLog)
            .filter(NotificationLog.event_type == EVENT, NotificationLog.channel == "email")
            .all()
        )
    finally:
        db.close()
    assert logs == []


def test_console_email_stub_is_not_recorded_as_provider_delivery(client: TestClient):
    _login_admin(client)
    user_id = _demo_user_id()
    _reset_delivery()
    _policy_for_user(user_id)

    from app.core.database import SessionLocal
    from app.models import NotificationLog
    from app.services.notification_service import fire_notification

    db = SessionLocal()
    try:
        sent = fire_notification(db, 1, EVENT, "plain detail", "Workspace")
        log = (
            db.query(NotificationLog)
            .filter(NotificationLog.channel == "email", NotificationLog.event_type == EVENT)
            .one()
        )
        assert sent == 1
        assert log.status == "sent"
        assert log.delivery_state == "sent"
        assert log.provider_mode == "dev-stub"
        assert log.delivered_to_provider is False
        assert log.dedupe_key == f"1:{EVENT}::email:demo@trust.local"
    finally:
        db.close()

    listed = client.get("/api/notifications/log?page_size=20")
    assert listed.status_code == 200
    entry = next(e for e in listed.json()["entries"] if e["channel"] == "email")
    assert entry["delivery_state"] == "sent"
    assert entry["delivered_to_provider"] is False
    assert entry["provider_mode"] == "dev-stub"


def test_second_fire_is_deduped_on_the_same_key(client: TestClient):
    _login_admin(client)
    user_id = _demo_user_id()
    _reset_delivery()
    _policy_for_user(user_id)
    from app.core.database import SessionLocal
    from app.services.notification_service import fire_notification

    db = SessionLocal()
    try:
        assert (
            fire_notification(db, 1, EVENT, "plain detail", "Workspace", event_id="evt-same") == 1
        )
        assert (
            fire_notification(db, 1, EVENT, "plain detail", "Workspace", event_id="evt-same") == 0
        )
    finally:
        db.close()
    email_states = _states("email")
    assert email_states.count("sent") == 1
    assert "deduped" in email_states
    assert email_states.count("queued") == 1
    from app.core.database import SessionLocal
    from app.models import NotificationDeliveryAttempt

    db = SessionLocal()
    try:
        deduped = (
            db.query(NotificationDeliveryAttempt)
            .filter(
                NotificationDeliveryAttempt.channel == "email",
                NotificationDeliveryAttempt.state == "deduped",
            )
            .one()
        )
        assert deduped.error_code == "per-process"
    finally:
        db.close()


def test_different_event_ids_are_not_deduped(client: TestClient):
    _login_admin(client)
    user_id = _demo_user_id()
    _reset_delivery()
    _policy_for_user(user_id)
    from app.core.database import SessionLocal
    from app.services.notification_service import fire_notification

    db = SessionLocal()
    try:
        assert fire_notification(db, 1, EVENT, "plain detail", "Workspace", event_id="evt-a") == 1
        assert fire_notification(db, 1, EVENT, "plain detail", "Workspace", event_id="evt-b") == 1
    finally:
        db.close()
    email_states = _states("email")
    assert email_states.count("sent") == 2
    assert "deduped" not in email_states


def test_dead_letter_releases_the_dedupe_key(client: TestClient):
    _login_admin(client)
    user_id = _demo_user_id()
    _reset_delivery()
    _policy_for_user(user_id)

    class AlwaysFail:
        def send(self, message) -> bool:
            raise RuntimeError("mailbox down")

    from app.core.database import SessionLocal
    from app.services import notification_service

    db = SessionLocal()
    try:
        original = notification_service.get_email_provider
        notification_service.get_email_provider = lambda: AlwaysFail()
        try:
            assert (
                notification_service.fire_notification(
                    db, 1, EVENT, "plain detail", "Workspace", event_id="evt-dead"
                )
                == 0
            )
        finally:
            notification_service.get_email_provider = original
        assert (
            notification_service.fire_notification(
                db, 1, EVENT, "plain detail", "Workspace", event_id="evt-dead"
            )
            == 1
        )
    finally:
        db.close()
    email_states = _states("email")
    assert "dead-lettered" in email_states
    assert email_states.count("sent") == 1
    assert "deduped" not in email_states


def test_email_retries_then_dead_letters_without_storing_the_secret(client: TestClient):
    _login_admin(client)
    user_id = _demo_user_id()
    _reset_delivery()
    _policy_for_user(user_id)

    class AlwaysFail:
        def __init__(self) -> None:
            self.calls = 0

        def send(self, message) -> bool:
            self.calls += 1
            raise RuntimeError("password=hunter2 sk_live_fakenotarealkey")

    from app.core.database import SessionLocal
    from app.services import notification_service

    provider = AlwaysFail()
    db = SessionLocal()
    try:
        original = notification_service.get_email_provider
        notification_service.get_email_provider = lambda: provider
        try:
            sent = notification_service.fire_notification(db, 1, EVENT, SECRET_DETAIL, "Workspace")
        finally:
            notification_service.get_email_provider = original
    finally:
        db.close()

    assert sent == 0
    assert provider.calls == 3
    email_states = _states("email")
    assert email_states[0] == "queued"
    assert email_states.count("retrying") == 2
    assert email_states[-1] == "dead-lettered"
    blob = _stored_text()
    assert "hunter2" not in blob
    assert "sk_live_" not in blob
    assert "xoxb-" not in blob
    assert "source quote" not in blob


def test_in_app_follows_the_preference_and_the_read_state(client: TestClient):
    _login_admin(client)
    user_id = _demo_user_id()
    _reset_delivery()
    _policy_for_user(user_id)

    from app.core.database import SessionLocal
    from app.models import InAppNotification
    from app.services.notification_service import fire_notification

    db = SessionLocal()
    try:
        fire_notification(db, 1, EVENT, "plain detail", "Workspace")
        skipped = (
            db.query(InAppNotification)
            .filter(
                InAppNotification.user_id == user_id,
                InAppNotification.title == "New member invited",
            )
            .count()
        )
    finally:
        db.close()
    # Missing in-app preference is a silent skip, not a suppressed row.
    assert skipped == 0
    assert _states("in_app") == []

    enabled = client.put(
        "/api/notifications/channel-preferences",
        json={"channel": "in_app", "enabled": True},
    )
    assert enabled.status_code == 200
    from app.services.notification_service import _recent_sends
    from app.services.slack_service import _slack_dedup

    _recent_sends.clear()
    _slack_dedup.clear()
    db = SessionLocal()
    try:
        fire_notification(db, 1, EVENT, "plain detail", "Workspace")
        note = (
            db.query(InAppNotification)
            .filter(
                InAppNotification.user_id == user_id,
                InAppNotification.title == "New member invited",
            )
            .one()
        )
        assert note.is_read is False
        assert note.link == "/dashboard/notifications"
        note_id = note.id
    finally:
        db.close()
    assert "sent" in _states("in_app")

    marked = client.post(f"/api/in-app-notifications/{note_id}/read")
    assert marked.status_code == 200, marked.text
    listed = client.get("/api/notifications/delivery-attempts?page_size=50")
    assert listed.status_code == 200
    body = listed.json()
    assert body["schema_version"] == 1
    match = [
        row
        for row in body["attempts"]
        if row["channel"] == "in_app"
        and row["state"] == "sent"
        and row["in_app_notification_id"] == note_id
    ]
    assert match, body["attempts"]
    assert match[0]["is_read"] is True
    assert match[0]["template_key"] == f"{EVENT}:in_app"
    assert match[0]["destination"] == f"user:{user_id}"
    assert "xoxb-" not in (match[0]["rendered_body"] or "")


def test_slack_opt_out_records_suppression_and_does_not_post(client: TestClient):
    _login_admin(client)
    user_id = _demo_user_id()
    _reset_delivery()
    _policy_for_user(user_id)
    connected = client.post(
        "/api/slack/connect",
        json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": "C_PREF",
            "channel_name": "prefs",
        },
    )
    assert connected.status_code == 200, connected.text
    saved = client.put(
        "/api/notifications/channel-preferences",
        json={"channel": "slack", "enabled": False},
    )
    assert saved.status_code == 200

    from app.core.database import SessionLocal
    from app.models import NotificationLog
    from app.services.notification_service import fire_notification

    db = SessionLocal()
    try:
        sent = fire_notification(db, 1, EVENT, "plain detail", "Workspace")
        slack_logs = (
            db.query(NotificationLog)
            .filter(NotificationLog.event_type == EVENT, NotificationLog.channel == "slack")
            .all()
        )
    finally:
        db.close()
    assert sent == 1  # console email still accepted
    assert slack_logs == []
    assert _states("slack") == ["suppressed-by-preference"]


def test_effective_preferences_default_email_and_slack_on(client: TestClient):
    _login_admin(client)
    _reset_delivery()
    got = client.get("/api/notifications/channel-preferences")
    assert got.status_code == 200
    body = got.json()
    assert body["schema_version"] == 1
    assert body["effective"]["email"] is True
    assert body["effective"]["slack"] is True
    assert body["effective"]["in_app"] is False


def _side_database_url(name: str) -> str:
    """Use this run's database role. CI does not accept postgres/postgres."""
    import os

    from sqlalchemy.engine import make_url

    raw = os.environ.get("TC_TEST_DATABASE_URL") or os.environ["DATABASE_URL"]
    return make_url(raw).set(database=name).render_as_string(hide_password=False)


def _recreate_side_database(name: str) -> None:
    from sqlalchemy import create_engine, text

    admin = create_engine(_side_database_url("postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": name},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()


def _drop_side_database(name: str) -> None:
    from sqlalchemy import create_engine, text

    admin = create_engine(_side_database_url("postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": name},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    admin.dispose()


def test_migration_upgrades_and_downgrades_on_a_fresh_database():
    import os
    import subprocess
    import sys

    from sqlalchemy import create_engine, text

    name = "trustcopilot_tc19008_migration_test"
    revision = "tc19008_notification_channel_delivery"
    parent = "tc11001_model_outcome_codes"
    url = _side_database_url(name)
    api_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    _recreate_side_database(name)
    try:

        def run(*args: str) -> subprocess.CompletedProcess:
            env = {**os.environ, "DATABASE_URL": url, "TRUST_COPILOT_TESTING": "1"}
            return subprocess.run(
                [sys.executable, "-m", "alembic", *args],
                cwd=api_root,
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )

        fresh = run("upgrade", "head")
        assert fresh.returncode == 0, fresh.stderr
        heads = run("heads")
        assert heads.returncode == 0, heads.stderr
        assert revision in heads.stdout
        assert heads.stdout.count("(head)") == 1

        engine = create_engine(url)
        with engine.connect() as conn:
            assert conn.execute(
                text("SELECT to_regclass('public.notification_delivery_attempts')")
            ).scalar()
            assert conn.execute(
                text("SELECT to_regclass('public.notification_channel_preferences')")
            ).scalar()
            indexes = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE tablename = 'notification_delivery_attempts'"
                    )
                )
            }
            assert "ix_notification_delivery_attempts_id" not in indexes
            assert "ix_notification_delivery_attempts_dedupe_key" in indexes
            unique_on_dedupe = conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'notification_delivery_attempts' "
                    "AND indexdef ILIKE '%UNIQUE%' "
                    "AND indexdef ILIKE '%dedupe_key%'"
                )
            ).scalar()
            assert unique_on_dedupe is None
        engine.dispose()

        down = run("downgrade", parent)
        assert down.returncode == 0, down.stderr
        engine = create_engine(url)
        with engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT to_regclass('public.notification_delivery_attempts')")
                ).scalar()
                is None
            )
            column = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'notification_log' AND column_name = 'delivery_state'"
                )
            ).scalar()
            assert column is None
        engine.dispose()

        again = run("upgrade", "head")
        assert again.returncode == 0, again.stderr
        current = run("current")
        assert revision in current.stdout
    finally:
        _drop_side_database(name)


@pytest.fixture(autouse=True)
def _clean_notification_delivery(_ensure_test_data):
    if not _ensure_test_data:
        pytest.fail("Postgres is required for TC-19-008; not skipping")
    _reset_delivery()
    yield
    _reset_delivery()
