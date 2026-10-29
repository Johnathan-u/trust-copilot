"""TC-21-005 versioned control-mapping overrides.

Runs on PostgreSQL. Labels are synthetic, not framework text.
"""

import os
import subprocess
import sys
import uuid
from urllib.parse import quote
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, engine
from app.core.password import hash_password
from app.main import app
from app.models import User, Workspace, WorkspaceControl, WorkspaceMember
from tests.conftest import TEST_HEADERS, TEST_ORIGIN

API_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
PARENT = "bug018a_gap_closed_at_reason"
REVISION = "tc21005_mapping_version"
SLUG = "tc21005"
ADMIN_EMAIL = "tc21005-admin@trust.local"
EDITOR_EMAIL = "tc21005-editor@trust.local"
REVIEWER_EMAIL = "tc21005-reviewer@trust.local"
OTHER_EMAIL = "tc21005-other@trust.local"
ADMIN_PASSWORD = "test-a"
EDITOR_PASSWORD = "test-e"
REVIEWER_PASSWORD = "test-r"
OTHER_PASSWORD = "test-o"
_COUNTED = (
    "tc21005_mapping_hold",
    "tc21005_mapping_history",
    "control_mapping_override",
    "audit_events",
    "idempotency_keys",
    "in_app_notifications",
    "compliance_webhook_outbox",
    "workspace_controls",
    "user_sessions",
    "workspace_members",
    "users",
    "workspaces",
)


def _db() -> Session:
    return SessionLocal()


def _sync_sequence(session: Session, table: str) -> None:
    session.execute(
        text(
            "SELECT setval(pg_get_serial_sequence(:table, 'id'), "
            "(SELECT COALESCE(MAX(id), 1) FROM " + table + "))"
        ),
        {"table": table},
    )


def _reset_login_limit() -> None:
    from app.core import rate_limit

    with rate_limit._lock:
        rate_limit._store.clear()


def _counts() -> dict[str, int]:
    session = _db()
    try:
        return {
            name: int(session.execute(text(f"SELECT count(*) FROM {name}")).scalar() or 0)
            for name in _COUNTED
        }
    finally:
        session.close()


def _ids() -> dict[str, set[int]]:
    session = _db()
    try:
        found = {}
        for name in _COUNTED:
            rows = session.execute(text(f"SELECT id FROM {name}")).fetchall()
            found[name] = {row[0] for row in rows}
        return found
    finally:
        session.close()


def _delete_created(before: dict[str, set[int]], skip: tuple[str, ...] = ()) -> None:
    session = _db()
    try:
        for name in _COUNTED:
            if name in skip:
                continue
            current = {row[0] for row in session.execute(text(f"SELECT id FROM {name}")).fetchall()}
            created = sorted(current - before[name])
            if not created:
                continue
            statement = text(f"DELETE FROM {name} WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            )
            session.execute(statement, {"ids": created})
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture(autouse=True)
def restored_rows(request):
    if request.node.originalname == "test_migration_round_trip_restores_mapping_history":
        yield
        return
    _reset_login_limit()
    before_counts = _counts()
    before_ids = _ids()
    try:
        yield
    finally:
        _delete_created(before_ids)
        after_counts = _counts()
        assert after_counts == before_counts, {"before": before_counts, "after": after_counts}
        print(f"TC21005_COUNTS before={before_counts} after={after_counts}")


def _actors() -> dict[str, int]:
    session = _db()
    try:
        workspace = session.query(Workspace).filter(Workspace.slug == SLUG).one_or_none()
        if workspace is None:
            _sync_sequence(session, "workspaces")
            workspace = Workspace(name="TC-21-005", slug=SLUG)
            session.add(workspace)
            session.flush()
        other = session.query(Workspace).filter(Workspace.slug == SLUG + "-other").one_or_none()
        if other is None:
            _sync_sequence(session, "workspaces")
            other = Workspace(name="TC-21-005 other", slug=SLUG + "-other")
            session.add(other)
            session.flush()

        def member(email: str, password: str, role: str, ws: Workspace) -> User:
            user = session.query(User).filter(User.email == email).one_or_none()
            if user is None:
                _sync_sequence(session, "users")
                user = User(email=email, password_hash=hash_password(password), display_name=email)
                session.add(user)
                session.flush()
            else:
                user.password_hash = hash_password(password)
            row = (
                session.query(WorkspaceMember)
                .filter(
                    WorkspaceMember.user_id == user.id,
                    WorkspaceMember.workspace_id == ws.id,
                )
                .one_or_none()
            )
            if row is None:
                session.add(
                    WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=role, suspended=False)
                )
            else:
                row.role = role
                row.suspended = False
            return user

        admin = member(ADMIN_EMAIL, ADMIN_PASSWORD, "admin", workspace)
        editor = member(EDITOR_EMAIL, EDITOR_PASSWORD, "editor", workspace)
        reviewer = member(REVIEWER_EMAIL, REVIEWER_PASSWORD, "reviewer", workspace)
        member(OTHER_EMAIL, OTHER_PASSWORD, "admin", other)
        session.commit()
        return {
            "workspace_id": workspace.id,
            "other_workspace_id": other.id,
            "admin_id": admin.id,
            "editor_id": editor.id,
            "reviewer_id": reviewer.id,
        }
    finally:
        session.close()


