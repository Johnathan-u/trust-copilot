"""Notification rule, preference and delivery-log boundaries on PostgreSQL."""

import uuid
from contextlib import contextmanager
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import bindparam, text

from app.core.database import SessionLocal, engine
from app.core.password import hash_password
from app.main import app
from app.models import (
    CustomRole,
    NotificationDeliveryAttempt,
    NotificationLog,
    NotificationPolicy,
    User,
    Workspace,
    WorkspaceMember,
)
from tests.conftest import TEST_HEADERS

pytestmark = pytest.mark.integration
TABLE_KEYS = (
    ("notification_delivery_attempts", "id"),
    ("notification_log", "id"),
    ("notification_dedupe_claims", "dedupe_key"),
    ("notification_channel_preferences", "id"),
    ("notification_unsubscribes", "id"),
    ("notification_policies", "id"),
    ("in_app_notifications", "id"),
    ("audit_events", "id"),
    ("idempotency_keys", "id"),
    ("user_sessions", "id"),
    ("custom_roles", "id"),
    ("workspace_members", "id"),
    ("users", "id"),
    ("workspaces", "id"),
)


def snapshot():
    with SessionLocal() as db:
        return {
            name: {row[0] for row in db.execute(text(f"SELECT {key} FROM {name}"))}
            for name, key in TABLE_KEYS
        }


def row_snapshot():
    """Read-only requests must preserve values as well as row counts."""
    with SessionLocal() as db:
        return {
            name: list(db.execute(text(f"SELECT * FROM {name} ORDER BY {key}")))
            for name, key in TABLE_KEYS
        }


@pytest.mark.parametrize("model_name", ["PolicyCreateRequest", "PolicyUpdateRequest"])
@pytest.mark.parametrize("value", ["r" * 256, "role\x00name", "role\nname", "İ" * 128])
def test_policy_schemas_reject_unsafe_or_oversized_recipient_values(model_name, value):
    from app.api.routes import notifications

    model = getattr(notifications, model_name)
    with pytest.raises(ValidationError):
        model(event_type="member.joined", recipient_type="role", recipient_value=value)


@pytest.fixture
def actors(_ensure_test_data):
    if not _ensure_test_data:
        pytest.fail("PostgreSQL is required for notification domain acceptance")
    before = snapshot()
    token = uuid.uuid4().hex
    data = {}
    try:
        with SessionLocal() as db:
            # Earlier baseline fixtures insert explicit workspace ids.
            db.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence('workspaces', 'id'), "
                    "(SELECT GREATEST(COALESCE(MAX(id), 1), 1) FROM workspaces))"
                )
            )
            ws = Workspace(name="Notification test", slug=f"notification-{token}")
            other = Workspace(name="Other notification test", slug=f"notification-other-{token}")
            db.add_all([ws, other])
            db.flush()
            data.update(ws=ws.id, other_ws=other.id)
            for role in ("admin", "editor", "reviewer", "suspended", "other"):
                user = User(
                    email=f"notification-{role}-{token}@test.local",
                    display_name=role,
                    password_hash=hash_password("test-password"),
                )
                db.add(user)
                db.flush()
                db.add(
                    WorkspaceMember(
                        workspace_id=other.id if role == "other" else ws.id,
                        user_id=user.id,
                        role="admin" if role in ("other", "suspended") else role,
                        suspended=role == "suspended",
                    )
                )
                data[role] = {"id": user.id, "email": user.email}
            db.add_all(
                [
                    CustomRole(workspace_id=ws.id, name="local-role", can_admin=False),
                    CustomRole(workspace_id=other.id, name="foreign-role", can_admin=False),
                ]
            )
            db.commit()
        yield data
    finally:
        current = snapshot()
        with SessionLocal() as db:
            for name, key in TABLE_KEYS:
                created = list(current[name] - before[name])
                if created:
                    stmt = text(f"DELETE FROM {name} WHERE {key} IN :ids").bindparams(
                        bindparam("ids", expanding=True)
                    )
                    db.execute(stmt, {"ids": created})
            db.commit()
        after = snapshot()
        assert after == before, {
            name: (len(before[name]), len(after[name])) for name, _ in TABLE_KEYS
        }


@contextmanager
def client_for(actors, role="admin"):
    with TestClient(app, headers=TEST_HEADERS) as client:
        if role is not None:
            response = client.post(
                "/api/auth/login",
                json={"email": actors[role]["email"], "password": "test-password"},
            )
            assert response.status_code == 200, response.text
        yield client


