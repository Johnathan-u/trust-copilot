"""Notification rule, preference and delivery-log boundaries on PostgreSQL."""

import uuid
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
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
                    )
                )
        db.commit()
    with client_for(actors) as client:
        before = snapshot()
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
        assert all(p["entries"][0]["delivered_to_provider"] is False for p in pages)
        assert all(
            f"recipient-{actors['ws']}-" in p["entries"][0]["recipient_email"] for p in pages
        )
        assert snapshot() == before


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
