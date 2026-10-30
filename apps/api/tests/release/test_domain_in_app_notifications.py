"""Personal notification access and read state on PostgreSQL."""

import hashlib
import importlib.util
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, inspect, text
from sqlalchemy.exc import IntegrityError

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
RECEIPT_KEY = "workspace_id::text || ':' || notification_id::text || ':' || user_id::text"
TABLE_KEYS = (
    ("in_app_notification_receipts", RECEIPT_KEY),
    ("in_app_notification_receipts_archive", RECEIPT_KEY),
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
    ("tags", "id"),  # Real API startup may insert missing global system tags.
    ("workspace_members", "id"),
    ("users", "id"),
    ("workspaces", "id"),
)


def snapshot():
    with SessionLocal() as db:
        return {
            name: {row[0] for row in db.execute(text(f"SELECT {key} FROM {name}"))}
            for name, key in TABLE_KEYS
            if inspect(db.connection()).has_table(name)
        }


def row_snapshot():
    with SessionLocal() as db:
        return {
            name: list(db.execute(text(f"SELECT * FROM {name} ORDER BY {key}")))
            for name, key in TABLE_KEYS
            if inspect(db.connection()).has_table(name)
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
                created = list(current.get(name, set()) - before.get(name, set()))
                if created:
                    stmt = text(f"DELETE FROM {name} WHERE {key} IN :ids").bindparams(
                        bindparam("ids", expanding=True)
                    )
                    db.execute(stmt, {"ids": created})
            db.commit()
        after = snapshot()
        assert after == before, {
            name: (len(before.get(name, set())), len(after.get(name, set())))
            for name, _ in TABLE_KEYS
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


def note(
    actors, *, role="editor", workspace=None, admin_only=False, title="Inbox item", is_read=False
):
    with SessionLocal() as db:
        row = InAppNotification(
            workspace_id=workspace or actors["ws"],
            user_id=actors[role]["id"] if role else None,
            title=title,
            is_read=is_read,
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


def test_dispatch_database_failure_rolls_back_without_a_partial_notification(actors):
    from app.services.in_app_notification_service import notify_user

    with SessionLocal() as db:
        count = db.query(InAppNotification).count()
        # Exceed the real database column bound to exercise the rollback path.
        assert notify_user(db, actors["ws"], actors["editor"]["id"], "x" * 256) is None
        assert db.query(InAppNotification).count() == count
        valid = notify_user(db, actors["ws"], actors["editor"]["id"], "x" * 255)
        assert valid is not None
        assert db.query(InAppNotification).count() == count + 1


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


def require_receipt_table():
    assert inspect(engine).has_table(
        "in_app_notification_receipts"
    ), "Broadcast read state requires the approved per-member receipt table"


def receipts(notification_id):
    require_receipt_table()
    with SessionLocal() as db:
        return list(
            db.execute(
                text(
                    "SELECT workspace_id, notification_id, user_id, read_at "
                    "FROM in_app_notification_receipts WHERE notification_id=:id ORDER BY user_id"
                ),
                {"id": notification_id},
            )
        )


@pytest.mark.parametrize("action", ["one", "all"])
def test_broadcast_read_creates_only_callers_receipt_and_preserves_timestamp(actors, action):
    require_receipt_table()
    shared = note(actors, role=None)
    hidden = note(actors, role=None, admin_only=True)
    with client_for(actors, "editor") as client:
        path = f"/{shared}/read" if action == "one" else "/read-all"
        response = client.post("/api/in-app-notifications" + path)
        assert response.status_code == 200
        first = receipts(shared)
        assert len(first) == 1
        assert tuple(first[0][:3]) == (actors["ws"], shared, actors["editor"]["id"])
        assert first[0].read_at is not None
        assert client.post("/api/in-app-notifications" + path).status_code == 200
        engine.dispose()
        before_gets = row_snapshot()
        listed = client.get("/api/in-app-notifications").json()["notifications"]
        assert [(row["id"], row["is_read"]) for row in listed] == [(shared, True)]
        assert client.get("/api/in-app-notifications/unread-count").json() == {"count": 0}
        assert row_snapshot() == before_gets
        assert receipts(shared) == first
    assert receipts(hidden) == []
    with SessionLocal() as db:
        assert db.get(InAppNotification, shared).is_read is False


@pytest.mark.parametrize("action", ["one", "all"])
def test_legacy_read_broadcast_stays_read_without_backfilling_receipts(actors, action):
    require_receipt_table()
    shared = note(actors, role=None, is_read=True)
    for role in ("editor", "reviewer"):
        with client_for(actors, role) as client:
            before = row_snapshot()
            assert client.get("/api/in-app-notifications/unread-count").json() == {"count": 0}
            assert (
                client.get("/api/in-app-notifications").json()["notifications"][0]["is_read"]
                is True
            )
            assert row_snapshot() == before
            path = f"/{shared}/read" if action == "one" else "/read-all"
            response = client.post("/api/in-app-notifications" + path)
            assert response.status_code == 200
            if action == "all":
                assert response.json() == {"updated": 0}
    assert receipts(shared) == []
    with SessionLocal() as db:
        assert db.get(InAppNotification, shared).is_read is True


@pytest.mark.parametrize("reference", ["notification", "member"])
@pytest.mark.parametrize("operation", ["insert", "update"])
def test_receipts_reject_cross_workspace_references(actors, reference, operation):
    require_receipt_table()
    own = note(actors, role=None)
    foreign = note(actors, role=None, workspace=actors["other_ws"])
    with SessionLocal() as db:
        params = {"ws": actors["ws"], "nid": own, "uid": actors["editor"]["id"]}
        insert = text(
            "INSERT INTO in_app_notification_receipts "
            "(workspace_id, notification_id, user_id, read_at) "
            "VALUES (:ws,:nid,:uid,:at)"
        )
        params["at"] = datetime(2020, 2, 3, 4, 5, 6, 123456, tzinfo=timezone.utc)
        if operation == "update":
            db.execute(insert, params)
            db.commit()
        if reference == "notification":
            params["nid"] = foreign
        else:
            params["uid"] = actors["other"]["id"]
        with pytest.raises(IntegrityError) as exc:
            db.execute(
                insert
                if operation == "insert"
                else text(
                    "UPDATE in_app_notification_receipts SET notification_id=:nid,user_id=:uid "
                    "WHERE workspace_id=:ws"
                ),
                params,
            )
            db.commit()
        assert exc.value.orig.pgcode == "23503"
        db.rollback()
    if operation == "update":
        assert tuple(receipts(own)[0][:3]) == (actors["ws"], own, actors["editor"]["id"])


@contextmanager
def receipt_migration(actors):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    path = Path(__file__).resolve().parents[2] / "alembic/versions/tc19010_inbox_receipts.py"
    assert path.is_file(), "The approved receipt schema requires a reversible migration"
    spec = importlib.util.spec_from_file_location("tc19010_receipts_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    require_receipt_table()
    # PostgreSQL transactional DDL keeps every receipt/schema change isolated.
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Operations.context(MigrationContext.configure(connection)):
                yield connection, migration
        finally:
            transaction.rollback()


def test_receipt_migration_roundtrip_preserves_nondefault_data_and_legacy_rows(actors):
    shared = note(actors, role=None, is_read=True)
    with receipt_migration(actors) as (connection, migration):
        expected_time = datetime(2019, 7, 6, 5, 4, 3, 123456, tzinfo=timezone.utc)
        connection.execute(
            text(
                "INSERT INTO in_app_notification_receipts "
                "(workspace_id, notification_id, user_id, read_at) VALUES (:ws,:nid,:uid,:at)"
            ),
            {"ws": actors["ws"], "nid": shared, "uid": actors["editor"]["id"], "at": expected_time},
        )
        connection.execute(
            text(
                "INSERT INTO in_app_notification_receipts "
                "(workspace_id, notification_id, user_id, read_at) VALUES (:ws,:nid,:uid,:at)"
            ),
            {
                "ws": actors["ws"],
                "nid": shared,
                "uid": actors["reviewer"]["id"],
                "at": datetime(2022, 3, 4, 5, 6, 7, 654321, tzinfo=timezone.utc),
            },
        )
        expected = list(
            connection.execute(
                text(
                    "SELECT * FROM in_app_notification_receipts ORDER BY workspace_id, notification_id, user_id"
                )
            )
        )
        legacy = list(connection.execute(text("SELECT * FROM in_app_notifications ORDER BY id")))
        for _ in range(2):
            migration.downgrade()
            assert not inspect(connection).has_table("in_app_notification_receipts")
            assert (
                list(
                    connection.execute(
                        text(
                            "SELECT * FROM in_app_notification_receipts_archive ORDER BY workspace_id, notification_id, user_id"
                        )
                    )
                )
                == expected
            )
            assert (
                list(connection.execute(text("SELECT * FROM in_app_notifications ORDER BY id")))
                == legacy
            )
            migration.upgrade()
            assert (
                list(
                    connection.execute(
                        text(
                            "SELECT * FROM in_app_notification_receipts ORDER BY workspace_id, notification_id, user_id"
                        )
                    )
                )
                == expected
            )
            assert not inspect(connection).has_table("in_app_notification_receipts_archive")
            assert (
                list(connection.execute(text("SELECT * FROM in_app_notifications ORDER BY id")))
                == legacy
            )


def test_receipt_migration_restore_fails_closed_if_membership_was_removed(actors):
    shared = note(actors, role=None)
    with receipt_migration(actors) as (connection, migration):
        connection.execute(
            text(
                "INSERT INTO in_app_notification_receipts "
                "(workspace_id, notification_id, user_id, read_at) VALUES (:ws,:nid,:uid,:at)"
            ),
            {
                "ws": actors["ws"],
                "nid": shared,
                "uid": actors["editor"]["id"],
                "at": datetime(2021, 1, 2, tzinfo=timezone.utc),
            },
        )
        migration.downgrade()
        archived = list(
            connection.execute(text("SELECT * FROM in_app_notification_receipts_archive"))
        )
        connection.execute(
            text("DELETE FROM workspace_members WHERE workspace_id=:ws AND user_id=:uid"),
            {"ws": actors["ws"], "uid": actors["editor"]["id"]},
        )
        with pytest.raises(IntegrityError) as exc:
            with connection.begin_nested():
                migration.upgrade()
        assert exc.value.orig.pgcode == "23503"
        assert (
            list(connection.execute(text("SELECT * FROM in_app_notification_receipts_archive")))
            == archived
        )
        assert not inspect(connection).has_table("in_app_notification_receipts")


@pytest.mark.parametrize("action", ["one", "all"])
def test_concurrent_broadcast_reads_create_one_receipt(actors, action):
    require_receipt_table()
    shared = note(actors, role=None)
    path = f"/{shared}/read" if action == "one" else "/read-all"
    barrier = Barrier(2)

    def mark(client):
        barrier.wait(timeout=10)
        response = client.post("/api/in-app-notifications" + path)
        assert response.status_code == 200, response.text
        return response.json()

    with client_for(actors, "editor") as first, client_for(actors, "editor") as second:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(mark, (first, second)))
        assert len(receipts(shared)) == 1
        recorded = receipts(shared)
        if action == "all":
            assert sorted(row["updated"] for row in results) == [0, 1]
        else:
            assert results == [{"ok": True}, {"ok": True}]
        assert first.post("/api/in-app-notifications" + path).status_code == 200
        assert receipts(shared) == recorded
        assert first.get("/api/in-app-notifications/unread-count").json() == {"count": 0}
    with SessionLocal() as db:
        assert db.get(InAppNotification, shared).is_read is False


@contextmanager
def _inbox_service(command, cwd, env, log_path):
    """Own and reap only this acceptance test's service process group."""
    with log_path.open("w") as log:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            yield process
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
            assert process.returncode is not None, "Acceptance service was not reaped"


def _inbox_wait_ready(process, url):
    deadline = time.monotonic() + 120
    with httpx.Client(trust_env=False, timeout=2) as client:
        while time.monotonic() < deadline:
            assert process.poll() is None, "Acceptance service exited before becoming ready"
            try:
                if client.get(url).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.2)
    pytest.fail("Acceptance service did not become ready within 120 seconds")


def test_inbox_ui_api_and_database_agree_after_full_process_restart(actors, tmp_path):
    """Catch page-sized counts, lost durable reads and cross-recipient broadcast updates.

    No route mocks: Chromium -> Next proxy -> a real API process -> PostgreSQL.
    Both service processes are terminated/reaped between phases; the second
    Playwright invocation also creates a fresh browser context.
    """
    from tests import _safety

    api_root = Path(__file__).resolve().parents[2]
    web_root = api_root.parent / "web"
    node = shutil.which("node")
    next_cli = web_root / "node_modules/next/dist/bin/next"
    playwright_cli = web_root / "node_modules/@playwright/test/cli.js"
    # Deliberately fail, never skip: CI's TC_REQUIRE_DB / web-toolchain gates
    # must not report AC3 green when its actual browser or database is absent.
    assert node and next_cli.is_file() and playwright_cli.is_file(), "Web toolchain required"
    _safety.validate_test_database_url(os.environ["DATABASE_URL"])

    visible = [
        {"id": note(actors, title=f"Personal item {index}"), "title": f"Personal item {index}"}
        for index in range(23)
    ]
    broadcasts = [
        {
            "id": note(actors, role=None, title=f"Shared item {index}"),
            "title": f"Shared item {index}",
        }
        for index in range(2)
    ]
    visible.extend(broadcasts)
    hidden = [
        {
            "id": note(actors, admin_only=True, title="Hidden admin item"),
            "title": "Hidden admin item",
        },
        {
            "id": note(actors, role="reviewer", title="Other recipient item"),
            "title": "Other recipient item",
        },
        {
            "id": note(actors, role="other", workspace=actors["other_ws"], title="Foreign item"),
            "title": "Foreign item",
        },
    ]
    persisted_query = text(
        "SELECT * FROM in_app_notifications " "WHERE workspace_id IN (:ws, :other_ws) ORDER BY id"
    )
    workspace_ids = {"ws": actors["ws"], "other_ws": actors["other_ws"]}
    with SessionLocal() as db:
        seeded_rows = [dict(row) for row in db.execute(persisted_query, workspace_ids).mappings()]
    assert len(seeded_rows) == 28
    fixture = {
        "email": actors["editor"]["email"],
        "reviewerEmail": actors["reviewer"]["email"],
        "password": "test-password",
        "visible": list(reversed(visible)),
        "hidden": hidden,
        "personal": visible[22],
        "shared": broadcasts[0],
        "reviewerVisible": [hidden[1], *reversed(broadcasts)],
    }
    # Bind both ports simultaneously before releasing them, avoiding accidental
    # reuse of the same ephemeral port. Never kill a pre-existing listener.
    with socket.socket() as api_socket, socket.socket() as web_socket:
        api_socket.bind(("127.0.0.1", 0))
        web_socket.bind(("127.0.0.1", 0))
        api_port, web_port = api_socket.getsockname()[1], web_socket.getsockname()[1]
    api_url, web_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{web_port}"
    env = {
        **os.environ,
        "APP_ENV": "test",
        "TRUST_COPILOT_TESTING": "1",
        "TC_INBOX_API_PORT": str(api_port),
        "TC_INBOX_BASE_URL": web_url,
        "TC_INBOX_FIXTURE": json.dumps(fixture),
        "API_UPSTREAM": api_url,
        "FRONTEND_URL": web_url,
        "APP_BASE_URL": web_url,
        "TRUSTED_ORIGINS": web_url,
        # Inbox acceptance has no storage dependency. The optional startup
        # bucket initializer rejects missing credentials before any storage I/O.
        "S3_ACCESS_KEY": "",
        "S3_SECRET_KEY": "",
        "NEXT_DIST_DIR": ".next",
        "NEXT_TELEMETRY_DISABLED": "1",
        "PLAYWRIGHT_HTML_OPEN": "never",
    }
    _safety.scrub_provider_env(env)
    assert env.get("SESSION_SECRET"), "A stable signing secret is required across process restarts"
    # The child has a new interpreter, so install the existing egress guard there
    # before importing the application. Keep the exact signing secret across runs.
    bootstrap = (
        "import os; from tests import _safety; "
        "_safety.scrub_provider_env(); "
        "_safety.validate_test_database_url(os.environ['DATABASE_URL']); "
        "_safety.install_network_guard(); "
        "import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', "
        "port=int(os.environ['TC_INBOX_API_PORT']))"
    )
    output = web_root / "test-results/inbox-restart"
    output.mkdir(parents=True, exist_ok=True)
    for name in ("before.json", "after.json", "processes.json"):
        (output / name).unlink(missing_ok=True)
    checkpoints = []
    first_receipts = None
    for phase in ("before", "after"):
        phase_env = {
            **env,
            "TC_INBOX_PHASE": phase,
            "PLAYWRIGHT_JSON_OUTPUT_FILE": str(output / f"{phase}.json"),
            "PLAYWRIGHT_HTML_OUTPUT_DIR": str(web_root / "playwright-report/inbox-restart" / phase),
        }
        with (
            _inbox_service(
                [sys.executable, "-c", bootstrap],
                api_root,
                phase_env,
                tmp_path / f"api-{phase}.log",
            ) as api,
            _inbox_service(
                [node, str(next_cli), "dev", "--hostname", "127.0.0.1", "--port", str(web_port)],
                web_root,
                phase_env,
                tmp_path / f"web-{phase}.log",
            ) as web,
        ):
            _inbox_wait_ready(api, f"{api_url}/healthz")
            _inbox_wait_ready(web, f"{web_url}/login")
            browser_log = tmp_path / f"browser-{phase}.log"
            with _inbox_service(
                [
                    node,
                    str(playwright_cli),
                    "test",
                    "--config=playwright.inbox.config.ts",
                    "--grep",
                    f"{phase} restart:",
                ],
                cwd=web_root,
                env=phase_env,
                log_path=browser_log,
            ) as browser:
                browser.wait(timeout=240)
            assert browser.returncode == 0, browser_log.read_text()
            report = json.loads((output / f"{phase}.json").read_text())
            assert report["stats"]["expected"] == 1
            assert all(report["stats"][key] == 0 for key in ("unexpected", "skipped", "flaky"))
        # Context exit must actually reap both old processes before the next
        # phase starts. A new client or engine.dispose() is not a restart.
        checkpoints.append(
            {
                "phase": phase,
                "api_pid": api.pid,
                "web_pid": web.pid,
                "api_exit": api.returncode,
                "web_exit": web.returncode,
            }
        )
        (output / "processes.json").write_text(json.dumps(checkpoints, indent=2) + "\n")
        for port in (api_port, web_port):
            deadline = time.monotonic() + 10
            while True:
                with socket.socket() as probe:
                    if probe.connect_ex(("127.0.0.1", port)) != 0:
                        break
                assert time.monotonic() < deadline, "Old service still listening"
                time.sleep(0.1)
        recorded = receipts(broadcasts[0]["id"])
        assert len(recorded) == 1
        assert recorded[0].read_at is not None
        assert tuple(recorded[0][:3]) == (actors["ws"], broadcasts[0]["id"], actors["editor"]["id"])
        if first_receipts is None:
            first_receipts = recorded
        else:
            assert (
                recorded == first_receipts
            ), "Restart/retry changed the original receipt timestamp"
        read_personal_ids = (
            {visible[22]["id"]} if phase == "before" else {row["id"] for row in visible[:23]}
        )
        with SessionLocal() as db:
            # Compare every persisted field, not just booleans: hidden/broadcast
            # rows must be unchanged, with no new notifications or lost rows.
            assert [dict(row) for row in db.execute(persisted_query, workspace_ids).mappings()] == [
                {**row, "is_read": row["id"] in read_personal_ids} for row in seeded_rows
            ]
            receipt_ids = (
                db.execute(
                    text(
                        "SELECT notification_id FROM in_app_notification_receipts "
                        "WHERE workspace_id IN (:ws, :other_ws) ORDER BY notification_id"
                    ),
                    workspace_ids,
                )
                .scalars()
                .all()
            )
            assert receipt_ids == [row["id"] for row in broadcasts[: 1 if phase == "before" else 2]]
        second_receipts = receipts(broadcasts[1]["id"])
        assert len(second_receipts) == (0 if phase == "before" else 1)
        if second_receipts:
            assert tuple(second_receipts[0][:3]) == (
                actors["ws"],
                broadcasts[1]["id"],
                actors["editor"]["id"],
            )
            assert second_receipts[0].read_at is not None
    assert checkpoints[0]["api_pid"] != checkpoints[1]["api_pid"]
    assert checkpoints[0]["web_pid"] != checkpoints[1]["web_pid"]
    (output / "processes.json").write_text(json.dumps(checkpoints, indent=2) + "\n")