@pytest.mark.parametrize("recipient", ["other", "suspended", "missing"])
def test_create_user_policy_requires_active_workspace_recipient(actors, recipient):
    value = actors[recipient]["id"] if recipient != "missing" else 2_000_000_000
    with client_for(actors) as client:
        response = client.post(
            "/api/notifications/policies",
            json={
                "event_type": "member.joined",
                "recipient_type": "user",
                "recipient_value": str(value),
            },
        )
    assert response.status_code == 404
    assert response.json() == {"detail": "Recipient not found"}
    with SessionLocal() as db:
        assert db.query(NotificationPolicy).filter_by(workspace_id=actors["ws"]).count() == 0


@pytest.mark.parametrize("role", ["foreign-role", "missing-role"])
def test_create_role_policy_requires_known_workspace_role(actors, role):
    with client_for(actors) as client:
        response = client.post(
            "/api/notifications/policies",
            json={"event_type": "member.joined", "recipient_type": "role", "recipient_value": role},
        )
    assert response.status_code == 404
    assert response.json() == {"detail": "Recipient not found"}


def test_policy_patch_validates_complete_prospective_recipient_before_write(actors):
    with client_for(actors) as client:
        created = client.post("/api/notifications/policies", json={"event_type": "member.joined"})
        assert created.status_code == 200
        policy_id = created.json()["id"]
        response = client.patch(
            f"/api/notifications/policies/{policy_id}",
            json={"enabled": False, "recipient_type": "user"},
        )
        assert response.status_code == 400
        listed = client.get("/api/notifications/policies").json()["policies"][0]
        assert listed["enabled"] is True
        assert listed["recipient_type"] == "admins"
        assert listed["recipient_value"] is None


def test_policy_recipient_normalizes_and_survives_new_connection(actors):
    with client_for(actors) as client:
        response = client.post(
            "/api/notifications/policies",
            json={
                "event_type": "member.joined",
                "recipient_type": " USER ",
                "recipient_value": f"  {actors['editor']['id']}  ",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["recipient_value"] == str(actors["editor"]["id"])
        engine.dispose()
        listed = client.get("/api/notifications/policies").json()["policies"][0]
        for key in ("id", "event_type", "enabled", "recipient_type", "recipient_value"):
            assert listed[key] == body[key]
        response = client.patch(
            f"/api/notifications/policies/{body['id']}",
            json={"recipient_type": "all", "recipient_value": None},
        )
        assert response.status_code == 200
        assert response.json()["recipient_value"] is None
    with SessionLocal() as db:
        row = db.get(NotificationPolicy, body["id"])
        assert row.recipient_type == "all"
        assert row.recipient_value is None


@pytest.mark.parametrize("change", ["removed", "suspended", "role_deleted"])
def test_disable_stale_recipient_policy_then_reject_reenable(actors, change):
    role = change == "role_deleted"
    with client_for(actors) as client:
        response = client.post(
            "/api/notifications/policies",
            json={
                "event_type": "member.joined",
                "recipient_type": "role" if role else "user",
                "recipient_value": "local-role" if role else str(actors["editor"]["id"]),
            },
        )
        assert response.status_code == 200
        path = f"/api/notifications/policies/{response.json()['id']}"
        with SessionLocal() as db:
            if role:
                db.delete(
                    db.query(CustomRole)
                    .filter_by(workspace_id=actors["ws"], name="local-role")
                    .one()
                )
            else:
                member = (
                    db.query(WorkspaceMember)
                    .filter_by(workspace_id=actors["ws"], user_id=actors["editor"]["id"])
                    .one()
                )
                if change == "removed":
                    db.delete(member)
                else:
                    member.suspended = True
            db.commit()
        disabled = client.patch(path, json={"enabled": False})
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["enabled"] is False
        rejected = client.patch(path, json={"enabled": True})
        assert rejected.status_code == 404
        assert client.get("/api/notifications/policies").json()["policies"][0]["enabled"] is False


@pytest.mark.parametrize("role,expected", [(None, 401), ("editor", 403), ("reviewer", 403)])
@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("post", "/policies", {"event_type": "member.joined"}),
        ("patch", "/policies/2000000000", {"enabled": False}),
        ("delete", "/policies/2000000000", None),
    ],
)
def test_policy_mutations_require_admin(actors, role, expected, method, path, payload):
    with client_for(actors, role) as client:
        response = client.request(
            method, "/api/notifications" + path, **({"json": payload} if payload else {})
        )
    assert response.status_code == expected


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("post", "/unsubscribes", {"event_type": "member.joined"}),
        ("delete", "/unsubscribes/2000000000", None),
        ("put", "/channel-preferences", {"channel": "email", "enabled": False}),
    ],
)
def test_personal_mutations_require_authentication(actors, method, path, payload):
    with client_for(actors, None) as client:
        response = client.request(
            method, "/api/notifications" + path, **({"json": payload} if payload else {})
        )
    assert response.status_code == 401


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_foreign_policy_and_missing_policy_are_identical(actors, method):
    with SessionLocal() as db:
        foreign = NotificationPolicy(workspace_id=actors["other_ws"], event_type="member.joined")
        db.add(foreign)
        db.commit()
        foreign_id = foreign.id
    with client_for(actors) as client:
        responses = [
            client.request(
                method,
                f"/api/notifications/policies/{pid}",
                **({"json": {"enabled": False}} if method == "patch" else {}),
            )
            for pid in (foreign_id, 2_000_000_000)
        ]
    assert [r.status_code for r in responses] == [404, 404]
    assert responses[0].json() == responses[1].json()


