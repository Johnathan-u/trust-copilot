"""Persisted compliance alerts.

Runs on PostgreSQL. Labels are synthetic, not framework text.
"""

import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.api.routes import compliance_alerts as alerts_mod
from app.core.database import SessionLocal
from app.core.password import hash_password
from app.models import (
    EvidenceGap,
    Questionnaire,
    User,
    Workspace,
    WorkspaceControl,
    WorkspaceMember,
)
from app.models.evidence_gap import CONTROL_CHECK
from app.models.questionnaire import Question

API_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
PARENT = "tc02001a_parent_ws_move"
REVISION = "tc21008_alert_records"
SLUG = "tc21008"
ADMIN_EMAIL = "tc21008-admin@trust.local"
EDITOR_EMAIL = "tc21008-editor@trust.local"
REVIEWER_EMAIL = "tc21008-reviewer@trust.local"
OTHER_EMAIL = "tc21008-other@trust.local"
ADMIN_PASSWORD = "test-a"
EDITOR_PASSWORD = "test-e"
REVIEWER_PASSWORD = "test-r"
OTHER_PASSWORD = "test-o"
_COUNTED = (
    "compliance_alerts",
    "evidence_gaps",
    "answers",
    "questions",
    "questionnaires",
    "workspace_controls",
    "idempotency_keys",
    "audit_events",
    "user_sessions",
    "workspace_members",
    "users",
    "workspaces",
)


def _db() -> Session:
    return SessionLocal()


def _revision_reaches_every_head(revision: str) -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(os.path.join(API_ROOT, "alembic.ini")))
    heads = script.get_heads()
    assert heads

    def reaches(current: str | None, seen: set[str] | None = None) -> bool:
        walked: set[str] = set() if seen is None else seen
        if current is None or current in walked:
            return False
        if current == revision:
            return True
        walked.add(current)
        script_rev = script.get_revision(current)
        parents = script_rev.down_revision
        if parents is None:
            return False
        if isinstance(parents, str):
            parents = (parents,)
        return any(reaches(parent, walked) for parent in parents)

    assert all(reaches(head) for head in heads)


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


def _delete_created(before: dict[str, set[int]]) -> None:
    session = _db()
    try:
        for name in _COUNTED:
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
    if request.node.originalname == "test_migration_round_trip_restores_alert_records":
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


def _actors() -> dict[str, int]:
    session = _db()
    try:
        workspace = session.query(Workspace).filter(Workspace.slug == SLUG).one_or_none()
        if workspace is None:
            _sync_sequence(session, "workspaces")
            workspace = Workspace(name="Synthetic alerts", slug=SLUG)
            session.add(workspace)
            session.flush()
        other = session.query(Workspace).filter(Workspace.slug == SLUG + "-other").one_or_none()
        if other is None:
            _sync_sequence(session, "workspaces")
            other = Workspace(name="Synthetic alerts other", slug=SLUG + "-other")
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
        member(EDITOR_EMAIL, EDITOR_PASSWORD, "editor", workspace)
        reviewer = member(REVIEWER_EMAIL, REVIEWER_PASSWORD, "reviewer", workspace)
        member(OTHER_EMAIL, OTHER_PASSWORD, "admin", other)
        session.commit()
        return {
            "workspace_id": workspace.id,
            "other_workspace_id": other.id,
            "admin_id": admin.id,
            "reviewer_id": reviewer.id,
        }
    finally:
        session.close()


def _login(client, email: str, password: str) -> None:
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def _questions(workspace_id: int) -> None:
    session = _db()
    try:
        _sync_sequence(session, "questionnaires")
        questionnaire = Questionnaire(
            workspace_id=workspace_id,
            filename=f"synthetic-{uuid.uuid4().hex}.txt",
            status="uploaded",
        )
        session.add(questionnaire)
        session.flush()
        _sync_sequence(session, "questions")
        session.add(Question(questionnaire_id=questionnaire.id, text="Synthetic question one"))
        session.add(Question(questionnaire_id=questionnaire.id, text="Synthetic question two"))
        session.commit()
    finally:
        session.close()


