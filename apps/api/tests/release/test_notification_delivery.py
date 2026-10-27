"""TC-19-008 channel preferences and delivery states.

No network, no mailbox, and no Slack workspace. Email failures are a local
provider. Slack uses the labelled development stub already selected in tests.
"""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.services.notification_redaction import redact_notification_text
from app.services.notification_templates import render_notification

EVENT = "member.invited"
INVITE_DETAIL = "invite token=xoxb-fake-1234567890abcdef evidence: source quote of the policy"


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
    email = render_notification(EVENT, "email", "Workspace", INVITE_DETAIL)
    slack = render_notification(EVENT, "slack", "Workspace", INVITE_DETAIL)
    in_app = render_notification(EVENT, "in_app", "Workspace", INVITE_DETAIL)
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
        raw_key = f"1:{EVENT}::email:demo@trust.local"
        assert log.dedupe_key == hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
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
        assert deduped.error_code == "claimed"
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


def test_claim_lease_expires_then_accept_extends_it():
    from app.core.database import SessionLocal
    from app.models import NotificationDedupeClaim
    from app.services.notification_service import (
        CLAIM_LEASE,
        CLAIM_TTL,
        claim_dedupe_key,
        extend_dedupe_claim,
    )

    key = hashlib.sha256(b"lease-probe").hexdigest()
    assert claim_dedupe_key(key) is True
    assert claim_dedupe_key(key) is False
    db = SessionLocal()
    try:
        row = db.query(NotificationDedupeClaim).filter_by(dedupe_key=key).one()
        span = row.expires_at - row.claimed_at
        assert CLAIM_LEASE - timedelta(seconds=5) <= span <= CLAIM_LEASE + timedelta(seconds=5)
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()
    assert claim_dedupe_key(key) is True
    extend_dedupe_claim(key)
    db = SessionLocal()
    try:
        row = db.query(NotificationDedupeClaim).filter_by(dedupe_key=key).one()
        remaining = row.expires_at - datetime.now(timezone.utc)
        assert remaining >= CLAIM_TTL - timedelta(minutes=1)
    finally:
        db.close()
    assert claim_dedupe_key(key) is False


def test_slack_failure_after_accept_does_not_post_again(client: TestClient):
    _login_admin(client)
    user_id = _demo_user_id()
    _reset_delivery()
    connected = client.post(
        "/api/slack/connect",
        json={
            "bot_token": "xoxb-test-token-fake-for-testing",
            "channel_id": "C_AFTER_ACCEPT",
            "channel_name": "after-accept",
        },
    )
    assert connected.status_code == 200, connected.text
    from app.core.database import SessionLocal
    from app.models import NotificationDedupeClaim
    from app.services.notification_service import (
        CLAIM_TTL,
        _fire_slack_notification,
        stable_dedupe_key,
    )
    from app.services.notification_templates import render_notification
    from app.services.slack_service import reset_slack_provider, set_slack_provider

    posts: list[str] = []
    accepted = {"ok": False}

    class AcceptingProvider:
        def send_message(self, bot_token, channel_id, text, on_attempt=None):
            posts.append(text)
            accepted["ok"] = True
            return {"ok": True, "attempts": 1, "delivered_to_provider": False}

        def list_channels(self, bot_token):
            return []

        def test_auth(self, bot_token):
            return {"ok": True}

    set_slack_provider(AcceptingProvider())
    rendered = render_notification(EVENT, "slack", "Workspace", "plain detail")
    db = SessionLocal()
    try:
        real_flush = db.flush

        def fail_after_accept(*args, **kwargs):
            if accepted["ok"]:
                accepted["ok"] = False
                raise RuntimeError("sent-row write failed")
            return real_flush(*args, **kwargs)

        db.flush = fail_after_accept
        try:
            _fire_slack_notification(
                db, 1, EVENT, [(user_id, "demo@trust.local")], rendered, "slack-occ-1"
            )
        finally:
            db.flush = real_flush
        db.rollback()
    finally:
        db.close()
        reset_slack_provider()

    key = stable_dedupe_key(1, EVENT, "slack", "C_AFTER_ACCEPT", "slack-occ-1")
    db = SessionLocal()
    try:
        claim = db.query(NotificationDedupeClaim).filter_by(dedupe_key=key).one()
        remaining = claim.expires_at - datetime.now(timezone.utc)
        assert remaining >= CLAIM_TTL - timedelta(minutes=1)
        assert claim.released_at is None
    finally:
        db.close()

    set_slack_provider(AcceptingProvider())
    db = SessionLocal()
    try:
        _fire_slack_notification(
            db, 1, EVENT, [(user_id, "demo@trust.local")], rendered, "slack-occ-1"
        )
        db.commit()
    finally:
        db.close()
        reset_slack_provider()
    assert posts == [rendered.slack_text]