def _login(client, email: str, password: str) -> None:
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def _control(workspace_id: int, name: str) -> int:
    session = _db()
    try:
        _sync_sequence(session, "workspace_controls")
        row = WorkspaceControl(
            workspace_id=workspace_id, status="not_implemented", custom_name=name
        )
        session.add(row)
        session.commit()
        return row.id
    finally:
        session.close()


def _table_count(table: str) -> int:
    session = _db()
    try:
        return int(session.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0)
    finally:
        session.close()


def _audits(mapping_id: int) -> list[dict]:
    session = _db()
    try:
        rows = session.execute(
            text(
                "SELECT action, user_id, occurred_at, details FROM audit_events "
                "WHERE resource_type = 'control_mapping' AND resource_id = :id "
                "ORDER BY id"
            ),
            {"id": str(mapping_id)},
        ).fetchall()
    finally:
        session.close()
    import json

    return [
        {
            "action": row.action,
            "user_id": row.user_id,
            "occurred_at": row.occurred_at,
            "details": json.loads(row.details),
        }
        for row in rows
    ]


def test_reads_stay_read_only_and_roles_are_denied(client):
    actors = _actors()
    control_id = _control(actors["workspace_id"], f"Deny {uuid.uuid4().hex[:8]}")
    question = f"synthetic deny {uuid.uuid4().hex[:8]}"
    routes = [
        ("GET", "/api/compliance/control-mappings", None, True),
        (
            "GET",
            "/api/compliance/control-mappings/suggest?question=" + quote(question),
            None,
            True,
        ),
        (
            "POST",
            "/api/compliance/control-mappings/confirm",
            {"question": question, "control_ids": [control_id]},
            False,
        ),
        (
            "POST",
            "/api/compliance/control-mappings/override",
            {
                "question": question,
                "control_ids": [control_id],
                "rationale": "synthetic override",
            },
            False,
        ),
        (
            "POST",
            "/api/compliance/control-mappings/rollback",
            {"question": question},
            False,
        ),
    ]
    client.cookies.clear()
    for method, path, body, _review in routes:
        response = client.get(path) if method == "GET" else client.post(path, json=body)
        assert response.status_code == 401, (method, path, response.text)
    for role, email, password in (
        ("reviewer", REVIEWER_EMAIL, REVIEWER_PASSWORD),
        ("editor", EDITOR_EMAIL, EDITOR_PASSWORD),
    ):
        _login(client, email, password)
        for method, path, body, review in routes:
            before = _counts()
            response = client.get(path) if method == "GET" else client.post(path, json=body)
            if review:
                assert response.status_code == 200, (role, path, response.text)
                assert _counts() == before
            else:
                assert response.status_code == 403, (role, path, response.text)
                assert response.json()["detail"] == "Insufficient permissions"
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    confirmed = client.post(
        "/api/compliance/control-mappings/confirm",
        json={"question": question, "control_ids": [control_id]},
    )
    assert confirmed.status_code == 200, confirmed.text
    overridden = client.post(
        "/api/compliance/control-mappings/override",
        json={
            "question": question,
            "control_ids": [control_id],
            "rationale": "synthetic override",
        },
    )
    assert overridden.status_code == 200, overridden.text
    rolled = client.post(
        "/api/compliance/control-mappings/rollback",
        json={"question": question},
    )
    assert rolled.status_code == 200, rolled.text
    assert client.get("/api/compliance/control-mappings").status_code == 200
    assert (
        client.get(f"/api/compliance/control-mappings/suggest?question={question}").status_code
        == 200
    )


