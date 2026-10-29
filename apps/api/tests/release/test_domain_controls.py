"""TC-21-002 legacy and canonical control contract.

Runs on PostgreSQL. Synthetic control ids are test labels, not framework text.
"""

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from sqlalchemy import inspect, text

from app.core.password import hash_password
from app.models import Control, User, Workspace, WorkspaceMember

API_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = API_ROOT.parents[1]
PARENT_REVISION = "tc06001_same_workspace_refs"
REVISION = "tc21002_control_contract"
SLUG = "tc21002"
EDITOR_EMAIL = "tc21002-editor@trust.local"
REVIEWER_EMAIL = "tc21002-reviewer@trust.local"
ADMIN_EMAIL = "tc21002-admin@trust.local"
EDITOR_PASSWORD = "test-c"
REVIEWER_PASSWORD = "test-v"
ADMIN_PASSWORD = "test-a"
OTHER_EMAIL = "tc21002-other@trust.local"
OTHER_PASSWORD = "test-o"


def _fresh():
    from app.core.database import SessionLocal

    return SessionLocal()


def _sync_sequence(session, table: str) -> None:
    session.execute(
        text(
            "SELECT setval(pg_get_serial_sequence(:table, 'id'), "
            "(SELECT COALESCE(MAX(id), 1) FROM " + table + "))"
        ),
        {"table": table},
    )


def _actors() -> dict[str, int]:
    session = _fresh()
    try:
        workspace = session.query(Workspace).filter(Workspace.slug == SLUG).first()
        if workspace is None:
            _sync_sequence(session, "workspaces")
            workspace = Workspace(name="TC-21-002", slug=SLUG)
            session.add(workspace)
            session.flush()
        other = session.query(Workspace).filter(Workspace.slug == SLUG + "-other").first()
        if other is None:
            _sync_sequence(session, "workspaces")
            other = Workspace(name="TC-21-002 other", slug=SLUG + "-other")
            session.add(other)
            session.flush()

        def member(email: str, password: str, role: str, ws: Workspace) -> User:
            user = session.query(User).filter(User.email == email).first()
            if user is None:
                _sync_sequence(session, "users")
                user = User(
                    email=email,
                    password_hash=hash_password(password),
                    display_name=email,
                )
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
                .first()
            )
            if row is None:
                session.add(
                    WorkspaceMember(
                        workspace_id=ws.id,
                        user_id=user.id,
                        role=role,
                        suspended=False,
                    )
                )
            else:
                row.role = role
                row.suspended = False
            return user

        editor = member(EDITOR_EMAIL, EDITOR_PASSWORD, "editor", workspace)
        reviewer = member(REVIEWER_EMAIL, REVIEWER_PASSWORD, "reviewer", workspace)
        admin = member(ADMIN_EMAIL, ADMIN_PASSWORD, "admin", workspace)
        outsider = member(OTHER_EMAIL, OTHER_PASSWORD, "admin", other)
        session.commit()
        return {
            "workspace_id": workspace.id,
            "other_workspace_id": other.id,
            "editor_id": editor.id,
            "reviewer_id": reviewer.id,
            "admin_id": admin.id,
            "outsider_id": outsider.id,
        }
    finally:
        session.close()