def test_in_app_claim_rolls_back_with_the_callers_commit(client: TestClient):
    _login_admin(client)
    user_id = _demo_user_id()
    _reset_delivery()
    from app.core.database import SessionLocal
    from app.models import InAppNotification, NotificationChannelPreference, NotificationDedupeClaim
    from app.services.notification_service import _deliver_in_app, stable_dedupe_key
    from app.services.notification_templates import render_notification

    db = SessionLocal()
    try:
        db.add(
            NotificationChannelPreference(
                workspace_id=1,
                user_id=user_id,
                channel="in_app",
                event_type="",
                enabled=True,
            )
        )
        db.commit()
        rendered = render_notification(EVENT, "in_app", "Workspace", "plain detail")
        assert (
            _deliver_in_app(
                db,
                workspace_id=1,
                event_type=EVENT,
                user_id=user_id,
                email="demo@trust.local",
                rendered=rendered,
                event_id="inapp-occ-1",
            )
            is True
        )
        db.rollback()
        assert (
            db.query(InAppNotification)
            .filter(InAppNotification.user_id == user_id, InAppNotification.workspace_id == 1)
            .count()
            == 0
        )
        key = stable_dedupe_key(1, EVENT, "in_app", f"user:{user_id}", "inapp-occ-1")
        assert db.query(NotificationDedupeClaim).filter_by(dedupe_key=key).count() == 0
        assert (
            _deliver_in_app(
                db,
                workspace_id=1,
                event_type=EVENT,
                user_id=user_id,
                email="demo@trust.local",
                rendered=rendered,
                event_id="inapp-occ-1",
            )
            is True
        )
        db.commit()
        assert (
            db.query(InAppNotification)
            .filter(
                InAppNotification.user_id == user_id,
                InAppNotification.title == "New member invited",
            )
            .count()
            == 1
        )
    finally:
        db.close()


def test_repeated_role_change_sends_twice(client: TestClient):
    _login_admin(client)
    user_id = _demo_user_id()
    _reset_delivery()
    from app.core.database import SessionLocal
    from app.core.password import hash_password
    from app.models import NotificationLog, NotificationPolicy, User, WorkspaceMember

    db = SessionLocal()
    try:
        db.query(NotificationPolicy).filter(
            NotificationPolicy.workspace_id == 1,
            NotificationPolicy.event_type == "member.role_changed",
        ).delete()
        other = db.query(User).filter(User.email == "repeat-role@test.local").first()
        if other is None:
            other = User(
                email="repeat-role@test.local",
                password_hash=hash_password("testpass123"),
                display_name="repeat",
            )
            db.add(other)
            db.commit()
            db.refresh(other)
        mem = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.user_id == other.id, WorkspaceMember.workspace_id == 1)
            .first()
        )
        if mem is None:
            mem = WorkspaceMember(workspace_id=1, user_id=other.id, role="viewer")
            db.add(mem)
        else:
            mem.role = "viewer"
            mem.suspended = False
        db.add(
            NotificationPolicy(
                workspace_id=1,
                event_type="member.role_changed",
                enabled=True,
                recipient_type="user",
                recipient_value=str(user_id),
            )
        )
        db.commit()
        member_id = mem.id
    finally:
        db.close()

    first = client.patch(f"/api/members/{member_id}", json={"role": "editor"})
    second = client.patch(f"/api/members/{member_id}", json={"role": "editor"})
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    db = SessionLocal()
    try:
        sent = (
            db.query(NotificationLog)
            .filter(
                NotificationLog.workspace_id == 1,
                NotificationLog.event_type == "member.role_changed",
                NotificationLog.channel == "email",
                NotificationLog.delivery_state == "sent",
            )
            .count()
        )
    finally:
        db.close()
    assert sent == 2


