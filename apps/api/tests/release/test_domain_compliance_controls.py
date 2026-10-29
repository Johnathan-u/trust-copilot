"""TC-21-003 compliance control lifecycle and evidence verification.

Runs on PostgreSQL. Labels are synthetic, not framework text.
"""

import logging
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text
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
_COUNTED = (
    "tc21003_link_hold",
    "control_evidence_links",
    "evidence_metadata",
    "chunks",
    "evidence_items",
    "documents",
    "in_app_notifications",
    "compliance_webhook_outbox",
    "audit_events",
    "control_contract_events",
    "controls",
    "workspace_controls",
    "user_sessions",
    "idempotency_keys",
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


def _reset_login_limit() -> None:
    """Login is limited to 10 attempts per minute per IP. This file logs in more than that."""
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
    """Delete every row this test creates and require the counted tables to match.

    The migration test drops and recreates tc21003_link_hold, so it cleans up itself.
    """
    if request.node.originalname == "test_migration_round_trip_restores_duplicate_links":
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
        print(f"TC21003_COUNTS before={before_counts} after={after_counts}")


def _chunk(workspace_id: int) -> int:
    session = _db()
    try:
        _sync_sequence(session, "documents")
        doc = Document(
            workspace_id=workspace_id,
            storage_key=f"tc21003/{uuid.uuid4().hex}",
            filename="chunk.txt",
            status="uploaded",
        )
        session.add(doc)
        session.flush()
        _sync_sequence(session, "chunks")
        chunk = Chunk(workspace_id=workspace_id, document_id=doc.id, text="synthetic")
        session.add(chunk)
        session.commit()
        return chunk.id
    finally:
        session.close()


def _table_count(table: str) -> int:
    session = _db()
    try:
        return int(session.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0)
    finally:
        session.close()


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
    created = _control(client, f"Synthetic {uuid.uuid4().hex[:8]}")
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
    created = _control(client, f"Verify {uuid.uuid4().hex[:8]}")
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
    session = _db()
    try:
        fresh_evidence = _evidence(
            session, actors["workspace_id"], approval="approved", document_id=None
        )
        session.commit()
    finally:
        session.close()
    linked = client.post(
        f"/api/compliance/controls/{created['id']}/evidence",
        json={"evidence_id": fresh_evidence},
    )
    assert linked.status_code == 201, linked.text
    replay = client.post(
        f"/api/compliance/controls/{created['id']}/evidence",
        json={"evidence_id": fresh_evidence},
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
            {"c": created["id"], "e": fresh_evidence},
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
    created = _control(client, f"Document {uuid.uuid4().hex[:8]}")
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
    created = _control(client, f"Accept {uuid.uuid4().hex[:8]}")
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


def _accept(client, control_id: int, chunk_id: int, key: str):
    return client.post(
        f"/api/compliance/controls/{control_id}/evidence/accept-suggested",
        json={"chunk_id": chunk_id, "confidence": 0.5},
        headers={"Idempotency-Key": key},
    )


def test_accept_suggested_same_key_retry_creates_nothing_new(client, restored_rows):
    actors = _actors()
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    created = _control(client, f"Idem {uuid.uuid4().hex[:8]}")
    chunk_id = _chunk(actors["workspace_id"])
    key = f"acc-{uuid.uuid4().hex}"
    storage = f"accept-suggested:{actors['workspace_id']}:{created['id']}:{key}"
    evidence_before = _table_count("evidence_items")
    links_before = _table_count("control_evidence_links")
    first = _accept(client, created["id"], chunk_id, key)
    assert first.status_code == 200, first.text
    body = first.json()
    assert _table_count("evidence_items") == evidence_before + 1
    assert _table_count("control_evidence_links") == links_before + 1
    session = _db()
    try:
        owner = session.execute(
            text("SELECT owner_token FROM idempotency_keys WHERE idempotency_key = :k"),
            {"k": storage},
        ).scalar()
        assert owner
    finally:
        session.close()
    retried = _accept(client, created["id"], chunk_id, key)
    assert retried.status_code == 200
    assert retried.json() == body
    assert _table_count("evidence_items") == evidence_before + 1
    assert _table_count("control_evidence_links") == links_before + 1


def test_accept_suggested_failed_commit_releases_the_claim(client, restored_rows):
    from sqlalchemy.orm import Session as OrmSession

    actors = _actors()
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    created = _control(client, f"Fail {uuid.uuid4().hex[:8]}")
    chunk_id = _chunk(actors["workspace_id"])
    key = f"acc-fail-{uuid.uuid4().hex}"
    storage = f"accept-suggested:{actors['workspace_id']}:{created['id']}:{key}"
    evidence_before = _table_count("evidence_items")
    links_before = _table_count("control_evidence_links")
    real_commit = OrmSession.commit
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
    with patch.object(OrmSession, "commit", failing_commit):
        failed = _accept(quiet, created["id"], chunk_id, key)
    assert failed.status_code == 500, failed.text
    assert seen["n"] >= 3
    assert _table_count("evidence_items") == evidence_before
    assert _table_count("control_evidence_links") == links_before
    session = _db()
    try:
        owner = session.execute(
            text("SELECT owner_token FROM idempotency_keys WHERE idempotency_key = :k"),
            {"k": storage},
        ).scalar()
        assert owner is None
    finally:
        session.close()
    retried = _accept(client, created["id"], chunk_id, key)
    assert retried.status_code == 200, retried.text
    assert _table_count("evidence_items") == evidence_before + 1
    assert _table_count("control_evidence_links") == links_before + 1
    replay = _accept(client, created["id"], chunk_id, key)
    assert replay.status_code == 200
    assert replay.json() == retried.json()
    assert _table_count("evidence_items") == evidence_before + 1
    assert _table_count("control_evidence_links") == links_before + 1


@pytest.mark.parametrize("failure", ["tags", "store"])
def test_accept_suggested_post_commit_failure_retries_without_duplicate(client, failure):
    """A post-commit tag or store error must not leave the claim in progress."""
    actors = _actors()
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    created = _control(client, f"Settle {failure} {uuid.uuid4().hex[:8]}")
    chunk_id = _chunk(actors["workspace_id"])
    key = f"acc-settle-{failure}-{uuid.uuid4().hex}"
    evidence_before = _table_count("evidence_items")
    links_before = _table_count("control_evidence_links")
    quiet = TestClient(
        app, base_url=TEST_ORIGIN, headers=TEST_HEADERS, raise_server_exceptions=False
    )
    _login(quiet, ADMIN_EMAIL, ADMIN_PASSWORD)
    target = (
        "app.services.tag_service.list_tags_for_document"
        if failure == "tags"
        else "app.api.routes.compliance_controls.idempotency_set"
    )

    def boom(*_args, **_kwargs):
        raise RuntimeError(f"forced {failure} failure")

    with patch(target, side_effect=boom):
        first = _accept(quiet, created["id"], chunk_id, key)
    assert first.status_code != 409, first.text
    assert _table_count("evidence_items") == evidence_before + 1
    assert _table_count("control_evidence_links") == links_before + 1
    retried = _accept(client, created["id"], chunk_id, key)
    assert retried.status_code == 200, retried.text
    assert retried.status_code != 409
    assert _table_count("evidence_items") == evidence_before + 1
    assert _table_count("control_evidence_links") == links_before + 1
    session = _db()
    try:
        stored_evidence = session.execute(
            text("SELECT evidence_id FROM control_evidence_links WHERE control_id = :c"),
            {"c": created["id"]},
        ).scalar()
    finally:
        session.close()
    assert retried.json()["evidence_id"] == stored_evidence
    assert retried.json()["evidence"]["id"] == stored_evidence
    if first.status_code == 200:
        assert retried.json() == first.json()


def test_second_idempotency_store_failure_keeps_the_original_error(client, caplog):
    """A second store failure must not replace the tag-lookup error."""
    actors = _actors()
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    created = _control(client, f"Mask {uuid.uuid4().hex[:8]}")
    chunk_id = _chunk(actors["workspace_id"])
    key = f"acc-mask-{uuid.uuid4().hex}"

    def tags_boom(*_args, **_kwargs):
        raise RuntimeError("forced tags failure")

    def store_boom(*_args, **_kwargs):
        raise RuntimeError("forced store failure")

    with caplog.at_level(logging.ERROR, logger="app.api.routes.compliance_controls"):
        with (
            patch("app.services.tag_service.list_tags_for_document", side_effect=tags_boom),
            patch("app.api.routes.compliance_controls.idempotency_set", side_effect=store_boom),
            patch("app.core.idempotency.set", side_effect=store_boom),
        ):
            with pytest.raises(RuntimeError, match="forced tags failure"):
                _accept(client, created["id"], chunk_id, key)
    assert "the original error is unchanged" in caplog.text
    assert "forced store failure" in caplog.text


def _call(client, method: str, path: str, body: dict | None):
    if method == "GET":
        return client.get(path)
    if method == "POST":
        return client.post(path, json=body)
    if method == "PATCH":
        return client.patch(path, json=body)
    if method == "DELETE":
        return client.delete(path)
    raise AssertionError(method)


def test_changed_routes_deny_at_each_permission_level(client):
    actors = _actors()
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    created = _control(client, f"Deny {uuid.uuid4().hex[:8]}")
    session = _db()
    try:
        approved = _evidence(session, actors["workspace_id"], approval="approved", document_id=None)
        session.add(
            ControlEvidenceLink(control_id=created["id"], evidence_id=approved, verified=False)
        )
        fresh = _evidence(session, actors["workspace_id"], approval="approved", document_id=None)
        session.commit()
        link_id = session.execute(
            text(
                "SELECT id FROM control_evidence_links WHERE control_id = :c AND evidence_id = :e"
            ),
            {"c": created["id"], "e": approved},
        ).scalar()
    finally:
        session.close()
    chunk_id = _chunk(actors["workspace_id"])
    control = created["id"]
    routes = [
        (
            "PATCH",
            f"/api/compliance/controls/{control}",
            {"status": "in_progress"},
            {"admin": 200},
        ),
        (
            "POST",
            f"/api/compliance/controls/{control}/verify",
            None,
            {"reviewer": 200, "editor": 200, "admin": 200},
        ),
        (
            "POST",
            f"/api/compliance/controls/{control}/evidence/accept-suggested",
            {"chunk_id": chunk_id, "confidence": 0.4},
            {"admin": 200},
        ),
        (
            "PATCH",
            f"/api/compliance/controls/{control}/evidence/{link_id}",
            {"verified": True},
            {"reviewer": 200, "editor": 200, "admin": 200},
        ),
        (
            "POST",
            f"/api/compliance/controls/{control}/evidence",
            {"evidence_id": fresh},
            {"admin": 201},
        ),
    ]
    client.cookies.clear()
    for method, path, body, _allowed in routes:
        response = _call(client, method, path, body)
        assert response.status_code == 401, (method, path, response.text)
    for role, email, password in (
        ("reviewer", REVIEWER_EMAIL, REVIEWER_PASSWORD),
        ("editor", EDITOR_EMAIL, EDITOR_PASSWORD),
        ("admin", ADMIN_EMAIL, ADMIN_PASSWORD),
    ):
        _login(client, email, password)
        for method, path, body, allowed in routes:
            response = _call(client, method, path, body)
            expected = allowed.get(role, 403)
            assert response.status_code == expected, (role, method, path, response.text)
            if expected == 403:
                assert response.json()["detail"] == "Insufficient permissions"


def test_missing_and_foreign_ids_share_the_404_body(client):
    actors = _actors()
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    created = _control(client, f"Same {uuid.uuid4().hex[:8]}")
    _login(client, OTHER_EMAIL, OTHER_PASSWORD)
    foreign_control = _control(client, f"Other {uuid.uuid4().hex[:8]}")
    session = _db()
    try:
        foreign_evidence = _evidence(
            session, actors["other_workspace_id"], approval="approved", document_id=None
        )
        session.add(
            ControlEvidenceLink(
                control_id=foreign_control["id"], evidence_id=foreign_evidence, verified=False
            )
        )
        own_evidence = _evidence(
            session, actors["workspace_id"], approval="approved", document_id=None
        )
        session.commit()
        foreign_link = session.execute(
            text("SELECT id FROM control_evidence_links WHERE control_id = :c"),
            {"c": foreign_control["id"]},
        ).scalar()
    finally:
        session.close()
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    missing_control = 999999991
    missing_evidence = 999999992
    missing_link = 999999993

    def same(method: str, missing_path: str, foreign_path: str, body: dict | None, detail: str):
        missing = _call(client, method, missing_path, body)
        foreign = _call(client, method, foreign_path, body)
        assert missing.status_code == 404, missing.text
        assert foreign.status_code == 404, foreign.text
        assert missing.json() == foreign.json()
        assert missing.json() == {"detail": detail}

    control_calls = [
        ("GET", "/api/compliance/controls/{id}", None),
        ("PATCH", "/api/compliance/controls/{id}", {"status": "in_progress"}),
        ("POST", "/api/compliance/controls/{id}/verify", None),
        (
            "POST",
            "/api/compliance/controls/{id}/evidence/accept-suggested",
            {"chunk_id": 1},
        ),
        ("GET", "/api/compliance/controls/{id}/evidence", None),
        ("POST", "/api/compliance/controls/{id}/evidence", {"evidence_id": own_evidence}),
        (
            "PATCH",
            "/api/compliance/controls/{id}/evidence/1",
            {"verified": False},
        ),
        ("DELETE", "/api/compliance/controls/{id}/evidence/1", None),
    ]
    for method, path, body in control_calls:
        same(
            method,
            path.format(id=missing_control),
            path.format(id=foreign_control["id"]),
            body,
            "Control not found",
        )
    missing_evidence_response = client.post(
        f"/api/compliance/controls/{created['id']}/evidence",
        json={"evidence_id": missing_evidence},
    )
    foreign_evidence_response = client.post(
        f"/api/compliance/controls/{created['id']}/evidence",
        json={"evidence_id": foreign_evidence},
    )
    assert missing_evidence_response.status_code == 404
    assert missing_evidence_response.json() == foreign_evidence_response.json()
    assert missing_evidence_response.json() == {"detail": "Evidence not found"}
    for method, body in (
        ("PATCH", {"verified": False}),
        ("DELETE", None),
    ):
        same(
            method,
            f"/api/compliance/controls/{created['id']}/evidence/{missing_link}",
            f"/api/compliance/controls/{created['id']}/evidence/{foreign_link}",
            body,
            "Link not found",
        )


def test_link_commit_failure_inserts_nothing(client):
    actors = _actors()
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    created = _control(client, f"Partial {uuid.uuid4().hex[:8]}")
    session = _db()
    try:
        evidence_id = _evidence(
            session, actors["workspace_id"], approval="approved", document_id=None
        )
        session.commit()
    finally:
        session.close()
    before_links = _table_count("control_evidence_links")
    before_evidence = _table_count("evidence_items")

    def fail_commit(self, *args, **kwargs):
        raise RuntimeError("forced commit failure")

    quiet = TestClient(
        app, base_url=TEST_ORIGIN, headers=TEST_HEADERS, raise_server_exceptions=False
    )
    _login(quiet, ADMIN_EMAIL, ADMIN_PASSWORD)
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(Session, "commit", fail_commit)
        failed = quiet.post(
            f"/api/compliance/controls/{created['id']}/evidence",
            json={"evidence_id": evidence_id},
        )
    assert failed.status_code == 500, failed.text
    assert _table_count("control_evidence_links") == before_links
    assert _table_count("evidence_items") == before_evidence


def _link_tuples(session: Session, control_id: int, evidence_id: int) -> list[tuple]:
    rows = session.execute(
        text(
            "SELECT id, control_id, evidence_id, confidence_score, verified, "
            "last_verified_at, created_at FROM control_evidence_links "
            "WHERE control_id = :c AND evidence_id = :e ORDER BY id"
        ),
        {"c": control_id, "e": evidence_id},
    ).fetchall()
    return [tuple(row) for row in rows]


def _hold_tuples(session: Session, control_id: int, evidence_id: int) -> list[tuple]:
    rows = session.execute(
        text(
            "SELECT link_id, control_id, evidence_id, confidence_score, verified, "
            "last_verified_at, created_at FROM tc21003_link_hold "
            "WHERE control_id = :c AND evidence_id = :e ORDER BY link_id"
        ),
        {"c": control_id, "e": evidence_id},
    ).fetchall()
    return [tuple(row) for row in rows]


def test_migration_round_trip_restores_duplicate_links():
    """Seed duplicate links, then upgrade, downgrade, and upgrade tc21003."""
    import importlib.util

    before_counts = _counts()
    before_ids = _ids()
    actors = _actors()
    path = os.path.join(API_ROOT, "alembic", "versions", "081_tc21003_evidence_link_uniq.py")
    spec = importlib.util.spec_from_file_location("tc21003_mig", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == REVISION
    assert mod.down_revision == PARENT
    assert "app." not in open(path, encoding="utf-8").read()
    env = {**os.environ, "DATABASE_URL": os.environ["DATABASE_URL"]}
    control_id = None
    evidence_id = None

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
            if control_id is not None:
                session.execute(
                    text("DELETE FROM tc21003_link_hold WHERE control_id = :c"),
                    {"c": control_id},
                )
                session.execute(
                    text("DELETE FROM control_evidence_links WHERE control_id = :c"),
                    {"c": control_id},
                )
                session.execute(
                    text("DELETE FROM workspace_controls WHERE id = :c"),
                    {"c": control_id},
                )
            if evidence_id is not None:
                session.execute(
                    text("DELETE FROM evidence_items WHERE id = :e"),
                    {"e": evidence_id},
                )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    try:
        try:
            # The index is already present at head, so drop it only long enough to seed.
            alembic("downgrade", PARENT)
            session = _db()
            try:
                _sync_sequence(session, "workspace_controls")
                control = WorkspaceControl(
                    workspace_id=actors["workspace_id"],
                    status="not_implemented",
                    custom_name=f"Dup {uuid.uuid4().hex[:8]}",
                )
                session.add(control)
                session.flush()
                _sync_sequence(session, "evidence_items")
                evidence = EvidenceItem(
                    workspace_id=actors["workspace_id"],
                    source_type="manual",
                    title="Dup evidence",
                    approval_status="approved",
                )
                session.add(evidence)
                session.flush()
                control_id = control.id
                evidence_id = evidence.id
                session.execute(
                    text(
                        "INSERT INTO control_evidence_links "
                        "(control_id, evidence_id, confidence_score, verified, "
                        "last_verified_at, created_at) VALUES "
                        "(:c, :e, 0.25, false, NULL, :oldest_at), "
                        "(:c, :e, 0.75, true, :verified_at, :newer_at)"
                    ),
                    {
                        "c": control_id,
                        "e": evidence_id,
                        "oldest_at": datetime(2020, 1, 1, 0, 0, 0),
                        "verified_at": datetime(2021, 6, 7, 8, 9, 10),
                        "newer_at": datetime(2021, 6, 7, 8, 0, 0),
                    },
                )
                session.commit()
                seeded = _link_tuples(session, control_id, evidence_id)
            finally:
                session.close()
            assert len(seeded) == 2
            duplicate = seeded[1:]
            alembic("upgrade", REVISION)
            session = _db()
            try:
                assert _link_tuples(session, control_id, evidence_id) == seeded[:1]
                assert _hold_tuples(session, control_id, evidence_id) == duplicate
                with pytest.raises(IntegrityError):
                    session.execute(
                        text(
                            "INSERT INTO control_evidence_links "
                            "(control_id, evidence_id, verified, created_at) "
                            "VALUES (:c, :e, false, :created_at)"
                        ),
                        {
                            "c": control_id,
                            "e": evidence_id,
                            "created_at": datetime(2022, 1, 1, 0, 0, 0),
                        },
                    )
                    session.commit()
                session.rollback()
            finally:
                session.close()
            alembic("downgrade", PARENT)
            session = _db()
            try:
                gone = session.execute(
                    text("SELECT to_regclass('public.tc21003_link_hold')")
                ).scalar()
                assert gone is None
                assert _link_tuples(session, control_id, evidence_id) == seeded
            finally:
                session.close()
            alembic("upgrade", REVISION)
            session = _db()
            try:
                assert _link_tuples(session, control_id, evidence_id) == seeded[:1]
                assert _hold_tuples(session, control_id, evidence_id) == duplicate
            finally:
                session.close()
            heads = [line.strip() for line in alembic("heads").splitlines() if "(head)" in line]
            assert len(heads) == 1
            from tests.release.test_billing_provider import _revision_is_applied, _revision_token

            assert _revision_is_applied(_revision_token(alembic("heads")), REVISION)
        finally:
            alembic("upgrade", "head")
            wipe()
            _delete_created(before_ids, skip=("tc21003_link_hold",))
    finally:
        after_counts = _counts()
        assert after_counts == before_counts, {"before": before_counts, "after": after_counts}
        print(f"TC21003_COUNTS before={before_counts} after={after_counts}")
