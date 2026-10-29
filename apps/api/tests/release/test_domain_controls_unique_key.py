"""TC-21-002a unique canonical key and verified-status sync.

Runs on PostgreSQL. Control labels are synthetic, not framework text.
"""

import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.models import Control, ControlEvidenceLink, EvidenceItem, WorkspaceControl
from app.services.control_contract import upsert_legacy_control
from tests.release.test_domain_controls import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    REVIEWER_EMAIL,
    REVIEWER_PASSWORD,
    _actors,
    _create,
    _fresh,
    _login,
    _sync_sequence,
)

API_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
PARENT = "tc21002_control_contract"
REVISION = "tc21002a_canonical_uniq"


def _indexes(session, table: str) -> set[str]:
    rows = session.execute(
        __import__("sqlalchemy").text("SELECT indexname FROM pg_indexes WHERE tablename = :table"),
        {"table": table},
    ).fetchall()
    return {row[0] for row in rows}


def test_reviewer_verify_syncs_verified_status_and_get_stays_read_only(client):
    actors = _actors()
    _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    created = _create(client, f"C-ver-{uuid.uuid4().hex[:8]}")
    session = _fresh()
    try:
        legacy = session.query(Control).filter(Control.id == created["id"]).one()
        workspace_id = legacy.workspace_control_id
        _sync_sequence(session, "evidence_items")
        evidence = EvidenceItem(
            workspace_id=actors["workspace_id"],
            source_type="manual",
            title="Synthetic evidence",
        )
        session.add(evidence)
        session.flush()
        session.add(
            ControlEvidenceLink(
                control_id=workspace_id,
                evidence_id=evidence.id,
                verified=False,
            )
        )
        session.commit()
    finally:
        session.close()

    _login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    refused = client.get(f"/api/compliance/controls/{workspace_id}")
    assert refused.status_code == 200
    verified = client.post(f"/api/compliance/controls/{workspace_id}/verify")
    assert verified.status_code == 200, verified.text
    body = verified.json()
    assert body["status"] == "verified"
    assert body["canonical"]["lifecycle"] == "verified"

    session = _fresh()
    try:
        legacy = session.query(Control).filter(Control.id == created["id"]).one()
        assert legacy.lifecycle == "verified"
        assert legacy.status == "implemented"
        workspace = (
            session.query(WorkspaceControl).filter(WorkspaceControl.id == workspace_id).one()
        )
        assert workspace.status == "verified"
        assert workspace.lifecycle == "verified"
        before = (legacy.updated_at, workspace.updated_at)
    finally:
        session.close()

    assert client.get(f"/api/compliance/controls/{workspace_id}").status_code == 200
    assert client.get("/api/controls").status_code == 200
    session = _fresh()
    try:
        legacy = session.query(Control).filter(Control.id == created["id"]).one()
        workspace = (
            session.query(WorkspaceControl).filter(WorkspaceControl.id == workspace_id).one()
        )
        assert (legacy.updated_at, workspace.updated_at) == before
    finally:
        session.close()

    _login(client, "tc21002-other@trust.local", "test-o")
    missing = client.post(f"/api/compliance/controls/{workspace_id}/verify")
    assert missing.status_code == 404
    missing_get = client.get(f"/api/compliance/controls/{workspace_id}")
    assert missing_get.status_code == 404