def _control_gap(workspace_id: int, version: str) -> int:
    session = _db()
    try:
        _sync_sequence(session, "workspace_controls")
        control = WorkspaceControl(
            workspace_id=workspace_id,
            status="not_implemented",
            custom_name="Synthetic control",
            content_version=version,
        )
        session.add(control)
        session.flush()
        _sync_sequence(session, "evidence_gaps")
        session.add(
            EvidenceGap(
                workspace_id=workspace_id,
                gap_type=CONTROL_CHECK,
                status="open",
                control_id=control.id,
                evaluation_state="gap",
                rule_code="missing_evidence",
            )
        )
        session.commit()
        return control.id
    finally:
        session.close()


def _scan(client, key: str = "scan-1"):
    return client.post(
        "/api/compliance-alerts/scan",
        json={},
        headers={"Idempotency-Key": key},
    )


def _alert_rows(workspace_id: int) -> list:
    session = _db()
    try:
        return session.execute(
            text(
                "SELECT id, condition, source_ref, source_revision, control_id, "
                "control_revision, status FROM compliance_alerts "
                "WHERE workspace_id = :ws ORDER BY id"
            ),
            {"ws": workspace_id},
        ).fetchall()
    finally:
        session.close()


def test_get_is_read_only_until_a_scan_persists_one_alert(client):
    actors = _actors()
    _questions(actors["workspace_id"])
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    before = _counts()["compliance_alerts"]
    listed = client.get("/api/compliance-alerts/active")
    assert listed.status_code == 200, listed.text
    assert listed.json()["schema_version"] == alerts_mod.SCHEMA_VERSION
    assert listed.json()["alerts"] == []
    assert _counts()["compliance_alerts"] == before

    scanned = _scan(client)
    assert scanned.status_code == 200, scanned.text
    body = scanned.json()
    assert body["partial"] is False
    assert len(body["alerts"]) == 1
    alert = body["alerts"][0]
    assert alert["condition"] == "coverage_drop"
    assert alert["type"] == "coverage_drop"
    assert alert["status"] == "active"
    assert alert["source_ref"] == "coverage"
    assert alert["source_revision"]
    assert alert["control_id"] is None
    assert alert["control_revision"] is None
    stored = _alert_rows(actors["workspace_id"])
    assert len(stored) == 1
    assert stored[0].source_revision == alert["source_revision"]

    session = _db()
    try:
        updated_at = session.execute(
            text("SELECT updated_at FROM compliance_alerts WHERE id = :id"),
            {"id": alert["id"]},
        ).scalar()
    finally:
        session.close()
    again = client.get("/api/compliance-alerts/active")
    assert again.status_code == 200
    assert again.json()["alerts"][0]["id"] == alert["id"]
    session = _db()
    try:
        assert (
            session.execute(
                text("SELECT updated_at FROM compliance_alerts WHERE id = :id"),
                {"id": alert["id"]},
            ).scalar()
            == updated_at
        )
    finally:
        session.close()

    retried = _scan(client, "scan-2")
    assert retried.status_code == 200, retried.text
    assert retried.json()["alerts"][0]["id"] == alert["id"]
    assert len(_alert_rows(actors["workspace_id"])) == 1
    replay = _scan(client, "scan-2")
    assert replay.status_code == 200
    assert replay.json()["alerts"][0]["id"] == alert["id"]
    assert len(_alert_rows(actors["workspace_id"])) == 1


