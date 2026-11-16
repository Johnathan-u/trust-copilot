"""TC-17-005a migration hashes existing share tokens and downgrade is lossy.

The chain stays a single head. Parent is question_cell_mapping. Re-upgrade cannot
rebuild a raw token that downgrade already discarded.
"""

import hashlib
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

API_ROOT = Path(__file__).resolve().parents[2]
REVISION = "tc17005a_share_token"
PARENT = "question_cell_mapping"


def _alembic(*args: str) -> str:
    env = {**os.environ, "DATABASE_URL": os.environ["DATABASE_URL"]}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:] + result.stdout[-2000:]
    return result.stdout


def _heads() -> list[str]:
    script = ScriptDirectory.from_config(Config(str(API_ROOT / "alembic.ini")))
    return list(script.get_heads())


def test_revision_is_the_single_head():
    script = ScriptDirectory.from_config(Config(str(API_ROOT / "alembic.ini")))
    revision = script.get_revision(REVISION)
    assert revision is not None
    assert isinstance(revision.down_revision, str)
    assert revision.down_revision == PARENT
    assert _heads() == [REVISION]
    source = (API_ROOT / "alembic" / "versions" / "tc17005a_share_token.py").read_text()
    assert "import app" not in source and "from app" not in source


def test_upgrade_hashes_plaintext_and_downgrade_cannot_restore_it(migrated_db):
    if not migrated_db:
        pytest.skip("Postgres test DB unavailable")
    stamp = datetime(2027, 4, 2, 15, 30, 0)
    active_token = "synthetic-active-share-token"
    inactive_token = "synthetic-inactive-share-token"
    ids: list[int] = []
    engine = create_engine(os.environ["DATABASE_URL"])

    def run(statement, **params):
        engine.dispose()
        with engine.begin() as conn:
            result = conn.execute(text(statement), params)
            if not result.returns_rows:
                return None
            return result.mappings().all()

    def columns():
        engine.dispose()
        return {column["name"] for column in inspect(engine).get_columns("shareable_spaces")}

    def one(space_id):
        rows = run(
            "SELECT access_token, token_hash, is_active, expires_at "
            "FROM shareable_spaces WHERE id = :id",
            id=space_id,
        )
        assert rows and len(rows) == 1
        return rows[0]

    def insert(name, token, active, expires):
        rows = run(
            """
            INSERT INTO shareable_spaces (
                workspace_id, name, access_token, is_active, expires_at,
                created_at, updated_at
            ) VALUES (
                1, :name, :token, :active, :expires, :now, :now
            ) RETURNING id
            """,
            name=name,
            token=token,
            active=active,
            expires=expires,
            now=stamp,
        )
        space_id = rows[0]["id"]
        ids.append(space_id)
        return space_id

    try:
        _alembic("downgrade", PARENT)
        assert "token_hash" not in columns()
        active_id = insert("tc17005a-active", active_token, True, stamp)
        inactive_id = insert("tc17005a-inactive", inactive_token, False, None)
        empty_id = insert("tc17005a-empty", None, True, None)

        _alembic("upgrade", REVISION)
        assert "token_hash" in columns()
        active = one(active_id)
        assert active["access_token"] is None
        assert active["token_hash"] == hashlib.sha256(active_token.encode()).hexdigest()
        assert active["is_active"] is True
        assert active["expires_at"] == stamp
        inactive = one(inactive_id)
        assert inactive["access_token"] is None
        assert inactive["is_active"] is False
        assert inactive["expires_at"] is None
        assert inactive["token_hash"] == hashlib.sha256(inactive_token.encode()).hexdigest()
        empty = one(empty_id)
        assert empty["access_token"] is None and empty["token_hash"] is None
        assert empty["is_active"] is True

        _alembic("downgrade", PARENT)
        assert "token_hash" not in columns()
        parked_active = run(
            "SELECT access_token, is_active, expires_at FROM shareable_spaces WHERE id = :id",
            id=active_id,
        )[0]
        parked_inactive = run(
            "SELECT access_token, is_active, expires_at FROM shareable_spaces WHERE id = :id",
            id=inactive_id,
        )[0]
        assert parked_active["access_token"] is None
        assert parked_active["is_active"] is True and parked_active["expires_at"] == stamp
        assert parked_inactive["access_token"] is None
        assert parked_inactive["is_active"] is False and parked_inactive["expires_at"] is None

        _alembic("upgrade", "head")
        restored = one(active_id)
        assert restored["access_token"] is None and restored["token_hash"] is None
        assert restored["is_active"] is True and restored["expires_at"] == stamp
    finally:
        _alembic("upgrade", "head")
        for space_id in ids:
            run("DELETE FROM shareable_spaces WHERE id = :id", id=space_id)
        engine.dispose()
    heads = _alembic("heads")
    assert heads.strip().splitlines() == [f"{REVISION} (head)"]
    assert _heads() == [REVISION]