def test_duplicate_canonical_key_is_rejected_and_concurrent_upsert_keeps_one_row():
    _actors()
    key = f"TC21002A:C-{uuid.uuid4().hex[:8]}"
    session = _fresh()
    try:
        workspace_id = session.execute(
            __import__("sqlalchemy").text("SELECT id FROM workspaces WHERE slug = 'tc21002'")
        ).scalar()
        indexes = _indexes(session, "controls")
        assert "uq_controls_ws_canonical_key" in indexes
        assert "uq_ws_controls_ws_canonical_key" in _indexes(session, "workspace_controls")
        session.execute(
            __import__("sqlalchemy").text(
                "INSERT INTO controls (workspace_id, framework, control_id, status, canonical_key) "
                "VALUES (:ws, 'TC21002A', 'kept', 'in_review', :key)"
            ),
            {"ws": workspace_id, "key": key},
        )
        session.commit()
        with pytest.raises(IntegrityError):
            session.execute(
                __import__("sqlalchemy").text(
                    "INSERT INTO controls (workspace_id, framework, control_id, status, canonical_key) "
                    "VALUES (:ws, 'TC21002A', 'dup', 'in_review', :key)"
                ),
                {"ws": workspace_id, "key": key},
            )
            session.commit()
        session.rollback()
        session.execute(
            __import__("sqlalchemy").text(
                "INSERT INTO controls (workspace_id, framework, control_id, status, canonical_key) "
                "VALUES (:ws, 'TC21002A', 'null-a', 'in_review', NULL), "
                "(:ws, 'TC21002A', 'null-b', 'in_review', NULL)"
            ),
            {"ws": workspace_id},
        )
        session.commit()
    finally:
        session.close()

    def once():
        db = SessionLocal()
        try:
            return upsert_legacy_control(
                db,
                workspace_id=workspace_id,
                framework="TC21002A",
                control_key=f"race-{key.split(':', 1)[1]}",
                name="Synthetic",
                legacy_status="in_review",
                owner_user_id=None,
                owner_team=None,
            )
        finally:
            db.close()

    race_key = f"TC21002A:race-{key.split(':', 1)[1]}"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: once(), (1, 2)))
    assert [item.http_status for item in results] == [200, 200]
    session = _fresh()
    try:
        count = session.execute(
            __import__("sqlalchemy").text(
                "SELECT count(*) FROM controls WHERE workspace_id = :ws AND canonical_key = :key"
            ),
            {"ws": workspace_id, "key": race_key},
        ).scalar()
        assert count == 1
    finally:
        session.close()


def test_migration_clears_only_duplicate_keys_and_downgrade_restores_them():
    actors = _actors()
    import importlib.util

    from app.core.database import engine

    path = os.path.join(API_ROOT, "alembic", "versions", "080_tc21002a_canonical_key_uniq.py")
    spec = importlib.util.spec_from_file_location("tc21002a_mig", path)
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

    key = f"TC21002A:dup-{uuid.uuid4().hex[:8]}"
    alembic("downgrade", PARENT)
    session = _fresh()
    try:
        session.execute(
            __import__("sqlalchemy").text(
                "INSERT INTO controls (workspace_id, framework, control_id, name, status, canonical_key) "
                "VALUES (:ws, 'TC21002A', 'old', 'Oldest', 'in_review', :key), "
                "(:ws, 'TC21002A', 'new', 'Later', 'na', :key)"
            ),
            {"ws": actors["workspace_id"], "key": key},
        )
        session.commit()
        ids = session.execute(
            __import__("sqlalchemy").text(
                "SELECT id, name FROM controls WHERE canonical_key = :key ORDER BY id"
            ),
            {"key": key},
        ).fetchall()
    finally:
        session.close()
    try:
        alembic("upgrade", "head")
        engine.dispose()
        session = _fresh()
        try:
            rows = session.execute(
                __import__("sqlalchemy").text(
                    "SELECT id, name, status, canonical_key FROM controls WHERE id = ANY(:ids) ORDER BY id"
                ),
                {"ids": [row.id for row in ids]},
            ).fetchall()
            assert rows[0].canonical_key == key
            assert rows[0].name == "Oldest"
            assert rows[1].canonical_key is None
            assert rows[1].name == "Later"
            assert rows[1].status == "na"
        finally:
            session.close()
        alembic("downgrade", PARENT)
        session = _fresh()
        try:
            restored = session.execute(
                __import__("sqlalchemy").text("SELECT canonical_key FROM controls WHERE id = :id"),
                {"id": ids[1].id},
            ).scalar()
            assert restored == key
        finally:
            session.close()
    finally:
        alembic("upgrade", "head")
    heads = [line.strip() for line in alembic("heads").splitlines() if "(head)" in line]
    assert len(heads) == 1
    assert REVISION in heads[0]