def _login(client, email: str, password: str) -> None:
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def _create(client, control_id: str = "C-1", **extra) -> dict:
    body = {
        "framework": "TC21002",
        "control_id": control_id,
        "name": "Synthetic",
        "status": "in_review",
    }
    body.update(extra)
    response = client.post("/api/controls/", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _canonical_rows(client) -> tuple[dict, dict]:
    legacy = client.get("/api/controls")
    assert legacy.status_code == 200
    compliance = client.get("/api/compliance/controls")
    assert compliance.status_code == 200
    return legacy.json(), compliance.json()


def _pair(client, control_id: str = "C-1") -> tuple[dict, dict]:
    legacy_rows, compliance_rows = _canonical_rows(client)
    legacy = next(row for row in legacy_rows if row["control_id"] == control_id)
    key = legacy["canonical"]["id"]
    compliance = next(row for row in compliance_rows if row["canonical"]["id"] == key)
    return legacy, compliance


def test_permissions_workspace_mismatch_and_invalid_status(client):
    actors = _actors()
    client.cookies.clear()
    assert client.get("/api/controls").status_code == 401
    assert (
        client.post(
            "/api/controls/", json={"framework": "TC21002", "control_id": "C-1"}
        ).status_code
        == 401
    )

    _login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    refused = client.post(
        "/api/controls/",
        json={"framework": "TC21002", "control_id": "C-deny", "status": "in_review"},
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == "Insufficient permissions"

    _login(client, EDITOR_EMAIL, EDITOR_PASSWORD)
    editor_refused = client.post(
        "/api/controls/",
        json={"framework": "TC21002", "control_id": "C-deny-editor", "status": "in_review"},
    )
    assert editor_refused.status_code == 403
    assert editor_refused.json()["detail"] == "Insufficient permissions"
    assert client.get("/api/controls").status_code == 200

    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    created = _create(client, "C-perm")
    assert client.get("/api/controls").status_code == 200
    assert client.get("/api/compliance/controls").status_code == 200

    _login(client, OTHER_EMAIL, OTHER_PASSWORD)
    missing = client.patch(f"/api/controls/{created['id']}", json={"status": "implemented"})
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Control not found"
    gone = client.delete(f"/api/controls/{created['id']}")
    assert gone.status_code == 404

    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    invalid = client.post(
        "/api/controls/",
        json={"framework": "TC21002", "control_id": "C-bad", "status": "enabled"},
    )
    assert invalid.status_code == 400
    assert "Invalid status" in invalid.json()["detail"]
    owner = client.post(
        "/api/controls/",
        json={
            "framework": "TC21002",
            "control_id": "C-owner",
            "status": "in_review",
            "owner_user_id": actors["outsider_id"],
        },
    )
    assert owner.status_code == 404
    assert owner.json()["detail"]["code"] == "owner_not_in_workspace"
    assert owner.json()["detail"]["partial_failure"] is False


def test_routes_agree_on_canonical_contract_and_retry(client):
    actors = _actors()
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    first = _create(client, "C-1", owner_user_id=actors["editor_id"], owner_team="owners")
    second = _create(client, "C-1", owner_user_id=actors["editor_id"], owner_team="owners")
    assert second["id"] == first["id"]
    assert first["status"] == "in_review"
    assert first["canonical"]["lifecycle"] == "in_progress"
    assert first["canonical"]["version"] is None
    assert first["canonical"]["content_version"] is None
    assert first["canonical"]["contract_version"] == "control-contract/v1"
    assert first["canonical"]["owner_user_id"] == actors["editor_id"]
    assert first["canonical"]["status_aligned"] is True

    legacy, compliance = _pair(client, "C-1")
    assert legacy["canonical"] == compliance["canonical"]
    assert compliance["status"] == "in_progress"

    session = _fresh()
    try:
        count = session.execute(
            text("SELECT count(*) FROM controls WHERE workspace_id = :ws AND canonical_key = :key"),
            {"ws": actors["workspace_id"], "key": first["canonical"]["id"]},
        ).scalar()
        assert count == 1
        blocked = session.execute(
            text("SELECT enablement_state FROM frameworks WHERE catalog_key = 'HIPAA'")
        ).scalar()
        assert blocked == "blocked"
    finally:
        session.close()

    # CI installs Node from apps/web/.nvmrc onto PATH (actions/setup-node).
    # A home-directory nvm path is not present on that runner.
    node = shutil.which("node")
    assert node, "node is not on PATH"
    version = subprocess.run([node, "--version"], capture_output=True, text=True, check=False)
    assert version.returncode == 0, version.stderr
    assert version.stdout.startswith("v24."), version.stdout
    script = (
        "import { sameCanonicalControl } from './apps/web/lib/controlContract.ts';"
        "const fs = await import('node:fs');"
        "const payload = JSON.parse(fs.readFileSync(0, 'utf8'));"
        "process.stdout.write(JSON.stringify(sameCanonicalControl(payload.legacy, payload.compliance)));"
    )
    proc = subprocess.run(
        [str(node), "--experimental-strip-types", "--input-type=module", "-e", script],
        input=json.dumps({"legacy": legacy, "compliance": compliance}),
        text=True,
        capture_output=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) is True

    session = _fresh()
    try:
        session.execute(
            text("UPDATE controls SET lifecycle = 'not_implemented' WHERE id = :id"),
            {"id": first["id"]},
        )
        session.commit()
    finally:
        session.close()
    drifted_legacy, drifted_compliance = _pair(client, "C-1")
    assert drifted_legacy["canonical"]["lifecycle"] == "in_progress"
    assert drifted_legacy["canonical"] == drifted_compliance["canonical"]
    assert drifted_legacy["canonical"]["status_aligned"] is False
    session = _fresh()
    try:
        stored = session.execute(
            text("SELECT lifecycle FROM controls WHERE id = :id"),
            {"id": first["id"]},
        ).scalar()
        assert stored == "not_implemented"
    finally:
        session.close()

    repaired = client.patch(f"/api/controls/{first['id']}", json={"status": "in_review"})
    assert repaired.status_code == 200
    assert repaired.json()["canonical"]["status_aligned"] is True
    assert repaired.json()["canonical"]["lifecycle"] == "in_progress"


def test_evidence_foreign_reference_partial_failure_and_retry(client):
    actors = _actors()
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    control_key = f"C-ev-{uuid.uuid4().hex[:12]}"
    created = _create(client, control_key)
    both = client.post(
        f"/api/controls/{created['id']}/evidence",
        json={"document_id": 1, "trust_article_id": 1},
    )
    assert both.status_code == 400
    assert "exactly one" in both.json()["detail"]

    session = _fresh()
    try:
        from app.models import Document

        _sync_sequence(session, "documents")
        foreign = Document(
            workspace_id=actors["other_workspace_id"],
            storage_key="tc21002/foreign",
            filename="foreign.txt",
            status="uploaded",
        )
        local = Document(
            workspace_id=actors["workspace_id"],
            storage_key="tc21002/local",
            filename="local.txt",
            status="uploaded",
        )
        session.add(foreign)
        session.add(local)
        session.commit()
        foreign_id = foreign.id
        local_id = local.id
    finally:
        session.close()

    missing = client.post(
        f"/api/controls/{created['id']}/evidence",
        json={"document_id": foreign_id},
    )
    assert missing.status_code == 404
    assert "not found in this workspace" in missing.json()["detail"]
    assert client.get(f"/api/controls/{created['id']}/evidence").json() == []

    from app.services.control_contract import attach_legacy_evidence

    session = _fresh()
    try:
        legacy = session.query(Control).filter(Control.id == created["id"]).one()
        partial = attach_legacy_evidence(
            session,
            legacy,
            document_id=local_id,
            trust_article_id=None,
            export_record_id=None,
            mirror_workspace_id=42424242,
        )
        assert partial.partial_failure is True
        assert partial.error["code"] == "control_evidence_partial_failure"
        assert partial.error["retryable"] is True
        evidence_id = partial.error["evidence_id"]
    finally:
        session.close()

    listed = client.get(f"/api/controls/{created['id']}/evidence")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [evidence_id]
    legacy, compliance = _pair(client, control_key)
    assert legacy["canonical"]["evidence"]["mirrored"] is False

    again = client.post(
        f"/api/controls/{created['id']}/evidence",
        json={"document_id": local_id},
    )
    assert again.status_code == 200
    assert again.json()["id"] == evidence_id
    assert again.json()["canonical"]["target_kind"] == "document"
    assert again.json()["canonical"]["exactly_one_target"] is True
    legacy, compliance = _pair(client, control_key)
    assert legacy["canonical"] == compliance["canonical"]
    assert legacy["canonical"]["evidence"]["legacy_count"] == 1
    assert legacy["canonical"]["evidence"]["canonical_count"] == 1
    assert legacy["canonical"]["evidence"]["mirrored"] is True

    session = _fresh()
    try:
        reloaded = session.query(Control).filter(Control.id == created["id"]).one()
        assert reloaded.lifecycle == "in_progress"
        assert reloaded.content_version is None
    finally:
        session.close()


def test_get_is_read_only_and_delete_removes_the_pair(client):
    actors = _actors()
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    created = _create(client, "C-ro")
    session = _fresh()
    try:
        before = session.execute(
            text(
                "SELECT status, lifecycle, content_version, updated_at "
                "FROM controls WHERE id = :id"
            ),
            {"id": created["id"]},
        ).one()
    finally:
        session.close()
    assert client.get("/api/controls").status_code == 200
    assert client.get("/api/compliance/controls").status_code == 200
    session = _fresh()
    try:
        after = session.execute(
            text(
                "SELECT status, lifecycle, content_version, updated_at "
                "FROM controls WHERE id = :id"
            ),
            {"id": created["id"]},
        ).one()
        assert tuple(after) == tuple(before)
        ws_count = session.execute(
            text(
                "SELECT count(*) FROM workspace_controls WHERE workspace_id = :ws AND canonical_key = :key"
            ),
            {"ws": actors["workspace_id"], "key": created["canonical"]["id"]},
        ).scalar()
        assert ws_count == 1
    finally:
        session.close()

    removed = client.delete(f"/api/controls/{created['id']}")
    assert removed.status_code == 200
    assert removed.json()["ok"] is True
    session = _fresh()
    try:
        assert (
            session.execute(
                text("SELECT count(*) FROM controls WHERE id = :id"),
                {"id": created["id"]},
            ).scalar()
            == 0
        )
        assert (
            session.execute(
                text(
                    "SELECT count(*) FROM workspace_controls "
                    "WHERE workspace_id = :ws AND canonical_key = :key"
                ),
                {"ws": actors["workspace_id"], "key": created["canonical"]["id"]},
            ).scalar()
            == 0
        )
    finally:
        session.close()


def test_contract_event_partial_failure_retries_to_the_same_row(client):
    actors = _actors()
    from app.services.control_contract import upsert_legacy_control

    session = _fresh()
    try:
        control_key = f"C-partial-{uuid.uuid4().hex[:12]}"
        request_id = f"tc21002-partial-{uuid.uuid4().hex[:12]}"
        failed = upsert_legacy_control(
            session,
            workspace_id=actors["workspace_id"],
            framework="TC21002",
            control_key=control_key,
            name="Synthetic",
            legacy_status="implemented",
            owner_user_id=actors["editor_id"],
            owner_team=None,
            request_id=request_id,
            event_workspace_id=42424242,
        )
        assert failed.http_status == 409
        assert failed.partial_failure is True
        assert failed.error["code"] == "control_contract_partial_failure"
        assert failed.error["lifecycle"] == "implemented"
        legacy_id = failed.error["control_id"]
    finally:
        session.close()

    session = _fresh()
    try:
        stored = session.execute(
            text("SELECT lifecycle, content_version FROM controls WHERE id = :id"),
            {"id": legacy_id},
        ).one()
        assert stored.lifecycle == "implemented"
        assert stored.content_version is None
        events = session.execute(
            text("SELECT count(*) FROM control_contract_events WHERE request_id = :request_id"),
            {"request_id": request_id},
        ).scalar()
        assert events == 0
    finally:
        session.close()

    session = _fresh()
    try:
        retried = upsert_legacy_control(
            session,
            workspace_id=actors["workspace_id"],
            framework="TC21002",
            control_key=control_key,
            name="Synthetic",
            legacy_status="implemented",
            owner_user_id=actors["editor_id"],
            owner_team=None,
            request_id=request_id,
        )
        assert retried.http_status == 200
        assert retried.ids["legacy"].id == legacy_id
    finally:
        session.close()

    _login(client, EDITOR_EMAIL, EDITOR_PASSWORD)
    legacy, compliance = _pair(client, control_key)
    assert legacy["id"] == legacy_id
    assert legacy["canonical"] == compliance["canonical"]
    assert legacy["canonical"]["lifecycle"] == "implemented"
    assert legacy["status"] == "implemented"
    assert compliance["status"] == "implemented"


def test_migration_upgrade_downgrade_upgrade_again(client):
    _actors()
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    created = _create(client, "C-mig")
    import importlib.util

    from app.core.database import engine

    mig = API_ROOT / "alembic" / "versions" / "079_tc21002_control_contract.py"
    spec = importlib.util.spec_from_file_location("tc21002_mig", mig)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == REVISION
    assert mod.down_revision == PARENT_REVISION
    assert "app." not in mig.read_text(encoding="utf-8")
    env = {**os.environ, "DATABASE_URL": os.environ["DATABASE_URL"]}

    def alembic(*args):
        proc = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=API_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr[-2000:] + proc.stdout[-2000:]
        return proc.stdout

    def columns(table: str) -> set[str]:
        engine.dispose()
        return {col["name"] for col in inspect(engine).get_columns(table)}

    assert "canonical_key" in columns("controls")
    assert "lifecycle" in columns("workspace_controls")
    alembic("downgrade", PARENT_REVISION)
    try:
        assert "canonical_key" not in columns("controls")
        assert "lifecycle" not in columns("workspace_controls")
        assert "evidence_item_id" not in columns("control_evidence")
        assert "control_contract_events" not in set(inspect(engine).get_table_names())
        session = _fresh()
        try:
            row = session.execute(
                text("SELECT framework, control_id, status, name FROM controls WHERE id = :id"),
                {"id": created["id"]},
            ).one()
            assert row.framework == "TC21002"
            assert row.control_id == "C-mig"
            assert row.status == "in_review"
            assert row.name == "Synthetic"
        finally:
            session.close()
    finally:
        alembic("upgrade", "head")
    assert "canonical_key" in columns("controls")
    heads_out = alembic("heads")
    # A later revision may be the single head. Same checks as
    # tests/release/test_job_retries.py and tests/release/test_billing_provider.py.
    assert len(heads_out.strip().splitlines()) == 1
    assert "(head)" in heads_out
    from tests.release.test_billing_provider import _revision_is_applied, _revision_token

    assert _revision_is_applied(_revision_token(heads_out), REVISION)