def test_control_revision_updates_in_place_and_lifecycle_does_not_duplicate(client):
    actors = _actors()
    _questions(actors["workspace_id"])
    control_id = _control_gap(actors["workspace_id"], "rev-1")
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    scanned = _scan(client, "life-1")
    assert scanned.status_code == 200, scanned.text
    by_condition = {item["condition"]: item for item in scanned.json()["alerts"]}
    assert set(by_condition) == {"coverage_drop", "control_gap"}
    control_alert = by_condition["control_gap"]
    assert control_alert["control_id"] == control_id
    assert control_alert["control_revision"] == "rev-1"
    assert control_alert["source_revision"] == "rev-1"

    session = _db()
    try:
        session.execute(
            text("UPDATE workspace_controls SET content_version = 'rev-2' WHERE id = :id"),
            {"id": control_id},
        )
        session.commit()
    finally:
        session.close()
    rescanned = _scan(client, "life-2")
    assert rescanned.status_code == 200, rescanned.text
    again = {item["condition"]: item for item in rescanned.json()["alerts"]}
    assert again["control_gap"]["id"] == control_alert["id"]
    assert again["control_gap"]["control_revision"] == "rev-2"
    assert len(_alert_rows(actors["workspace_id"])) == 2

    _login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    denied = client.get("/api/compliance-alerts/active")
    assert denied.status_code == 403
    acknowledged = client.post(
        f"/api/compliance-alerts/{control_alert['id']}/acknowledge",
        json={"reason": "seen"},
        headers={"Idempotency-Key": "ack-1"},
    )
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["alert"]["status"] == "acknowledged"
    replay = client.post(
        f"/api/compliance-alerts/{control_alert['id']}/acknowledge",
        json={"reason": "seen"},
        headers={"Idempotency-Key": "ack-1"},
    )
    assert replay.status_code == 200
    assert replay.json()["alert"]["id"] == control_alert["id"]
    changed = client.post(
        f"/api/compliance-alerts/{control_alert['id']}/acknowledge",
        json={"reason": "other"},
        headers={"Idempotency-Key": "ack-1"},
    )
    assert changed.status_code == 422
    session = _db()
    try:
        audits = session.execute(
            text(
                "SELECT count(*) FROM audit_events "
                "WHERE action = 'alert_acknowledged' AND resource_id = :id AND user_id = :user"
            ),
            {"id": str(control_alert["id"]), "user": actors["reviewer_id"]},
        ).scalar()
    finally:
        session.close()
    assert audits == 1

    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    kept = _scan(client, "life-3")
    assert kept.status_code == 200, kept.text
    assert len(_alert_rows(actors["workspace_id"])) == 2
    assert all(
        row.status != "active" or row.condition != "control_gap"
        for row in _alert_rows(actors["workspace_id"])
    )
    visible = client.get("/api/compliance-alerts/active")
    assert [item["condition"] for item in visible.json()["alerts"]] == ["coverage_drop"]

    coverage_id = by_condition["coverage_drop"]["id"]
    snoozed = client.post(
        f"/api/compliance-alerts/{coverage_id}/snooze",
        json={
            "until": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            "reason": "later",
        },
        headers={"Idempotency-Key": "snooze-1"},
    )
    assert snoozed.status_code == 200, snoozed.text
    hidden = client.get("/api/compliance-alerts/active")
    assert hidden.json()["alerts"] == []

    resolved = client.post(
        f"/api/compliance-alerts/{coverage_id}/resolve",
        json={},
        headers={"Idempotency-Key": "resolve-1"},
    )
    assert resolved.status_code == 200, resolved.text
    reopened = _scan(client, "life-4")
    assert reopened.status_code == 200, reopened.text
    rows = _alert_rows(actors["workspace_id"])
    coverage_rows = [row for row in rows if row.condition == "coverage_drop"]
    assert len(coverage_rows) == 2
    assert sum(row.status == "active" for row in coverage_rows) == 1
    assert sum(row.status == "resolved" for row in coverage_rows) == 1