def test_reviewer_id_timestamp_precedence_and_audit(client):
    actors = _actors()
    first_id = _control(actors["workspace_id"], f"First {uuid.uuid4().hex[:8]}")
    second_id = _control(actors["workspace_id"], f"Second {uuid.uuid4().hex[:8]}")
    question = f"synthetic precedence {uuid.uuid4().hex[:8]}"
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    before_override = _table_count("control_mapping_override")
    before_audit = _table_count("audit_events")
    suggested = client.get(
        "/api/compliance/control-mappings/suggest", params={"question": question}
    )
    assert suggested.status_code == 200, suggested.text
    assert suggested.json()["state"] == "proposed"
    assert suggested.json()["precedence"] == 1
    assert suggested.json()["has_override"] is False
    assert _table_count("control_mapping_override") == before_override
    assert _table_count("audit_events") == before_audit

    started = datetime.utcnow() - timedelta(seconds=5)
    confirmed = client.post(
        "/api/compliance/control-mappings/confirm",
        json={
            "question": question,
            "control_ids": [first_id],
            "reviewer_id": 999999,
            "reviewed_at": "1999-01-01T00:00:00",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["state"] == "confirmed"
    assert body["precedence"] == 2
    assert body["control_ids"] == [first_id]
    assert body["reviewed_by_user_id"] == actors["admin_id"]
    assert body["reviewed_by_user_id"] != 999999
    reviewed_at = datetime.fromisoformat(body["reviewed_at"])
    assert reviewed_at >= started
    assert reviewed_at.year != 1999
    session = _db()
    try:
        stored = session.execute(
            text(
                "SELECT state, version, reviewed_by_user_id, reviewed_at, override_control_ids "
                "FROM control_mapping_override WHERE id = :id"
            ),
            {"id": body["id"]},
        ).one()
    finally:
        session.close()
    assert stored.state == "confirmed"
    assert stored.version == 2
    assert stored.reviewed_by_user_id == actors["admin_id"]
    assert stored.reviewed_at == reviewed_at
    audits = _audits(body["id"])
    actions = [item["action"] for item in audits]
    assert actions == ["mapping.propose", "mapping.confirm"]
    propose, confirm = audits
    assert propose["user_id"] == actors["admin_id"]
    assert propose["details"]["previous_state"] is None
    assert propose["details"]["new_state"] == "proposed"
    assert propose["details"]["actor_user_id"] == actors["admin_id"]
    assert propose["occurred_at"] >= started
    assert confirm["details"]["previous_state"] == "proposed"
    assert confirm["details"]["new_state"] == "confirmed"
    assert confirm["details"]["rationale"] is None
    assert confirm["user_id"] == actors["admin_id"]

    blocked = client.post(
        "/api/compliance/control-mappings/override",
        json={"question": question, "control_ids": [second_id]},
    )
    assert blocked.status_code == 400
    assert blocked.json()["detail"] == "rationale is required"
    overridden = client.post(
        "/api/compliance/control-mappings/override",
        json={
            "question": question,
            "control_ids": [second_id],
            "rationale": "synthetic human override",
            "reviewer_id": 999999,
        },
    )
    assert overridden.status_code == 200, overridden.text
    assert overridden.json()["state"] == "overridden"
    assert overridden.json()["precedence"] == 3
    assert overridden.json()["reviewed_by_user_id"] == actors["admin_id"]
    assert overridden.json()["control_ids"] == [second_id]
    again = client.post(
        "/api/compliance/control-mappings/confirm",
        json={"question": question, "control_ids": [first_id]},
    )
    assert again.status_code == 200, again.text
    assert again.json()["precedence_held"] is True
    assert again.json()["state"] == "overridden"
    assert again.json()["control_ids"] == [second_id]
    assert again.json()["version"] == overridden.json()["version"]
    winner = client.get("/api/compliance/control-mappings/suggest", params={"question": question})
    assert winner.json()["control_ids"] == [second_id]
    assert winner.json()["has_override"] is True
    assert winner.json()["precedence"] == 3
    rolled = client.post("/api/compliance/control-mappings/rollback", json={"question": question})
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["state"] == "confirmed"
    assert rolled.json()["control_ids"] == [first_id]
    assert rolled.json()["reviewed_by_user_id"] == actors["admin_id"]
    rollback_audit = _audits(body["id"])[-1]
    assert rollback_audit["action"] == "mapping.rollback"
    assert rollback_audit["user_id"] == actors["admin_id"]
    assert rollback_audit["details"]["previous_state"] == "overridden"
    assert rollback_audit["details"]["new_state"] == "confirmed"
    assert rollback_audit["details"]["rationale"] is None
    session = _db()
    try:
        history = session.execute(
            text(
                "SELECT state, control_ids, reviewed_by_user_id FROM tc21005_mapping_history "
                "WHERE mapping_id = :id ORDER BY id"
            ),
            {"id": body["id"]},
        ).fetchall()
    finally:
        session.close()
    assert [row.state for row in history] == ["proposed", "confirmed", "overridden"]
    assert history[-1].reviewed_by_user_id == actors["admin_id"]


def test_missing_and_foreign_controls_share_the_404(client):
    actors = _actors()
    own = _control(actors["workspace_id"], f"Own {uuid.uuid4().hex[:8]}")
    foreign = _control(actors["other_workspace_id"], f"Foreign {uuid.uuid4().hex[:8]}")
    question = f"synthetic scope {uuid.uuid4().hex[:8]}"
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    missing = client.post(
        "/api/compliance/control-mappings/confirm",
        json={"question": question, "control_ids": [999999991]},
    )
    other = client.post(
        "/api/compliance/control-mappings/confirm",
        json={"question": question, "control_ids": [foreign]},
    )
    assert missing.status_code == 404
    assert missing.json() == other.json()
    assert missing.json() == {"detail": "Control not found"}
    saved = client.post(
        "/api/compliance/control-mappings/confirm",
        json={"question": question, "control_ids": [own]},
    )
    assert saved.status_code == 200, saved.text
    _login(client, OTHER_EMAIL, OTHER_PASSWORD)
    hidden = client.post(
        "/api/compliance/control-mappings/rollback",
        json={"question": question},
    )
    absent = client.post(
        "/api/compliance/control-mappings/rollback",
        json={"question": f"missing {uuid.uuid4().hex}"},
    )
    assert hidden.status_code == 404
    assert hidden.json() == absent.json()
    assert hidden.json() == {"detail": "Mapping not found"}


def test_missing_and_foreign_source_refs_share_the_404(client):
    actors = _actors()
    own = _control(actors["workspace_id"], f"Src own {uuid.uuid4().hex[:8]}")
    foreign = _control(actors["other_workspace_id"], f"Src foreign {uuid.uuid4().hex[:8]}")
    question = f"synthetic source {uuid.uuid4().hex[:8]}"
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    missing = client.post(
        "/api/compliance/control-mappings/confirm",
        json={"question": question, "control_ids": [own], "source_control_id": 999999991},
    )
    other = client.post(
        "/api/compliance/control-mappings/override",
        json={
            "question": question,
            "control_ids": [own],
            "source_control_id": foreign,
            "rationale": "synthetic source check",
        },
    )
    assert missing.status_code == 404, missing.text
    assert other.status_code == 404, other.text
    assert missing.json() == other.json()
    assert missing.json() == {"detail": "Control not found"}


def test_audit_rows_for_every_state_change(client):
    actors = _actors()
    first_id = _control(actors["workspace_id"], f"Audit a {uuid.uuid4().hex[:8]}")
    second_id = _control(actors["workspace_id"], f"Audit b {uuid.uuid4().hex[:8]}")
    question = f"synthetic audit {uuid.uuid4().hex[:8]}"
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    started = datetime.utcnow() - timedelta(seconds=5)
    confirmed = client.post(
        "/api/compliance/control-mappings/confirm",
        json={
            "question": question,
            "control_ids": [first_id],
            "rationale": "synthetic confirmation",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    overridden = client.post(
        "/api/compliance/control-mappings/override",
        json={
            "question": question,
            "control_ids": [second_id],
            "rationale": "synthetic human override",
        },
    )
    assert overridden.status_code == 200, overridden.text
    rolled = client.post("/api/compliance/control-mappings/rollback", json={"question": question})
    assert rolled.status_code == 200, rolled.text
    rows = {item["action"]: item for item in _audits(confirmed.json()["id"])}
    expected = {
        "mapping.propose": (None, "proposed", None),
        "mapping.confirm": ("proposed", "confirmed", "synthetic confirmation"),
        "mapping.override": ("confirmed", "overridden", "synthetic human override"),
        "mapping.rollback": ("overridden", "confirmed", "synthetic confirmation"),
    }
    assert set(rows) == set(expected)
    for action, (previous, new, rationale) in expected.items():
        item = rows[action]
        assert item["user_id"] == actors["admin_id"]
        assert item["occurred_at"] is not None
        assert item["occurred_at"] >= started
        assert item["details"]["actor_user_id"] == actors["admin_id"]
        assert item["details"]["timestamp"]
        assert item["details"]["previous_state"] == previous
        assert item["details"]["new_state"] == new
        assert item["details"]["rationale"] == rationale


def test_same_key_retry_and_failed_commit_leave_one_version(client):
    actors = _actors()
    control_id = _control(actors["workspace_id"], f"Idem {uuid.uuid4().hex[:8]}")
    question = f"synthetic idem {uuid.uuid4().hex[:8]}"
    key = f"map-{uuid.uuid4().hex}"
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    overrides = _table_count("control_mapping_override")
    history = _table_count("tc21005_mapping_history")
    audits = _table_count("audit_events")
    first = client.post(
        "/api/compliance/control-mappings/confirm",
        json={"question": question, "control_ids": [control_id]},
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 200, first.text
    assert _table_count("control_mapping_override") == overrides + 1
    assert _table_count("tc21005_mapping_history") == history + 1
    after_first_audits = _table_count("audit_events")
    assert after_first_audits >= audits + 2
    retried = client.post(
        "/api/compliance/control-mappings/confirm",
        json={"question": question, "control_ids": [control_id]},
        headers={"Idempotency-Key": key},
    )
    assert retried.status_code == 200
    assert retried.json() == first.json()
    assert _table_count("control_mapping_override") == overrides + 1
    assert _table_count("tc21005_mapping_history") == history + 1
    assert _table_count("audit_events") == after_first_audits

    fail_question = f"synthetic fail {uuid.uuid4().hex[:8]}"
    fail_key = f"map-fail-{uuid.uuid4().hex}"
    real_commit = Session.commit
    seen = {"n": 0}

    def failing_commit(self, *args, **kwargs):
        seen["n"] += 1
        if seen["n"] == 2:
            raise RuntimeError("forced commit failure")
        return real_commit(self, *args, **kwargs)

    quiet = TestClient(
        app, base_url=TEST_ORIGIN, headers=TEST_HEADERS, raise_server_exceptions=False
    )
    _login(quiet, ADMIN_EMAIL, ADMIN_PASSWORD)
    before_overrides = _table_count("control_mapping_override")
    before_history = _table_count("tc21005_mapping_history")
    before_audits = _table_count("audit_events")
    with patch.object(Session, "commit", failing_commit):
        failed = quiet.post(
            "/api/compliance/control-mappings/override",
            json={
                "question": fail_question,
                "control_ids": [control_id],
                "rationale": "synthetic failure",
            },
            headers={"Idempotency-Key": fail_key},
        )
    assert failed.status_code == 500, failed.text
    assert _table_count("control_mapping_override") == before_overrides
    assert _table_count("tc21005_mapping_history") == before_history
    assert _table_count("audit_events") == before_audits
    session = _db()
    try:
        from app.services.question_normalizer import normalize_question, question_cache_hash

        storage = (
            f"m:{actors['workspace_id']}:override:"
            f"{question_cache_hash(normalize_question(fail_question))}:{fail_key}"
        )
        owner = session.execute(
            text("SELECT owner_token FROM idempotency_keys WHERE idempotency_key = :k"),
            {"k": storage},
        ).scalar()
    finally:
        session.close()
    assert owner is None
    recovered = client.post(
        "/api/compliance/control-mappings/override",
        json={
            "question": fail_question,
            "control_ids": [control_id],
            "rationale": "synthetic failure",
        },
        headers={"Idempotency-Key": fail_key},
    )
    assert recovered.status_code == 200, recovered.text
    assert _table_count("control_mapping_override") == before_overrides + 1
    replay = client.post(
        "/api/compliance/control-mappings/override",
        json={
            "question": fail_question,
            "control_ids": [control_id],
            "rationale": "synthetic failure",
        },
        headers={"Idempotency-Key": fail_key},
    )
    assert replay.status_code == 200
    assert replay.json() == recovered.json()
    assert _table_count("control_mapping_override") == before_overrides + 1


def test_post_commit_store_failure_retries_without_a_second_version(client):
    actors = _actors()
    control_id = _control(actors["workspace_id"], f"Store {uuid.uuid4().hex[:8]}")
    question = f"synthetic store {uuid.uuid4().hex[:8]}"
    key = f"map-store-{uuid.uuid4().hex}"
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    before = _table_count("control_mapping_override")
    quiet = TestClient(
        app, base_url=TEST_ORIGIN, headers=TEST_HEADERS, raise_server_exceptions=False
    )
    _login(quiet, ADMIN_EMAIL, ADMIN_PASSWORD)

    def boom(*_args, **_kwargs):
        raise RuntimeError("forced store failure")

    with patch("app.api.routes.compliance_mappings.idempotency_set", side_effect=boom):
        first = quiet.post(
            "/api/compliance/control-mappings/confirm",
            json={"question": question, "control_ids": [control_id]},
            headers={"Idempotency-Key": key},
        )
    assert first.status_code == 200, first.text
    assert _table_count("control_mapping_override") == before + 1
    retried = client.post(
        "/api/compliance/control-mappings/confirm",
        json={"question": question, "control_ids": [control_id]},
        headers={"Idempotency-Key": key},
    )
    assert retried.status_code == 200, retried.text
    assert retried.status_code != 409
    assert retried.json() == first.json()
    assert _table_count("control_mapping_override") == before + 1


def test_rollback_notifies_without_a_real_send(client):
    actors = _actors()
    control_id = _control(actors["workspace_id"], f"Notify {uuid.uuid4().hex[:8]}")
    question = f"synthetic rollback notify {uuid.uuid4().hex[:8]}"
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    confirmed = client.post(
        "/api/compliance/control-mappings/confirm",
        json={"question": question, "control_ids": [control_id]},
    )
    assert confirmed.status_code == 200, confirmed.text
    before = _table_count("in_app_notifications")
    with (
        patch("app.api.routes.compliance_mappings.notify_admins") as notify,
        patch("app.api.routes.compliance_mappings.emit_compliance_event") as emit,
    ):
        rolled = client.post(
            "/api/compliance/control-mappings/rollback",
            json={"question": question},
        )
    assert rolled.status_code == 200, rolled.text
    assert notify.called
    assert notify.call_args.args[2] == "Mapping rolled back"
    assert emit.called
    assert _table_count("in_app_notifications") == before


def test_migrated_schema_matches_the_model():
    import importlib.util

    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import inspect

    from app.models.control_mapping_override import ControlMappingHistory, ControlMappingOverride

    path = os.path.join(API_ROOT, "alembic", "versions", "082_tc21005_mapping_version.py")
    spec = importlib.util.spec_from_file_location("tc21005_mig_schema", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    actors = _actors()
    orphan_id = 2_100_000_000 + (uuid.uuid4().int % 50_000_000)

    def apply() -> None:
        with engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                mod.upgrade()

    apply()
    session = _db()
    try:
        session.execute(
            text(
                "INSERT INTO tc21005_mapping_hold ("
                "id, mapping_id, version, workspace_id, question_hash, control_ids, state, "
                "rationale, reviewed_by_user_id, reviewed_at, recorded_at"
                ") VALUES ("
                ":id, :id, 1, :ws, 'orphan', CAST('[]' AS json), 'proposed', "
                "NULL, NULL, NULL, :recorded)"
            ),
            {
                "id": orphan_id,
                "ws": actors["workspace_id"],
                "recorded": datetime(2020, 1, 1, 0, 0, 0),
            },
        )
        session.commit()
    finally:
        session.close()
    apply()
    session = _db()
    try:
        assert (
            session.execute(
                text("SELECT count(*) FROM tc21005_mapping_history WHERE id = :id"),
                {"id": orphan_id},
            ).scalar()
            == 0
        )
        assert (
            session.execute(
                text("SELECT count(*) FROM tc21005_mapping_hold WHERE id = :id"),
                {"id": orphan_id},
            ).scalar()
            == 0
        )
    finally:
        session.close()
    inspected = inspect(engine)
    live_fk = next(
        fk
        for fk in inspected.get_foreign_keys("tc21005_mapping_history")
        if fk["constrained_columns"] == ["mapping_id"]
    )
    model_fk = next(iter(ControlMappingHistory.__table__.foreign_keys))
    assert live_fk["referred_table"] == model_fk.column.table.name
    assert live_fk["referred_columns"] == [model_fk.column.name]
    assert (live_fk.get("options") or {}).get("ondelete") == model_fk.ondelete == "CASCADE"
    history_indexes = {
        tuple(idx["column_names"]) for idx in inspected.get_indexes("tc21005_mapping_history")
    }
    override_indexes = {
        tuple(idx["column_names"]) for idx in inspected.get_indexes("control_mapping_override")
    }
    assert ("mapping_id",) in history_indexes
    assert ("reviewed_by_user_id",) in override_indexes
    assert any(
        tuple(col.name for col in idx.columns) == ("mapping_id",)
        for idx in ControlMappingHistory.__table__.indexes
    )
    assert any(
        tuple(col.name for col in idx.columns) == ("reviewed_by_user_id",)
        for idx in ControlMappingOverride.__table__.indexes
    )


def test_migration_round_trip_restores_mapping_history():
    import importlib.util

    before_counts = _counts()
    before_ids = _ids()
    actors = _actors()
    path = os.path.join(API_ROOT, "alembic", "versions", "082_tc21005_mapping_version.py")
    spec = importlib.util.spec_from_file_location("tc21005_mig", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == REVISION
    assert mod.down_revision == PARENT
    assert "app." not in open(path, encoding="utf-8").read()
    env = {**os.environ, "DATABASE_URL": os.environ["DATABASE_URL"]}
    override_id = None

    def alembic(*args):
        proc = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=API_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr[-2000:] + proc.stdout[-2000:]
        engine.dispose()
        return proc.stdout

    def wipe() -> None:
        session = _db()
        try:
            if override_id is not None:
                session.execute(
                    text("DELETE FROM tc21005_mapping_history WHERE mapping_id = :id"),
                    {"id": override_id},
                )
                session.execute(
                    text("DELETE FROM tc21005_mapping_hold WHERE mapping_id = :id"),
                    {"id": override_id},
                )
                session.execute(
                    text("DELETE FROM tc21005_mapping_attr_hold WHERE mapping_id = :id"),
                    {"id": override_id},
                )
                session.execute(
                    text("DELETE FROM control_mapping_override WHERE id = :id"),
                    {"id": override_id},
                )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    try:
        try:
            alembic("downgrade", PARENT)
            created_at = datetime(2020, 1, 2, 3, 4, 5)
            session = _db()
            try:
                inserted = session.execute(
                    text(
                        "INSERT INTO control_mapping_override "
                        "(workspace_id, question_hash, override_control_ids, created_at) "
                        "VALUES (:ws, :h, CAST(:ids AS json), :created) RETURNING id"
                    ),
                    {
                        "ws": actors["workspace_id"],
                        "h": uuid.uuid4().hex,
                        "ids": "[7, 8]",
                        "created": created_at,
                    },
                ).scalar()
                session.commit()
                override_id = inserted
                original = session.execute(
                    text(
                        "SELECT id, workspace_id, question_hash, override_control_ids, created_at "
                        "FROM control_mapping_override WHERE id = :id"
                    ),
                    {"id": override_id},
                ).one()
            finally:
                session.close()
            original_tuple = (
                original.id,
                original.workspace_id,
                original.question_hash,
                original.override_control_ids,
                original.created_at,
            )
            alembic("upgrade", REVISION)
            session = _db()
            try:
                upgraded = session.execute(
                    text(
                        "SELECT id, workspace_id, question_hash, override_control_ids, created_at, "
                        "state, version, reviewed_at FROM control_mapping_override WHERE id = :id"
                    ),
                    {"id": override_id},
                ).one()
                assert (
                    upgraded.id,
                    upgraded.workspace_id,
                    upgraded.question_hash,
                    upgraded.override_control_ids,
                    upgraded.created_at,
                ) == original_tuple
                assert upgraded.state == "overridden"
                assert upgraded.version == 1
                assert upgraded.reviewed_at == upgraded.created_at
                kept_review = datetime(2022, 3, 4, 5, 6, 7)
                session.execute(
                    text(
                        "UPDATE control_mapping_override SET state = 'confirmed', "
                        "rationale = 'synthetic kept rationale', version = 3, "
                        "reviewed_by_user_id = :user, reviewed_at = :reviewed WHERE id = :id"
                    ),
                    {"user": actors["admin_id"], "reviewed": kept_review, "id": override_id},
                )
                recorded = datetime(2021, 6, 7, 8, 9, 10)
                session.execute(
                    text(
                        "INSERT INTO tc21005_mapping_history ("
                        "mapping_id, version, workspace_id, question_hash, control_ids, state, "
                        "rationale, reviewed_by_user_id, reviewed_at, recorded_at"
                        ") VALUES "
                        "(:mapping, 1, :ws, :h, CAST(:ids AS json), 'proposed', "
                        "NULL, NULL, NULL, :recorded), "
                        "(:mapping, 2, :ws, :h, CAST('[7]' AS json), 'confirmed', "
                        "'synthetic history rationale', :user, :hist_reviewed, :recorded)"
                    ),
                    {
                        "mapping": override_id,
                        "ws": actors["workspace_id"],
                        "h": original.question_hash,
                        "ids": "[7]",
                        "user": actors["admin_id"],
                        "hist_reviewed": datetime(2021, 6, 7, 8, 0, 0),
                        "recorded": recorded,
                    },
                )
                session.commit()
                seeded_mapping = session.execute(
                    text(
                        "SELECT id, workspace_id, question_hash, override_control_ids, created_at, "
                        "state, rationale, version, reviewed_by_user_id, reviewed_at "
                        "FROM control_mapping_override WHERE id = :id"
                    ),
                    {"id": override_id},
                ).one()
                seeded_history = session.execute(
                    text(
                        "SELECT id, mapping_id, version, workspace_id, question_hash, control_ids, "
                        "state, rationale, reviewed_by_user_id, reviewed_at, recorded_at "
                        "FROM tc21005_mapping_history WHERE mapping_id = :id ORDER BY id"
                    ),
                    {"id": override_id},
                ).fetchall()
                seeded_mapping_tuple = tuple(seeded_mapping)
                seeded_history_tuples = [tuple(row) for row in seeded_history]
            finally:
                session.close()
            alembic("downgrade", PARENT)
            session = _db()
            try:
                restored = session.execute(
                    text(
                        "SELECT id, workspace_id, question_hash, override_control_ids, created_at "
                        "FROM control_mapping_override WHERE id = :id"
                    ),
                    {"id": override_id},
                ).one()
                assert tuple(restored) == original_tuple
                assert (
                    session.execute(
                        text("SELECT to_regclass('public.tc21005_mapping_history')")
                    ).scalar()
                    is None
                )
                held = session.execute(
                    text(
                        "SELECT id, mapping_id, version, workspace_id, question_hash, control_ids, "
                        "state, rationale, reviewed_by_user_id, reviewed_at, recorded_at "
                        "FROM tc21005_mapping_hold WHERE mapping_id = :id ORDER BY id"
                    ),
                    {"id": override_id},
                ).fetchall()
                assert [tuple(row) for row in held] == seeded_history_tuples
                parked = session.execute(
                    text(
                        "SELECT mapping_id, state, rationale, version, reviewed_by_user_id, "
                        "reviewed_at FROM tc21005_mapping_attr_hold WHERE mapping_id = :id"
                    ),
                    {"id": override_id},
                ).one()
                assert parked.state == "confirmed"
                assert parked.rationale == "synthetic kept rationale"
                assert parked.version == 3
                assert parked.reviewed_by_user_id == actors["admin_id"]
            finally:
                session.close()
            alembic("upgrade", REVISION)
            session = _db()
            try:
                again = session.execute(
                    text(
                        "SELECT id, workspace_id, question_hash, override_control_ids, created_at, "
                        "state, rationale, version, reviewed_by_user_id, reviewed_at "
                        "FROM control_mapping_override WHERE id = :id"
                    ),
                    {"id": override_id},
                ).one()
                assert tuple(again) == seeded_mapping_tuple
                revived = session.execute(
                    text(
                        "SELECT id, mapping_id, version, workspace_id, question_hash, control_ids, "
                        "state, rationale, reviewed_by_user_id, reviewed_at, recorded_at "
                        "FROM tc21005_mapping_history WHERE mapping_id = :id ORDER BY id"
                    ),
                    {"id": override_id},
                ).fetchall()
                assert [tuple(row) for row in revived] == seeded_history_tuples
                assert (
                    session.execute(
                        text("SELECT count(*) FROM tc21005_mapping_hold WHERE mapping_id = :id"),
                        {"id": override_id},
                    ).scalar()
                    == 0
                )
            finally:
                session.close()
            heads = [line.strip() for line in alembic("heads").splitlines() if "(head)" in line]
            assert len(heads) == 1
            from tests.release.test_billing_provider import _revision_is_applied, _revision_token

            assert _revision_is_applied(_revision_token(alembic("heads")), REVISION)
        finally:
            alembic("upgrade", "head")
            wipe()
            _delete_created(before_ids, skip=("tc21005_mapping_hold", "tc21005_mapping_history"))
    finally:
        after_counts = _counts()
        assert after_counts == before_counts, {"before": before_counts, "after": after_counts}
        print(f"TC21005_COUNTS before={before_counts} after={after_counts}")