def test_same_coverage_numbers_fire_twice(client: TestClient):
    """Same job retries once, a new job inside the cooldown is quiet, and a later job fires."""
    _login_admin(client)
    user_id = _demo_user_id()
    _reset_delivery()
    from datetime import datetime, timedelta, timezone
    from unittest.mock import patch

    from app.core.database import SessionLocal
    from app.models import AuditEvent, NotificationLog, NotificationPolicy
    from app.services.compliance_event_service import (
        COOLDOWN_MINUTES,
        evaluate_and_fire_compliance_events,
    )
    from app.services.notification_service import stable_dedupe_key

    coverage = {
        "kpi": {
            "total_questions": 10,
            "coverage_pct": 10,
            "insufficient_pct": 0,
            "blind_spot_count": 0,
        },
        "blind_spots": [],
        "weak_areas": [],
    }
    event_type = "compliance.coverage_drop"
    db = SessionLocal()
    try:
        audits_before = db.query(AuditEvent).filter(AuditEvent.action == event_type).count()
        db.query(NotificationPolicy).filter(
            NotificationPolicy.workspace_id == 1,
            NotificationPolicy.event_type == event_type,
        ).delete()
        db.add(
            NotificationPolicy(
                workspace_id=1,
                event_type=event_type,
                enabled=True,
                recipient_type="user",
                recipient_value=str(user_id),
            )
        )
        db.commit()

        def sent_count() -> int:
            return (
                db.query(NotificationLog)
                .filter(
                    NotificationLog.workspace_id == 1,
                    NotificationLog.event_type == event_type,
                    NotificationLog.channel == "email",
                    NotificationLog.delivery_state == "sent",
                )
                .count()
            )

        with patch(
            "app.services.compliance_event_service.get_compliance_coverage",
            return_value=coverage,
        ):
            assert evaluate_and_fire_compliance_events(db, 1, "Workspace", job_id=101) == 1
            assert evaluate_and_fire_compliance_events(db, 1, "Workspace", job_id=101) == 0
            assert sent_count() == 1
            assert evaluate_and_fire_compliance_events(db, 1, "Workspace", job_id=202) == 0
            assert sent_count() == 1
            aged = datetime.now(timezone.utc) - timedelta(minutes=COOLDOWN_MINUTES + 1)
            db.query(NotificationLog).filter(
                NotificationLog.workspace_id == 1,
                NotificationLog.event_type == event_type,
            ).update({NotificationLog.created_at: aged}, synchronize_session=False)
            db.commit()
            assert evaluate_and_fire_compliance_events(db, 1, "Workspace", job_id=303) == 1
        assert sent_count() == 2
        email = (
            db.query(NotificationLog)
            .filter(
                NotificationLog.workspace_id == 1,
                NotificationLog.event_type == event_type,
                NotificationLog.channel == "email",
            )
            .order_by(NotificationLog.id.asc())
            .first()
        )
        assert email is not None
        assert email.dedupe_key == stable_dedupe_key(
            1, event_type, "email", email.recipient_email, "job:101:compliance.coverage_drop"
        )
        assert db.query(AuditEvent).filter(AuditEvent.action == event_type).count() == audits_before
    finally:
        db.close()


