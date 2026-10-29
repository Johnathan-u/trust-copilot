"""Personal notification access and read state on PostgreSQL."""

import hashlib
import uuid
from contextlib import contextmanager
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text

from app.core.database import SessionLocal, engine
from app.core.password import hash_password
from app.main import app
from app.models import (
    ApiKey,
    CustomRole,
    User,
    Workspace,
    WorkspaceMember,
)
from tests.conftest import TEST_HEADERS
from app.models.in_app_notification import InAppNotification

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
    ("api_keys", "id"),
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
    with SessionLocal() as db:
        return {
            name: list(db.execute(text(f"SELECT * FROM {name} ORDER BY {key}")))
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
            ws = Workspace(name="Notification test", slug=f"inbox-{token}")
            other = Workspace(name="Other notification test", slug=f"inbox-other-{token}")
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


def note(actors, *, role="editor", workspace=None, admin_only=False, title="Inbox item"):
    with SessionLocal() as db:
        row = InAppNotification(
            workspace_id=workspace or actors["ws"],
            user_id=actors[role]["id"] if role else None,
            title=title,
            body="Synthetic content",
            admin_only=admin_only,
            created_at=datetime(2026, 1, 1),
        )
        db.add(row)
        db.commit()
        return row.id


def test_mark_one_applies_the_same_visibility_as_list(actors):
    hidden = note(actors, admin_only=True)
    with client_for(actors, "editor") as client:
        assert client.get("/api/in-app-notifications").json()["total"] == 0
        response = client.post(f"/api/in-app-notifications/{hidden}/read")
        missing = client.post("/api/in-app-notifications/2000000000/read")
        assert response.status_code == missing.status_code == 404
        assert response.json() == missing.json()
    with SessionLocal() as db:
        assert db.get(InAppNotification, hidden).is_read is False


@pytest.mark.parametrize("path", ["", "/unread-count", "/read-all", "/2000000000/read"])
def test_removed_member_loses_inbox_access_immediately(actors, path):
    with client_for(actors, "editor") as client:
        with SessionLocal() as db:
            member = (
                db.query(WorkspaceMember)
                .filter_by(workspace_id=actors["ws"], user_id=actors["editor"]["id"])
                .one()
            )
            db.delete(member)
            db.commit()
        response = client.request(
            "POST" if "read-all" in path or path.endswith("/read") else "GET",
            "/api/in-app-notifications" + path,
        )
        assert response.status_code == 403


@pytest.mark.parametrize("path", ["/read-all", "/2000000000/read"])
def test_inbox_mutations_require_a_personal_authenticated_session(actors, path):
    with client_for(actors, None) as client:
        assert client.post("/api/in-app-notifications" + path).status_code == 401


def test_inbox_uses_current_role_for_admin_only_content(actors):
    hidden = note(actors, role="admin", admin_only=True)
    with client_for(actors) as client:
        with SessionLocal() as db:
            member = (
                db.query(WorkspaceMember)
                .filter_by(workspace_id=actors["ws"], user_id=actors["admin"]["id"])
                .one()
            )
            member.role = "editor"
            db.commit()
        assert client.get("/api/in-app-notifications").json()["total"] == 0
        assert client.post(f"/api/in-app-notifications/{hidden}/read").status_code == 404


def test_custom_admin_permission_controls_admin_only_visibility(actors):
    visible = note(actors, role="editor", admin_only=True)
    with client_for(actors, "editor") as client:
        with SessionLocal() as db:
            db.query(CustomRole).filter_by(
                workspace_id=actors["ws"], name="local-role"
            ).one().can_admin = True
            db.query(WorkspaceMember).filter_by(
                workspace_id=actors["ws"], user_id=actors["editor"]["id"]
            ).one().role = "local-role"
            db.commit()
        listed = client.get("/api/in-app-notifications").json()["notifications"]
        assert [row["id"] for row in listed] == [visible]
        assert client.post(f"/api/in-app-notifications/{visible}/read").status_code == 200


@pytest.mark.parametrize("action", ["one", "all"])
def test_api_key_cannot_mark_personal_notifications(actors, action):
    shared = note(actors, role=None)
    token = "synthetic-inbox-key-" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(
            ApiKey(
                workspace_id=actors["ws"],
                role="admin",
                key_hash=hashlib.sha256(token.encode()).hexdigest(),
                label="Synthetic fixture",
            )
        )
        db.commit()
    path = f"/{shared}/read" if action == "one" else "/read-all"
    with TestClient(app, headers={**TEST_HEADERS, "Authorization": "Bearer " + token}) as client:
        response = client.post("/api/in-app-notifications" + path)
        assert response.status_code == 400
    with SessionLocal() as db:
        assert db.get(InAppNotification, shared).is_read is False


def test_foreign_and_other_recipient_notification_match_missing(actors):
    foreign = note(actors, role="other", workspace=actors["other_ws"])
    another = note(actors, role="reviewer")
    with client_for(actors, "editor") as client:
        responses = [
            client.post(f"/api/in-app-notifications/{key}/read")
            for key in (foreign, another, 2_000_000_000)
        ]
        assert [r.status_code for r in responses] == [404, 404, 404]
        assert responses[0].json() == responses[1].json() == responses[2].json()


def test_pagination_unread_counts_and_retries_reconcile_without_get_writes(actors):
    ids = [note(actors, title=f"Item {index}") for index in range(4)]
    hidden = note(actors, admin_only=True)
    other = note(actors, role="reviewer")
    with client_for(actors, "editor") as client:
        before = row_snapshot()
        pages = [
            client.get(f"/api/in-app-notifications?limit=2&offset={offset}").json()
            for offset in (0, 2)
        ]
        assert [page["total"] for page in pages] == [4, 4]
        assert [item["id"] for page in pages for item in page["notifications"]] == sorted(
            ids, reverse=True
        )
        assert client.get("/api/in-app-notifications/unread-count").json() == {"count": 4}
        assert row_snapshot() == before
        first = client.post(f"/api/in-app-notifications/{ids[0]}/read")
        retry = client.post(f"/api/in-app-notifications/{ids[0]}/read")
        assert first.status_code == retry.status_code == 200
        assert first.json() == retry.json() == {"ok": True}
        engine.dispose()
        assert client.get("/api/in-app-notifications/unread-count").json() == {"count": 3}
        assert client.post("/api/in-app-notifications/read-all").json() == {"updated": 3}
        assert client.post("/api/in-app-notifications/read-all").json() == {"updated": 0}
        assert client.get("/api/in-app-notifications/unread-count").json() == {"count": 0}
    with SessionLocal() as db:
        assert db.get(InAppNotification, hidden).is_read is False
        assert db.get(InAppNotification, other).is_read is False


@pytest.mark.parametrize("action", ["one", "all"])
def test_shared_legacy_notification_read_state_is_personal(actors, action):
    shared = note(actors, role=None)
    with client_for(actors, "editor") as client:
        path = f"/{shared}/read" if action == "one" else "/read-all"
        assert client.post("/api/in-app-notifications" + path).status_code == 200
        assert client.get("/api/in-app-notifications/unread-count").json() == {"count": 0}
    with client_for(actors, "reviewer") as client:
        assert client.get("/api/in-app-notifications/unread-count").json() == {"count": 1}
        row = client.get("/api/in-app-notifications").json()["notifications"][0]
        assert row["id"] == shared
        assert row["is_read"] is False


@pytest.mark.parametrize("recipient", ["other", "suspended", "missing"])
def test_dispatch_does_not_create_an_inbox_item_for_an_unauthorized_recipient(actors, recipient):
    from app.services.in_app_notification_service import notify_user

    user_id = actors[recipient]["id"] if recipient != "missing" else 2_000_000_000
    with SessionLocal() as db:
        count = db.query(InAppNotification).count()
        result = notify_user(db, actors["ws"], user_id, "Synthetic notification")
        assert result is None
        assert db.query(InAppNotification).count() == count


def test_personal_preference_is_visible_only_to_its_user(actors):
    with client_for(actors, "editor") as client:
        response = client.put(
            "/api/notifications/channel-preferences", json={"channel": "in_app", "enabled": True}
        )
        assert response.status_code == 200
        assert (
            client.get("/api/notifications/channel-preferences").json()["effective"]["in_app"]
            is True
        )
    with client_for(actors, "reviewer") as client:
        assert client.get("/api/notifications/channel-preferences").json()["preferences"] == []
        assert (
            client.get("/api/notifications/channel-preferences").json()["effective"]["in_app"]
            is False
        )