def test_permissions_foreign_ids_and_bad_input(client):
    actors = _actors()
    _questions(actors["workspace_id"])
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    scanned = _scan(client, "perm-scan")
    alert_id = scanned.json()["alerts"][0]["id"]

    client.cookies.clear()
    assert client.get("/api/compliance-alerts/active").status_code == 401
    _login(client, EDITOR_EMAIL, EDITOR_PASSWORD)
    assert client.get("/api/compliance-alerts/active").status_code == 403
    assert _scan(client, "editor-scan").status_code == 403
    _login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    assert (
        client.post(
            "/api/compliance-alerts/scan", json={}, headers={"Idempotency-Key": "r"}
        ).status_code
        == 403
    )
    missing = client.post(
        "/api/compliance-alerts/999999991/acknowledge",
        json={},
        headers={"Idempotency-Key": "missing"},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Alert not found"
    nul = client.post(
        f"/api/compliance-alerts/{alert_id}/acknowledge",
        json={"reason": "bad\x00text"},
        headers={"Idempotency-Key": "nul"},
    )
    assert nul.status_code == 422
    snooze = client.post(
        f"/api/compliance-alerts/{alert_id}/snooze",
        json={"reason": "later"},
        headers={"Idempotency-Key": "no-until"},
    )
    assert snooze.status_code == 422

    _login(client, OTHER_EMAIL, OTHER_PASSWORD)
    foreign = client.post(
        f"/api/compliance-alerts/{alert_id}/acknowledge",
        json={},
        headers={"Idempotency-Key": "foreign"},
    )
    assert foreign.status_code == 404
    assert foreign.json()["detail"] == missing.json()["detail"]
    assert len(_alert_rows(actors["workspace_id"])) == 1
    assert _alert_rows(actors["workspace_id"])[0].status == "active"


def test_partial_publish_failure_keeps_the_saved_alert(client):
    actors = _actors()
    _questions(actors["workspace_id"])
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    from unittest.mock import patch

    with patch("app.api.routes.compliance_alerts._publish_scan", side_effect=RuntimeError("down")):
        scanned = _scan(client, "partial-1")
    assert scanned.status_code == 200, scanned.text
    assert scanned.json()["partial"] is True
    assert scanned.json()["reason"] == "publish_failed"
    assert len(scanned.json()["alerts"]) == 1
    listed = client.get("/api/compliance-alerts/active")
    assert listed.json()["alerts"][0]["id"] == scanned.json()["alerts"][0]["id"]


def test_conflicting_insert_updates_the_active_row(client):
    actors = _actors()
    _questions(actors["workspace_id"])
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    first = _scan(client, "conflict-1")
    assert first.status_code == 200, first.text
    alert_id = first.json()["alerts"][0]["id"]
    from unittest.mock import patch

    with patch("app.api.routes.compliance_alerts._open_episode", return_value=None):
        second = _scan(client, "conflict-2")
    assert second.status_code == 200, second.text
    assert second.json()["alerts"][0]["id"] == alert_id
    assert len(_alert_rows(actors["workspace_id"])) == 1


def test_concurrent_scans_leave_one_active_alert(client):
    import threading

    from fastapi.testclient import TestClient
    from unittest.mock import patch

    from app.main import app
    from tests.conftest import TEST_HEADERS, TEST_ORIGIN

    actors = _actors()
    _questions(actors["workspace_id"])
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    token = client.cookies.get("tc_session")
    holding = threading.Event()
    release = threading.Event()
    codes: list[int] = []
    real_lock = alerts_mod._lock_alert_writes

    def lock_and_hold(db, workspace_id: int) -> None:
        real_lock(db, workspace_id)
        if workspace_id == actors["workspace_id"] and not holding.is_set():
            holding.set()
            assert release.wait(timeout=8), "scan was not released"

    def call(key: str) -> None:
        local = TestClient(app, base_url=TEST_ORIGIN, headers=TEST_HEADERS)
        local.cookies.set("tc_session", token)
        response = local.post(
            "/api/compliance-alerts/scan",
            json={},
            headers={"Idempotency-Key": key},
        )
        codes.append(response.status_code)

    first = threading.Thread(target=call, args=("race-1",))
    second = threading.Thread(target=call, args=("race-2",))
    try:
        with patch(
            "app.api.routes.compliance_alerts._lock_alert_writes", side_effect=lock_and_hold
        ):
            first.start()
            assert holding.wait(timeout=8), "scan never took the alert lock"
            second.start()
            assert _wait_for_lock(), "second scan did not wait on the alert lock"
    finally:
        release.set()
        for thread in (first, second):
            if thread.ident is not None:
                thread.join(timeout=10)
    for thread in (first, second):
        assert not thread.is_alive()
    assert sorted(codes) == [200, 200], codes
    rows = _alert_rows(actors["workspace_id"])
    assert len(rows) == 1
    assert rows[0].status == "active"


def _wait_for_lock(timeout: float = 5.0) -> bool:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        if _lock_wait_visible():
            return True
        time.sleep(0.05)
    return False


def _lock_wait_visible() -> bool:
    session = _db()
    try:
        row = session.execute(
            text(
                """
                SELECT 1
                FROM pg_stat_activity
                WHERE pid <> pg_backend_pid()
                  AND datname = current_database()
                  AND wait_event_type = 'Lock'
                  AND wait_event IN ('advisory', 'transactionid', 'tuple')
                UNION ALL
                SELECT 1
                FROM pg_locks
                WHERE NOT granted
                  AND locktype IN ('advisory', 'transactionid', 'tuple')
                  AND pid IN (
                    SELECT pid FROM pg_stat_activity WHERE datname = current_database()
                  )
                LIMIT 1
                """
            )
        ).first()
        return row is not None
    finally:
        session.close()


def test_migration_round_trip_restores_alert_records():
    assert len(REVISION) <= 32
    assert REVISION == "tc21008_alert_records"
    before_counts = _counts()
    before_ids = _ids()
    actors = _actors()
    seeded_ids: list[int] = []
    seeded_rows: list[tuple] = []
    moment = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    def alembic(*args):
        proc = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=API_ROOT,
            env={**os.environ, "DATABASE_URL": os.environ["DATABASE_URL"]},
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr or proc.stdout
        return proc.stdout

    def cleanup() -> None:
        session = _db()
        try:
            if (
                seeded_ids
                and session.execute(text("SELECT to_regclass('public.compliance_alerts')")).scalar()
            ):
                session.execute(
                    text("DELETE FROM compliance_alerts WHERE id IN :ids").bindparams(
                        bindparam("ids", expanding=True)
                    ),
                    {"ids": seeded_ids},
                )
            if (
                seeded_ids
                and session.execute(
                    text("SELECT to_regclass('public.tc21008_alert_hold')")
                ).scalar()
            ):
                session.execute(
                    text("DELETE FROM tc21008_alert_hold WHERE id IN :ids").bindparams(
                        bindparam("ids", expanding=True)
                    ),
                    {"ids": seeded_ids},
                )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    try:
        alembic("upgrade", REVISION)
        session = _db()
        try:
            for source_ref, metric in (("coverage", 12.5), ("subject:synthetic", 4.0)):
                alert_id = session.execute(
                    text(
                        "INSERT INTO compliance_alerts ("
                        "workspace_id, condition, source_ref, source_revision, control_id, "
                        "control_revision, status, severity, title, description, metric, "
                        "created_at, updated_at"
                        ") VALUES ("
                        ":ws, 'coverage_drop', :source, 'rev', NULL, 'rev-1', 'active', "
                        "'high', 'Low coverage', 'Synthetic coverage is low.', :metric, :now, :now"
                        ") RETURNING id"
                    ),
                    {
                        "ws": actors["workspace_id"],
                        "source": source_ref,
                        "metric": metric,
                        "now": moment,
                    },
                ).scalar()
                seeded_ids.append(int(alert_id))
            session.commit()
            seeded_rows = [
                tuple(row)
                for row in session.execute(
                    text(
                        "SELECT id, workspace_id, condition, source_ref, source_revision, "
                        "control_revision, status, severity, title, description, metric "
                        "FROM compliance_alerts WHERE id IN :ids ORDER BY id"
                    ).bindparams(bindparam("ids", expanding=True)),
                    {"ids": seeded_ids},
                ).fetchall()
            ]
            assert len(seeded_rows) == 2
        finally:
            session.close()
        alembic("downgrade", PARENT)
        session = _db()
        try:
            assert (
                session.execute(text("SELECT to_regclass('public.compliance_alerts')")).scalar()
                is None
            )
            parked = session.execute(
                text("SELECT count(*) FROM tc21008_alert_hold WHERE id IN :ids").bindparams(
                    bindparam("ids", expanding=True)
                ),
                {"ids": seeded_ids},
            ).scalar()
            assert parked == 2
        finally:
            session.close()
        alembic("upgrade", REVISION)
        session = _db()
        try:
            restored = [
                tuple(row)
                for row in session.execute(
                    text(
                        "SELECT id, workspace_id, condition, source_ref, source_revision, "
                        "control_revision, status, severity, title, description, metric "
                        "FROM compliance_alerts WHERE id IN :ids ORDER BY id"
                    ).bindparams(bindparam("ids", expanding=True)),
                    {"ids": seeded_ids},
                ).fetchall()
            ]
            assert len(restored) == 2
            assert restored == seeded_rows
            hold_left = session.execute(
                text("SELECT count(*) FROM tc21008_alert_hold WHERE id IN :ids").bindparams(
                    bindparam("ids", expanding=True)
                ),
                {"ids": seeded_ids},
            ).scalar()
            assert hold_left == 0
        finally:
            session.close()
        _revision_reaches_every_head(REVISION)
    finally:
        alembic("upgrade", "head")
        cleanup()
        _delete_created(before_ids)
        after_counts = _counts()
        assert after_counts == before_counts, {"before": before_counts, "after": after_counts}