@pytest.mark.parametrize("change", ["removed", "demoted"])
def test_policy_mutation_rechecks_current_membership(actors, change):
    with client_for(actors) as client:
        with SessionLocal() as db:
            member = (
                db.query(WorkspaceMember)
                .filter_by(workspace_id=actors["ws"], user_id=actors["admin"]["id"])
                .one()
            )
            if change == "removed":
                db.delete(member)
            else:
                member.role = "reviewer"
            db.commit()
        response = client.post("/api/notifications/policies", json={"event_type": "member.joined"})
    assert response.status_code == 403


def test_gets_are_read_only_and_logs_are_scoped_and_stably_paginated(actors):
    with SessionLocal() as db:
        for ws in (actors["ws"], actors["other_ws"]):
            for index in range(3):
                db.add(
                    NotificationLog(
                        workspace_id=ws,
                        event_type="member.joined",
                        channel="email",
                        recipient_email=f"recipient-{ws}-{index}@test.local",
                        status="failed",
                        delivery_state="dead-lettered",
                        delivered_to_provider=False,
                        provider_mode="http",
                        created_at=datetime(2026, 1, 2, 3, 4, 5),
                    )
                )
        db.commit()
    with client_for(actors) as client:
        before = row_snapshot()
        for path in (
            "event-types",
            "policies",
            "unsubscribes",
            "channel-preferences",
            "delivery-attempts",
        ):
            assert client.get("/api/notifications/" + path).status_code == 200
        pages = [
            client.get(f"/api/notifications/log?page={page}&page_size=1").json()
            for page in (1, 2, 3)
        ]
        assert [p["total"] for p in pages] == [3, 3, 3]
        assert len({p["entries"][0]["id"] for p in pages}) == 3
        ids = [p["entries"][0]["id"] for p in pages]
        assert ids == sorted(ids, reverse=True)
        assert all(p["entries"][0]["delivered_to_provider"] is False for p in pages)
        assert all(
            f"recipient-{actors['ws']}-" in p["entries"][0]["recipient_email"] for p in pages
        )
        assert row_snapshot() == before


def test_delivery_log_cannot_expose_foreign_in_app_reference(actors):
    from app.models.in_app_notification import InAppNotification

    with SessionLocal() as db:
        foreign = InAppNotification(
            workspace_id=actors["other_ws"],
            user_id=actors["other"]["id"],
            title="Foreign",
            body="Private",
            category="info",
        )
        db.add(foreign)
        db.flush()
        attempt = NotificationDeliveryAttempt(
            workspace_id=actors["ws"],
            event_type="member.joined",
            channel="in_app",
            recipient="current",
            user_id=actors["admin"]["id"],
            dedupe_key=uuid.uuid4().hex,
            state="sent",
            in_app_notification_id=foreign.id,
        )
        db.add(attempt)
        db.commit()
    with client_for(actors) as client:
        response = client.get("/api/notifications/delivery-attempts")
        assert response.status_code == 200
        assert response.json()["attempts"][0]["in_app_notification_id"] is None
        assert response.json()["attempts"][0]["is_read"] is None


def test_personal_preferences_retry_and_unsubscribe_are_scoped(actors):
    with client_for(actors, "editor") as client:
        payload = {"channel": "email", "enabled": False, "event_type": "member.joined"}
        first = client.put("/api/notifications/channel-preferences", json=payload)
        second = client.put("/api/notifications/channel-preferences", json=payload)
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        unsub = client.post("/api/notifications/unsubscribes", json={"event_type": "member.joined"})
        assert unsub.status_code == 200
        assert (
            client.post(
                "/api/notifications/unsubscribes", json={"event_type": "member.joined"}
            ).json()
            == unsub.json()
        )
        editor_unsub = unsub.json()["id"]
    with client_for(actors, "reviewer") as client:
        assert client.get("/api/notifications/channel-preferences").json()["preferences"] == []
        foreign = client.delete(f"/api/notifications/unsubscribes/{editor_unsub}")
        missing = client.delete("/api/notifications/unsubscribes/2000000000")
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()