def test_two_generation_jobs_with_the_same_gap_both_send(client: TestClient):
    _login_admin(client)
    user_id = _demo_user_id()
    _reset_delivery()
    from app.core.database import SessionLocal
    from app.models import (
        Answer,
        Job,
        NotificationLog,
        NotificationPolicy,
        Question,
        Questionnaire,
        Workspace,
    )
    from app.services.automation_service import evaluate_generation_result

    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == 1).one()
        previous_flag = bool(ws.ai_automate_everything)
        ws.ai_automate_everything = True
        db.query(NotificationPolicy).filter(
            NotificationPolicy.workspace_id == 1,
            NotificationPolicy.event_type == "questionnaire.generated",
        ).delete()
        db.add(
            NotificationPolicy(
                workspace_id=1,
                event_type="questionnaire.generated",
                enabled=True,
                recipient_type="user",
                recipient_value=str(user_id),
            )
        )
        qnr = Questionnaire(workspace_id=1, filename="repeat.csv", status="parsed")
        db.add(qnr)
        db.flush()
        question = Question(questionnaire_id=qnr.id, text="Do you encrypt data at rest?")
        db.add(question)
        db.flush()
        db.add(
            Answer(
                question_id=question.id,
                text="",
                status="insufficient_evidence",
                confidence=0,
            )
        )
        jobs = []
        for _n in range(2):
            job = Job(
                workspace_id=1,
                kind="generate_answers",
                status="completed",
                payload=f'{{"questionnaire_id": {qnr.id}}}',
            )
            db.add(job)
            jobs.append(job)
        db.commit()
        for job in jobs:
            db.refresh(job)
            evaluate_generation_result(db, job, {"questionnaire_id": qnr.id})
        sent = (
            db.query(NotificationLog)
            .filter(
                NotificationLog.workspace_id == 1,
                NotificationLog.event_type == "questionnaire.generated",
                NotificationLog.channel == "email",
                NotificationLog.delivery_state == "sent",
            )
            .count()
        )
    finally:
        ws = db.query(Workspace).filter(Workspace.id == 1).one()
        ws.ai_automate_everything = previous_flag
        db.commit()
        db.close()
    assert sent == 2


def test_missing_event_id_skips_dedupe(client: TestClient):
    _login_admin(client)
    user_id = _demo_user_id()
    _reset_delivery()
    _policy_for_user(user_id)
    from app.core.database import SessionLocal
    from app.models import NotificationDedupeClaim
    from app.services.notification_service import fire_notification

    db = SessionLocal()
    try:
        assert fire_notification(db, 1, EVENT, "plain detail", "Workspace") == 1
        assert fire_notification(db, 1, EVENT, "plain detail", "Workspace") == 1
        claims = db.query(NotificationDedupeClaim).count()
    finally:
        db.close()
    assert claims == 0
    assert _states("email").count("sent") == 2
    assert "deduped" not in _states("email")


def test_two_sessions_racing_one_key_only_one_wins():
    from app.core.database import SessionLocal
    from app.models import NotificationDedupeClaim
    from app.services.notification_service import claim_dedupe_key

    key = "1:member.invited:evt-race:email:race@example.com"
    db = SessionLocal()
    try:
        db.query(NotificationDedupeClaim).filter(NotificationDedupeClaim.dedupe_key == key).delete()
        db.commit()
    finally:
        db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        won = list(pool.map(lambda _n: claim_dedupe_key(key), (1, 2)))
    assert won.count(True) == 1
    assert won.count(False) == 1


def test_worker_prunes_expired_and_released_claims(client: TestClient):
    import time

    import app.worker as worker
    from app.core.database import SessionLocal
    from app.models import NotificationDedupeClaim

    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        db.add(
            NotificationDedupeClaim(
                dedupe_key="1:prune:expired:email:a@example.com",
                claimed_at=now - timedelta(hours=25),
                expires_at=now - timedelta(hours=1),
            )
        )
        db.add(
            NotificationDedupeClaim(
                dedupe_key="1:prune:released:email:b@example.com",
                claimed_at=now,
                expires_at=now + timedelta(hours=24),
                released_at=now,
            )
        )
        db.add(
            NotificationDedupeClaim(
                dedupe_key="1:prune:live:email:c@example.com",
                claimed_at=now,
                expires_at=now + timedelta(hours=24),
            )
        )
        db.commit()
    finally:
        db.close()

    previous = (
        worker.last_dedupe_prune_run,
        worker.last_usage_cleanup_run,
        worker.last_compliance_webhook_run,
    )
    worker.last_dedupe_prune_run = 0.0
    worker.last_usage_cleanup_run = time.time()
    worker.last_compliance_webhook_run = time.time()
    original_claim = worker.claim_job
    worker.claim_job = lambda _session: None
    try:
        assert worker._process_one_job() is False
    finally:
        worker.claim_job = original_claim
        (
            worker.last_dedupe_prune_run,
            worker.last_usage_cleanup_run,
            worker.last_compliance_webhook_run,
        ) = previous

    db = SessionLocal()
    try:
        keys = {
            row.dedupe_key
            for row in db.query(NotificationDedupeClaim)
            .filter(NotificationDedupeClaim.dedupe_key.like("1:prune:%"))
            .all()
        }
    finally:
        db.close()
    assert keys == {"1:prune:live:email:c@example.com"}


