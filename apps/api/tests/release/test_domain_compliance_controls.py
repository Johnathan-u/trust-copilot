"""TC-21-003 compliance control lifecycle and evidence verification.

Runs on PostgreSQL. Labels are synthetic, not framework text.
"""

import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, engine
from app.core.password import hash_password
from app.main import app
from app.models import (
    Chunk,
    ControlEvidenceLink,
    Document,
    EvidenceItem,
    EvidenceMetadata,
    User,
    Workspace,
    WorkspaceControl,
    WorkspaceMember,
)
from tests.conftest import TEST_HEADERS, TEST_ORIGIN

API_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
PARENT = "tc21002a_canonical_uniq"
REVISION = "tc21003_evidence_link_uniq"
SLUG = "tc21003"
ADMIN_EMAIL = "tc21003-admin@trust.local"
EDITOR_EMAIL = "tc21003-editor@trust.local"
REVIEWER_EMAIL = "tc21003-reviewer@trust.local"
OTHER_EMAIL = "tc21003-other@trust.local"
ADMIN_PASSWORD = "test-a"
EDITOR_PASSWORD = "test-e"
REVIEWER_PASSWORD = "test-r"
OTHER_PASSWORD = "test-o"
DENIED = "Verified status requires approved, current evidence linked in this workspace"


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


def _actors() -> dict[str, int]:
    session = _db()
    try:
        workspace = session.query(Workspace).filter(Workspace.slug == SLUG).one_or_none()
        if workspace is None:
            _sync_sequence(session, "workspaces")
            workspace = Workspace(name="TC-21-003", slug=SLUG)
            session.add(workspace)
            session.flush()
        other = session.query(Workspace).filter(Workspace.slug == SLUG + "-other").one_or_none()
        if other is None:
            _sync_sequence(session, "workspaces")
            other = Workspace(name="TC-21-003 other", slug=SLUG + "-other")
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
        outsider = member(OTHER_EMAIL, OTHER_PASSWORD, "admin", other)
        session.commit()
        return {
            "workspace_id": workspace.id,
            "other_workspace_id": other.id,
            "admin_id": admin.id,
            "editor_id": editor.id,
            "reviewer_id": reviewer.id,
            "outsider_id": outsider.id,
        }
    finally:
        session.close()


