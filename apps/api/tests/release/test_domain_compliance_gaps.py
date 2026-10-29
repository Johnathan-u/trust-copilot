"""TC-21-006 explainable compliance gaps.

Runs on PostgreSQL. Labels are synthetic, not framework text.
Notification delivery is stubbed. Nothing is sent.
"""

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.api.routes import compliance_gaps as gaps_mod
from app.core.database import SessionLocal, engine
from app.core.password import hash_password
from app.models import (
    ControlEvidenceLink,
    Document,
    EvidenceItem,
    EvidenceMetadata,
    User,
    Workspace,
    WorkspaceControl,
    WorkspaceMember,
)
API_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
PARENT = "bug018a_gap_closed_at_reason"
REVISION = "tc21006_gap_evaluation"
SLUG = "tc21006"
ADMIN_EMAIL = "tc21006-admin@trust.local"
EDITOR_EMAIL = "tc21006-editor@trust.local"
REVIEWER_EMAIL = "tc21006-reviewer@trust.local"
OTHER_EMAIL = "tc21006-other@trust.local"
ADMIN_PASSWORD = "test-a"
EDITOR_PASSWORD = "test-e"
REVIEWER_PASSWORD = "test-r"
OTHER_PASSWORD = "test-o"
_COUNTED = (
    "tc21006_gap_eval_hold",
    "evidence_gaps",
    "control_evidence_links",
    "evidence_metadata",
    "evidence_items",
    "documents",
    "workspace_controls",
    "in_app_notifications",
    "idempotency_keys",
    "audit_events",
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
    if request.node.originalname == "test_migration_round_trip_restores_gap_evaluation":
        yield
        return
    _reset_login_limit()
    gaps_mod._last_gap_notify.clear()
    before_counts = _counts()
    before_ids = _ids()
    try:
        yield
    finally:
        gaps_mod._last_gap_notify.clear()
        _delete_created(before_ids)
        after_counts = _counts()
        assert after_counts == before_counts, {"before": before_counts, "after": after_counts}
        print(f"TC21006_COUNTS before={before_counts} after={after_counts}")


def _actors() -> dict[str, int]:
    session = _db()
    try:
        workspace = session.query(Workspace).filter(Workspace.slug == SLUG).one_or_none()
        if workspace is None:
            _sync_sequence(session, "workspaces")
            workspace = Workspace(name="TC-21-006", slug=SLUG)
            session.add(workspace)
            session.flush()
        other = session.query(Workspace).filter(Workspace.slug == SLUG + "-other").one_or_none()
        if other is None:
            _sync_sequence(session, "workspaces")
            other = Workspace(name="TC-21-006 other", slug=SLUG + "-other")
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
        member(REVIEWER_EMAIL, REVIEWER_PASSWORD, "reviewer", workspace)
        member(OTHER_EMAIL, OTHER_PASSWORD, "admin", other)
        session.commit()
        return {
            "workspace_id": workspace.id,
            "other_workspace_id": other.id,
            "admin_id": admin.id,
        }
    finally:
        session.close()


def _login(client, email: str, password: str) -> None:
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def _control(workspace_id: int, name: str, owner_user_id: int | None = None) -> int:
    session = _db()
    try:
        _sync_sequence(session, "workspace_controls")
        row = WorkspaceControl(
            workspace_id=workspace_id,
            status="not_implemented",
            custom_name=name,
            owner_user_id=owner_user_id,
        )
        session.add(row)
        session.commit()
        return row.id
    finally:
        session.close()


def _evidence(workspace_id: int, *, approval: str, document_deleted: bool = False) -> int:
    session = _db()
    try:
        _sync_sequence(session, "documents")
        doc = Document(
            workspace_id=workspace_id,
            storage_key=f"tc21006/{uuid.uuid4().hex}",
            filename="synthetic.txt",
            status="uploaded",
            deleted_at=datetime.utcnow() if document_deleted else None,
        )
        session.add(doc)
        session.flush()
        _sync_sequence(session, "evidence_items")
        row = EvidenceItem(
            workspace_id=workspace_id,
            document_id=doc.id,
            source_type="document",
            title="Synthetic evidence",
            approval_status=approval,
        )
        session.add(row)
        session.commit()
        return row.id
    finally:
        session.close()


def _link(control_id: int, evidence_id: int) -> None:
    session = _db()
    try:
        session.add(
            ControlEvidenceLink(control_id=control_id, evidence_id=evidence_id, verified=False)
        )
        session.commit()
    finally:
        session.close()


def _gap_for(client, control_id: int) -> dict | None:
    response = client.get("/api/compliance/gaps", params={"control_id": control_id})
    assert response.status_code == 200, response.text
    hits = [item for item in response.json()["gaps"] if item["control_id"] == control_id]
    return hits[0] if hits else None


def test_denial_at_each_permission_level(client):
    _actors()
    client.cookies.clear()
    assert client.get("/api/compliance/gaps").status_code == 401
    assert client.post("/api/compliance/gaps/scan-and-notify").status_code == 401
    for role, email, password, get_code, post_code in (
        ("reviewer", REVIEWER_EMAIL, REVIEWER_PASSWORD, 200, 403),
        ("editor", EDITOR_EMAIL, EDITOR_PASSWORD, 200, 403),
        ("admin", ADMIN_EMAIL, ADMIN_PASSWORD, 200, 200),
    ):
        _login(client, email, password)
        before = _counts()
        listed = client.get("/api/compliance/gaps")
        assert listed.status_code == get_code, (role, listed.text)
        assert _counts() == before
        with patch("app.api.routes.compliance_gaps.notify_admins") as notify:
            scanned = client.post("/api/compliance/gaps/scan-and-notify")
        assert scanned.status_code == post_code, (role, scanned.text)
        if post_code == 403:
            assert scanned.json()["detail"] == "Insufficient permissions"
        else:
            assert notify.called or scanned.json()["gaps"] == 0


def test_missing_and_foreign_control_ids_share_the_404(client):
    actors = _actors()
    foreign = _control(actors["other_workspace_id"], f"Foreign {uuid.uuid4().hex[:8]}")
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    missing = client.get("/api/compliance/gaps", params={"control_id": 999999991})
    other = client.get("/api/compliance/gaps", params={"control_id": foreign})
    assert missing.status_code == 404
    assert missing.json() == other.json()
    assert missing.json() == {"detail": "Control not found"}


def test_rules_owner_and_states(client):
    actors = _actors()
    bare = _control(actors["workspace_id"], f"Bare {uuid.uuid4().hex[:8]}")
    owned = _control(
        actors["workspace_id"], f"Owned {uuid.uuid4().hex[:8]}", owner_user_id=actors["admin_id"]
    )
    pending_control = _control(actors["workspace_id"], f"Pending {uuid.uuid4().hex[:8]}")
    pending = _evidence(actors["workspace_id"], approval="pending")
    _link(pending_control, pending)
    clear_control = _control(actors["workspace_id"], f"Clear {uuid.uuid4().hex[:8]}")
    approved = _evidence(actors["workspace_id"], approval="approved")
    _link(clear_control, approved)
    stale_control = _control(actors["workspace_id"], f"Stale {uuid.uuid4().hex[:8]}")
    stale_evidence = _evidence(actors["workspace_id"], approval="approved")
    _link(stale_control, stale_evidence)
    session = _db()
    try:
        session.add(
            EvidenceMetadata(
                evidence_id=stale_evidence, expires_at=datetime.utcnow() - timedelta(days=1)
            )
        )
        session.commit()
    finally:
        session.close()
    unknown_control = _control(actors["workspace_id"], f"Unknown {uuid.uuid4().hex[:8]}")
    session = _db()
    try:
        session.execute(text("SET session_replication_role = replica"))
        session.execute(
            text(
                "INSERT INTO control_evidence_links "
                "(control_id, evidence_id, verified, created_at) "
                "VALUES (:c, 999999992, false, NOW())"
            ),
            {"c": unknown_control},
        )
        session.execute(text("SET session_replication_role = DEFAULT"))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    _login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    before = _counts()
    bare_gap = _gap_for(client, bare)
    assert _counts() == before
    assert bare_gap["state"] == "gap"
    assert bare_gap["rule"] == "no_evidence"
    assert bare_gap["reason"]["control_id"] == bare
    assert bare_gap["reason"]["evidence_ids"] == []
    assert bare_gap["next_step"]["owner_user_id"] is None
    assert bare_gap["next_step"]["owner_missing"] is True
    assert bare_gap["next_step"]["action"] == "collect_evidence"
    owned_gap = _gap_for(client, owned)
    assert owned_gap["next_step"]["owner_user_id"] == actors["admin_id"]
    assert owned_gap["next_step"]["owner_missing"] is False
    pending_gap = _gap_for(client, pending_control)
    assert pending_gap["state"] == "gap"
    assert pending_gap["rule"] == "not_approved"
    assert pending_gap["evidence_ids"] == [pending]
    assert _gap_for(client, clear_control) is None
    stale_gap = _gap_for(client, stale_control)
    assert stale_gap["state"] == "stale"
    assert stale_gap["rule"] == "expired"
    unknown_gap = _gap_for(client, unknown_control)
    assert unknown_gap["state"] == "unknown"
    assert unknown_gap["rule"] == "missing_evidence_row"
    with patch(
        "app.api.routes.compliance_gaps._scope", side_effect=RuntimeError("forced check failure")
    ):
        failed = client.get("/api/compliance/gaps", params={"control_id": bare})
    assert failed.status_code == 200, failed.text
    assert failed.json()["gaps"][0]["state"] == "failed"
    assert failed.json()["gaps"][0]["rule"] == "check_error"


def test_scan_persists_and_retry_does_not_duplicate_notifications(client):
    actors = _actors()
    control_id = _control(actors["workspace_id"], f"Scan {uuid.uuid4().hex[:8]}")
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    key = f"gap-{uuid.uuid4().hex}"
    before_gaps = _counts()["evidence_gaps"]
    before_notes = _counts()["in_app_notifications"]
    with patch(
        "app.api.routes.compliance_gaps.notify_admins", side_effect=RuntimeError("delivery failed")
    ):
        failed = client.post(
            "/api/compliance/gaps/scan-and-notify",
            headers={"Idempotency-Key": key},
        )
    assert failed.status_code == 200, failed.text
    assert failed.json()["notification_error"] == "delivery_failed"
    assert failed.json()["notified"] is False
    assert _counts()["evidence_gaps"] == before_gaps + 1
    assert _counts()["in_app_notifications"] == before_notes
    session = _db()
    try:
        stored = session.execute(
            text(
                "SELECT evaluation_state, rule_code, control_id, owner_user_id, next_action "
                "FROM evidence_gaps WHERE control_id = :id AND gap_type = 'control_check'"
            ),
            {"id": control_id},
        ).one()
    finally:
        session.close()
    assert stored.evaluation_state == "gap"
    assert stored.rule_code == "no_evidence"
    assert stored.owner_user_id is None
    assert stored.next_action == "collect_evidence"
    retried = client.post(
        "/api/compliance/gaps/scan-and-notify",
        headers={"Idempotency-Key": key},
    )
    assert retried.status_code == 200
    assert retried.json() == failed.json()
    assert _counts()["evidence_gaps"] == before_gaps + 1
    assert _counts()["in_app_notifications"] == before_notes


def test_migration_round_trip_restores_gap_evaluation():
    before_counts = _counts()
    before_ids = _ids()
    actors = _actors()
    env = {**os.environ, "DATABASE_URL": os.environ["DATABASE_URL"]}
    gap_id = None

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
            if gap_id is not None:
                session.execute(
                    text("DELETE FROM tc21006_gap_eval_hold WHERE id = :id"), {"id": gap_id}
                )
                session.execute(text("DELETE FROM evidence_gaps WHERE id = :id"), {"id": gap_id})
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    try:
        try:
            session = _db()
            try:
                _sync_sequence(session, "evidence_gaps")
                gap_id = session.execute(
                    text(
                        "INSERT INTO evidence_gaps ("
                        "workspace_id, gap_type, reason, status, created_at, updated_at, "
                        "control_id, evaluation_state, rule_code, evidence_refs, next_action, "
                        "owner_user_id"
                        ") VALUES ("
                        ":ws, 'control_check', :reason, 'open', :now, :now, "
                        ":control, 'stale', 'expired', :refs, 'refresh_evidence', :owner"
                        ") RETURNING id"
                    ),
                    {
                        "ws": actors["workspace_id"],
                        "reason": json.dumps(
                            {"rule": "expired", "control_id": 4, "evidence_ids": [8]}
                        ),
                        "now": datetime(2024, 1, 2, 3, 4, 5),
                        "control": 4,
                        "refs": "[8]",
                        "owner": actors["admin_id"],
                    },
                ).scalar()
                session.commit()
                seeded = session.execute(
                    text(
                        "SELECT id, workspace_id, gap_type, reason, status, control_id, "
                        "evaluation_state, rule_code, evidence_refs, next_action, owner_user_id "
                        "FROM evidence_gaps WHERE id = :id"
                    ),
                    {"id": gap_id},
                ).one()
                seeded_tuple = tuple(seeded)
            finally:
                session.close()
            alembic("downgrade", PARENT)
            alembic("upgrade", REVISION)
            session = _db()
            try:
                restored = session.execute(
                    text(
                        "SELECT id, workspace_id, gap_type, reason, status, control_id, "
                        "evaluation_state, rule_code, evidence_refs, next_action, owner_user_id "
                        "FROM evidence_gaps WHERE id = :id"
                    ),
                    {"id": gap_id},
                ).one()
                assert tuple(restored) == seeded_tuple
                assert (
                    session.execute(
                        text("SELECT count(*) FROM tc21006_gap_eval_hold WHERE id = :id"),
                        {"id": gap_id},
                    ).scalar()
                    == 0
                )
            finally:
                session.close()
            heads = [line.strip() for line in alembic("heads").splitlines() if "(head)" in line]
            assert len(heads) == 1
            assert REVISION in heads[0]
        finally:
            alembic("upgrade", "head")
            wipe()
            _delete_created(before_ids, skip=("tc21006_gap_eval_hold",))
    finally:
        after_counts = _counts()
        assert after_counts == before_counts, {"before": before_counts, "after": after_counts}