def test_email_send_raise_releases_the_claim(client: TestClient):
    _login_admin(client)
    user_id = _demo_user_id()
    _reset_delivery()
    _policy_for_user(user_id)
    from app.core.database import SessionLocal
    from app.services import notification_service

    def _boom(_provider, _message, _on_attempt):
        raise RuntimeError("transport down")

    db = SessionLocal()
    original = notification_service._send_email_bounded
    notification_service._send_email_bounded = _boom
    try:
        with pytest.raises(RuntimeError, match="transport down"):
            notification_service.fire_notification(
                db, 1, EVENT, "plain detail", "Workspace", event_id="evt-raise"
            )
        db.rollback()
    finally:
        notification_service._send_email_bounded = original
        db.close()

    db = SessionLocal()
    try:
        assert (
            notification_service.fire_notification(
                db, 1, EVENT, "plain detail", "Workspace", event_id="evt-raise"
            )
            == 1
        )
    finally:
        db.close()
    assert _states("email").count("sent") == 1
    assert "deduped" not in _states("email")


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
            sent = notification_service.fire_notification(db, 1, EVENT, INVITE_DETAIL, "Workspace")
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


def _revision_token(output: str) -> str:
    for line in output.splitlines():
        token = line.strip().split()[0] if line.strip() else ""
        if token and not token.startswith("INFO"):
            return token
    raise AssertionError(f"no revision in alembic output: {output!r}")


def _alembic_script():
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    api_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(api_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_dir / "alembic"))
    return ScriptDirectory.from_config(cfg)


def _revision_is_applied(head: str, revision: str) -> bool:
    """True when ``head`` is ``revision`` or a later revision on its chain."""
    script = _alembic_script()
    current: str | None = head
    seen: set[str] = set()
    while current and current not in seen:
        if current == revision:
            return True
        seen.add(current)
        rev = script.get_revision(current)
        parent = rev.down_revision if rev is not None else None
        if isinstance(parent, tuple):
            return any(_revision_is_applied(item, revision) for item in parent if item)
        current = parent
    return False


def _down_revision(revision: str) -> str:
    parent = _alembic_script().get_revision(revision).down_revision
    assert isinstance(parent, str) and parent
    return parent


def test_migration_upgrades_and_downgrades_on_a_fresh_database():
    import os
    import subprocess
    import sys

    from sqlalchemy import create_engine, text

    name = "trustcopilot_tc19008_migration_test"
    revision = "tc19008_notification_delivery"
    parent = _down_revision(revision)
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
        assert heads.stdout.count("(head)") == 1
        assert _revision_is_applied(_revision_token(heads.stdout), revision)

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
            assert conn.execute(
                text("SELECT to_regclass('public.notification_dedupe_claims')")
            ).scalar()
            claim_pk = conn.execute(
                text(
                    "SELECT a.attname FROM pg_index i "
                    "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                    "WHERE i.indrelid = 'public.notification_dedupe_claims'::regclass "
                    "AND i.indisprimary"
                )
            ).scalar()
            assert claim_pk == "dedupe_key"
            claim_indexes = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE tablename = 'notification_dedupe_claims'"
                    )
                )
            }
            assert "ix_notification_dedupe_claims_expires_at" in claim_indexes
            assert "ix_notification_dedupe_claims_released_at" in claim_indexes
            version_width = conn.execute(
                text(
                    "SELECT character_maximum_length FROM information_schema.columns "
                    "WHERE table_name = 'alembic_version' AND column_name = 'version_num'"
                )
            ).scalar()
            assert version_width == 32
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
            assert (
                conn.execute(
                    text("SELECT to_regclass('public.notification_dedupe_claims')")
                ).scalar()
                is None
            )
        engine.dispose()

        again = run("upgrade", "head")
        assert again.returncode == 0, again.stderr
        current = run("current")
        assert current.returncode == 0, current.stderr
        assert _revision_is_applied(_revision_token(current.stdout), revision)
    finally:
        _drop_side_database(name)


@pytest.fixture(autouse=True)
def _clean_notification_delivery(_ensure_test_data):
    if not _ensure_test_data:
        pytest.fail("Postgres is required for TC-19-008; not skipping")
    _reset_delivery()
    yield
    _reset_delivery()