@pytest.mark.parametrize("role", ["admin", "editor", "reviewer", "local-role"])
def test_policy_accepts_builtin_and_current_workspace_roles(actors, role):
    with client_for(actors) as client:
        response = client.post(
            "/api/notifications/policies",
            json={
                "event_type": "member.joined",
                "recipient_type": "role",
                "recipient_value": f" {role.upper()} ",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["recipient_value"] == role


@pytest.mark.parametrize("channel", ["email", "slack", "in_app"])
def test_static_renderer_preserves_copy_and_redaction_contract(channel):
    from app.services.notification_templates import render_notification

    rendered = render_notification(
        "member.joined", channel, "A&B <Workspace>", "token=xoxb-test-private-value"
    )
    assert rendered.template_key == f"member.joined:{channel}"
    assert rendered.label == rendered.title == "Member joined workspace"
    assert rendered.label in rendered.subject
    assert rendered.label in rendered.slack_text
    assert rendered.label in rendered.body_text
    assert "A&amp;B &lt;Workspace&gt;" in rendered.body_html
    assert "xoxb-test-private-value" not in repr(rendered)
    assert rendered.link == "/dashboard/notifications"


@pytest.mark.parametrize("accepted", [True, False])
def test_provider_result_retry_and_dedupe_survive_new_connection(actors, monkeypatch, accepted):
    from app.services import notification_service

    class FixtureProvider:
        provider_mode = "fixture"
        counts_as_provider = True

        def __init__(self):
            self.calls = []

        def send(self, message):
            self.calls.append(message)
            return accepted and len(self.calls) > 1

    provider = FixtureProvider()
    monkeypatch.setattr(notification_service, "get_email_provider", lambda: provider)
    event_id = uuid.uuid4().hex
    with client_for(actors) as client:
        response = client.post(
            "/api/notifications/policies",
            json={
                "event_type": "member.joined",
                "recipient_type": "user",
                "recipient_value": str(actors["editor"]["id"]),
            },
        )
        assert response.status_code == 200
        with SessionLocal() as db:
            sent = notification_service.fire_notification(
                db, actors["ws"], "member.joined", "Safe detail", "Workspace", event_id
            )
        assert sent == int(accepted)
        assert len(provider.calls) == (2 if accepted else 3)
        assert all(m.to == actors["editor"]["email"] for m in provider.calls)
        engine.dispose()
        log = client.get("/api/notifications/log").json()["entries"][0]
        assert log["status"] == ("sent" if accepted else "failed")
        assert log["delivery_state"] == ("sent" if accepted else "dead-lettered")
        assert log["delivered_to_provider"] is accepted
        assert log["provider_mode"] == "fixture"
        assert log["attempt_count"] == (2 if accepted else 3)
        attempts = client.get("/api/notifications/delivery-attempts").json()["attempts"]
        email = [row for row in attempts if row["channel"] == "email"]
        assert email[0]["state"] == log["delivery_state"]
        assert email[0]["delivered_to_provider"] is accepted
        assert email[0]["template_key"] == "member.joined:email"
        assert {r["state"] for r in email} == {"queued", "retrying", log["delivery_state"]}
        assert all(r["delivered_to_provider"] is False for r in email[1:])
        if accepted:
            # A persisted claim, not an in-process cache, prevents another send.
            with SessionLocal() as db:
                assert (
                    notification_service.fire_notification(
                        db, actors["ws"], "member.joined", "Safe detail", "Workspace", event_id
                    )
                    == 0
                )
            assert len(provider.calls) == 2
            assert client.get("/api/notifications/log").json()["total"] == 1
            attempts = client.get("/api/notifications/delivery-attempts").json()["attempts"]
            assert next(r for r in attempts if r["channel"] == "email")["state"] == "deduped"


@pytest.mark.parametrize("change", ["removed", "suspended"])
@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("post", "/unsubscribes", {"event_type": "member.joined"}),
        ("delete", "/unsubscribes/2000000000", None),
        ("put", "/channel-preferences", {"channel": "email", "enabled": False}),
    ],
)
def test_personal_mutations_recheck_membership(actors, change, method, path, payload):
    with client_for(actors, "editor") as client:
        with SessionLocal() as db:
            member = (
                db.query(WorkspaceMember)
                .filter_by(workspace_id=actors["ws"], user_id=actors["editor"]["id"])
                .one()
            )
            if change == "removed":
                db.delete(member)
            else:
                member.suspended = True
            db.commit()
        response = client.request(
            method, "/api/notifications" + path, **({"json": payload} if payload else {})
        )
        assert response.status_code == 403