def _login(client, email: str, password: str) -> None:
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def _control(client, name: str) -> dict:
    response = client.post(
        "/api/compliance/controls",
        json={"custom_name": name, "status": "not_implemented"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _evidence(
    session: Session, workspace_id: int, *, approval: str, document_id: int | None
) -> int:
    _sync_sequence(session, "evidence_items")
    row = EvidenceItem(
        workspace_id=workspace_id,
        source_type="manual" if document_id is None else "document",
        title="Synthetic evidence",
        approval_status=approval,
        document_id=document_id,
    )
    session.add(row)
    session.flush()
    return row.id


def test_permissions_workspace_mismatch_and_read_only_gets(client):
    _actors()
    client.cookies.clear()
    assert client.get("/api/compliance/controls").status_code == 401
    assert client.get("/api/compliance/controls/stats").status_code == 401
    assert client.post("/api/compliance/controls", json={"custom_name": "x"}).status_code == 401

    _login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    refused = client.post("/api/compliance/controls", json={"custom_name": "Reviewer"})
    assert refused.status_code == 403
    assert refused.json()["detail"] == "Insufficient permissions"
    assert client.get("/api/compliance/controls").status_code == 200
    assert client.get("/api/compliance/controls/stats").status_code == 200

    _login(client, EDITOR_EMAIL, EDITOR_PASSWORD)
    editor_refused = client.post("/api/compliance/controls", json={"custom_name": "Editor"})
    assert editor_refused.status_code == 403

    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    created = _control(client, "Synthetic control")
    session = _db()
    try:
        before = session.execute(
            text("SELECT updated_at FROM workspace_controls WHERE id = :id"),
            {"id": created["id"]},
        ).scalar()
    finally:
        session.close()
    assert client.get("/api/compliance/controls").status_code == 200
    assert client.get(f"/api/compliance/controls/{created['id']}").status_code == 200
    assert client.get("/api/compliance/controls/stats").status_code == 200
    assert client.get(f"/api/compliance/controls/{created['id']}/evidence").status_code == 200
    session = _db()
    try:
        after = session.execute(
            text("SELECT updated_at FROM workspace_controls WHERE id = :id"),
            {"id": created["id"]},
        ).scalar()
        assert after == before
    finally:
        session.close()

    _login(client, OTHER_EMAIL, OTHER_PASSWORD)
    missing = client.get(f"/api/compliance/controls/{created['id']}")
    assert missing.status_code == 404
    patched = client.patch(
        f"/api/compliance/controls/{created['id']}", json={"status": "in_progress"}
    )
    assert patched.status_code == 404
    assert client.get(f"/api/compliance/controls/{created['id']}/evidence").status_code == 404
    _login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    suggest = client.post(f"/api/compliance/controls/{created['id']}/suggest-evidence")
    assert suggest.status_code == 200
    assert suggest.json() == [] or isinstance(suggest.json(), list)


def test_verify_requires_qualifying_evidence_and_retry_is_stable(client):
    actors = _actors()
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    created = _control(client, "Verify synthetic")
    session = _db()
    try:
        pending = _evidence(session, actors["workspace_id"], approval="pending", document_id=None)
        session.add(
            ControlEvidenceLink(control_id=created["id"], evidence_id=pending, verified=False)
        )
        session.commit()
    finally:
        session.close()

    _login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    denied = client.post(f"/api/compliance/controls/{created['id']}/verify")
    assert denied.status_code == 400
    assert denied.json()["detail"] == DENIED
    session = _db()
    try:
        status = session.execute(
            text("SELECT status FROM workspace_controls WHERE id = :id"),
            {"id": created["id"]},
        ).scalar()
        assert status == "not_implemented"
        approved = _evidence(session, actors["workspace_id"], approval="approved", document_id=None)
        session.add(
            ControlEvidenceLink(control_id=created["id"], evidence_id=approved, verified=False)
        )
        session.commit()
        evidence_id = approved
    finally:
        session.close()

    verified = client.post(f"/api/compliance/controls/{created['id']}/verify")
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "verified"
    stamp = verified.json()["verified_at"]
    again = client.post(f"/api/compliance/controls/{created['id']}/verify")
    assert again.status_code == 200
    assert again.json()["status"] == "verified"
    assert again.json()["verified_at"] == stamp

    session = _db()
    try:
        session.add(
            EvidenceMetadata(
                evidence_id=evidence_id,
                expires_at=datetime.utcnow() - timedelta(days=1),
            )
        )
        session.commit()
    finally:
        session.close()
    expired = client.post(f"/api/compliance/controls/{created['id']}/verify")
    assert expired.status_code == 400
    session = _db()
    try:
        status = session.execute(
            text("SELECT status FROM workspace_controls WHERE id = :id"),
            {"id": created["id"]},
        ).scalar()
        assert status == "verified"
    finally:
        session.close()

    _login(client, EDITOR_EMAIL, EDITOR_PASSWORD)
    assert (
        client.post(
            f"/api/compliance/controls/{created['id']}/evidence", json={"evidence_id": evidence_id}
        ).status_code
        == 403
    )
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    linked = client.post(
        f"/api/compliance/controls/{created['id']}/evidence",
        json={"evidence_id": evidence_id},
    )
    assert linked.status_code == 200, linked.text
    replay = client.post(
        f"/api/compliance/controls/{created['id']}/evidence",
        json={"evidence_id": evidence_id},
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == linked.json()["id"]
    session = _db()
    try:
        count = session.execute(
            text(
                "SELECT count(*) FROM control_evidence_links "
                "WHERE control_id = :c AND evidence_id = :e"
            ),
            {"c": created["id"], "e": evidence_id},
        ).scalar()
        assert count == 1
        foreign = _evidence(
            session, actors["other_workspace_id"], approval="approved", document_id=None
        )
        session.commit()
        foreign_id = foreign
    finally:
        session.close()
    missing = client.post(
        f"/api/compliance/controls/{created['id']}/evidence",
        json={"evidence_id": foreign_id},
    )
    assert missing.status_code == 404
    gone = client.post(
        f"/api/compliance/controls/{created['id']}/evidence",
        json={"evidence_id": 99999999},
    )
    assert gone.status_code == 404


def test_deleted_document_and_link_verified_flag(client):
    actors = _actors()
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    created = _control(client, "Document synthetic")
    session = _db()
    try:
        _sync_sequence(session, "documents")
        doc = Document(
            workspace_id=actors["workspace_id"],
            storage_key=f"tc21003/{uuid.uuid4().hex}",
            filename="synthetic.txt",
            status="uploaded",
            deleted_at=datetime.utcnow(),
        )
        session.add(doc)
        session.flush()
        evidence_id = _evidence(
            session, actors["workspace_id"], approval="approved", document_id=doc.id
        )
        session.add(
            ControlEvidenceLink(control_id=created["id"], evidence_id=evidence_id, verified=False)
        )
        session.commit()
    finally:
        session.close()
    _login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    denied = client.post(f"/api/compliance/controls/{created['id']}/verify")
    assert denied.status_code == 400
    session = _db()
    try:
        link_id = session.execute(
            text("SELECT id FROM control_evidence_links WHERE control_id = :c"),
            {"c": created["id"]},
        ).scalar()
    finally:
        session.close()
    marked = client.patch(
        f"/api/compliance/controls/{created['id']}/evidence/{link_id}",
        json={"verified": True},
    )
    assert marked.status_code == 400


def test_accept_suggested_failure_leaves_no_partial_state(client):
    actors = _actors()
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    created = _control(client, "Accept synthetic")
    _login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    assert (
        client.post(
            f"/api/compliance/controls/{created['id']}/evidence/accept-suggested",
            json={"chunk_id": 1},
        ).status_code
        == 403
    )
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    session = _db()
    try:
        _sync_sequence(session, "documents")
        doc = Document(
            workspace_id=actors["workspace_id"],
            storage_key=f"tc21003/{uuid.uuid4().hex}",
            filename="chunk.txt",
            status="uploaded",
        )
        session.add(doc)
        session.flush()
        _sync_sequence(session, "chunks")
        chunk = Chunk(workspace_id=actors["workspace_id"], document_id=doc.id, text="synthetic")
        session.add(chunk)
        session.commit()
        chunk_id = chunk.id
        before_evidence = session.execute(
            text("SELECT count(*) FROM evidence_items WHERE workspace_id = :ws"),
            {"ws": actors["workspace_id"]},
        ).scalar()
        before_links = session.execute(
            text("SELECT count(*) FROM control_evidence_links WHERE control_id = :c"),
            {"c": created["id"]},
        ).scalar()
    finally:
        session.close()

    from sqlalchemy.orm import Session as OrmSession

    def fail_commit(self, *args, **kwargs):
        raise RuntimeError("forced commit failure")

    quiet = TestClient(
        app, base_url=TEST_ORIGIN, headers=TEST_HEADERS, raise_server_exceptions=False
    )
    _login(quiet, ADMIN_EMAIL, ADMIN_PASSWORD)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(OrmSession, "commit", fail_commit)
        failed = quiet.post(
            f"/api/compliance/controls/{created['id']}/evidence/accept-suggested",
            json={"chunk_id": chunk_id},
        )
    assert failed.status_code == 500
    session = _db()
    try:
        evidence = session.execute(
            text("SELECT count(*) FROM evidence_items WHERE workspace_id = :ws"),
            {"ws": actors["workspace_id"]},
        ).scalar()
        links = session.execute(
            text("SELECT count(*) FROM control_evidence_links WHERE control_id = :c"),
            {"c": created["id"]},
        ).scalar()
        assert evidence == before_evidence
        assert links == before_links
    finally:
        session.close()


def test_migration_dedupes_links_and_downgrade_restores_them():
    actors = _actors()
    import importlib.util

    path = os.path.join(API_ROOT, "alembic", "versions", "081_tc21003_evidence_link_uniq.py")
    spec = importlib.util.spec_from_file_location("tc21003_mig", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == REVISION
    assert mod.down_revision == PARENT
    assert "app." not in open(path, encoding="utf-8").read()
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

    session = _db()
    try:
        control = WorkspaceControl(
            workspace_id=actors["workspace_id"], status="not_implemented", custom_name="Dup"
        )
        session.add(control)
        session.flush()
        evidence = EvidenceItem(
            workspace_id=actors["workspace_id"],
            source_type="manual",
            title="Dup evidence",
            approval_status="approved",
        )
        session.add(evidence)
        session.commit()
        control_id = control.id
        evidence_id = evidence.id
    finally:
        session.close()

    alembic("downgrade", PARENT)
    session = _db()
    try:
        session.execute(
            text(
                "INSERT INTO control_evidence_links "
                "(control_id, evidence_id, verified, created_at) "
                "VALUES (:c, :e, false, NOW()), (:c, :e, true, NOW())"
            ),
            {"c": control_id, "e": evidence_id},
        )
        session.commit()
        ids = session.execute(
            text(
                "SELECT id FROM control_evidence_links "
                "WHERE control_id = :c AND evidence_id = :e ORDER BY id"
            ),
            {"c": control_id, "e": evidence_id},
        ).fetchall()
    finally:
        session.close()
    assert len(ids) == 2
    try:
        alembic("upgrade", "head")
        engine.dispose()
        session = _db()
        try:
            remaining = session.execute(
                text(
                    "SELECT id, verified FROM control_evidence_links "
                    "WHERE control_id = :c AND evidence_id = :e"
                ),
                {"c": control_id, "e": evidence_id},
            ).fetchall()
            assert len(remaining) == 1
            assert remaining[0].id == ids[0].id
            with pytest.raises(IntegrityError):
                session.execute(
                    text(
                        "INSERT INTO control_evidence_links "
                        "(control_id, evidence_id, verified, created_at) "
                        "VALUES (:c, :e, false, NOW())"
                    ),
                    {"c": control_id, "e": evidence_id},
                )
                session.commit()
            session.rollback()
        finally:
            session.close()
        alembic("downgrade", PARENT)
        session = _db()
        try:
            restored = session.execute(
                text(
                    "SELECT count(*) FROM control_evidence_links "
                    "WHERE control_id = :c AND evidence_id = :e"
                ),
                {"c": control_id, "e": evidence_id},
            ).scalar()
            assert restored == 2
        finally:
            session.close()
    finally:
        alembic("upgrade", "head")
    heads = [line.strip() for line in alembic("heads").splitlines() if "(head)" in line]
    assert len(heads) == 1
    from tests.release.test_billing_provider import _revision_is_applied, _revision_token

    assert _revision_is_applied(_revision_token(alembic("heads")), REVISION)
