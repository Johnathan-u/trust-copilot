"""TC-07-002: exercise the actual migration and an isolated PostgreSQL round trip."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import DatabaseError

API_ROOT = Path(__file__).resolve().parents[2]
REVISION = "tc07002_session_key_id"
PARENT = "tc19010_inbox_receipts"
FRESH_NAME = "tc07002_signing_key_roundtrip_test"
ARCHIVE = "tc07002_session_key_archive"


@pytest.fixture
def migration_db():
    path = API_ROOT / "alembic/versions/085_tc07002_session_signing_key.py"
    spec = importlib.util.spec_from_file_location("signing_key_migration_under_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def explicit_transactions(connection, _record):
        connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN")

    with engine.begin() as connection:
        connection.execute(
            text("""
            CREATE TABLE user_sessions (
                id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
                session_id VARCHAR(64) NOT NULL UNIQUE, created_at TIMESTAMP,
                user_agent VARCHAR(512), ip_address VARCHAR(64)
            )
        """)
        )

    def migrate(direction):
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                getattr(migration, direction)()

    migrate("upgrade")
    try:
        yield engine, migrate
    finally:
        engine.dispose()


def _seed_sessions(engine, created_at="2026-10-30 10:00:00.000001"):
    with engine.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO user_sessions (id, user_id, session_id, created_at, signing_key_id)
            VALUES (1, 10, 'original-session', :created_at, 'v1'),
                   (2, 10, 'legacy-session', NULL, NULL)
        """),
            {"created_at": created_at},
        )


@pytest.mark.unit
@pytest.mark.parametrize("created_at", [None, "2026-10-30 10:00:00.000001"])
def test_actual_migration_preserves_nondefault_key_and_null_sessions(migration_db, created_at):
    engine, migrate = migration_db
    _seed_sessions(engine, created_at)
    migrate("downgrade")
    with engine.connect() as connection:
        assert "signing_key_id" not in {
            column["name"] for column in inspect(connection).get_columns("user_sessions")
        }
    migrate("upgrade")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT id, signing_key_id FROM user_sessions ORDER BY id")
        ).all() == [(1, "v1"), (2, None)]
        assert connection.execute(text(f"SELECT COUNT(*) FROM {ARCHIVE}")).scalar_one() == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    "change", ["delete", "new-token", "new-owner", "new-created-at", "reassign"]
)
def test_changed_or_deleted_session_cannot_inherit_archived_key(migration_db, change):
    engine, migrate = migration_db
    _seed_sessions(engine)
    migrate("downgrade")
    with engine.begin() as connection:
        if change == "reassign":
            connection.execute(text("UPDATE user_sessions SET user_id = 11 WHERE id = 1"))
        else:
            connection.execute(text("DELETE FROM user_sessions WHERE id = 1"))
            if change != "delete":
                connection.execute(
                    text("""
                    INSERT INTO user_sessions (id, user_id, session_id, created_at)
                    VALUES (1, :owner, :token, :created_at)
                """),
                    {
                        "owner": 11 if change == "new-owner" else 10,
                        "token": "replacement-session"
                        if change == "new-token"
                        else "original-session",
                        "created_at": "2026-10-30 11:00:00"
                        if change == "new-created-at"
                        else "2026-10-30 10:00:00.000001",
                    },
                )
        connection.execute(
            text(
                "INSERT INTO user_sessions (id, user_id, session_id) VALUES (3, 10, 'new-session')"
            )
        )
    migrate("upgrade")
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id, signing_key_id FROM user_sessions ORDER BY id")
        ).all()
        assert rows == (
            [(2, None), (3, None)] if change == "delete" else [(1, None), (2, None), (3, None)]
        )
        assert connection.execute(
            text(f"SELECT id, user_id, session_id, signing_key_id FROM {ARCHIVE}")
        ).all() == [(1, 10, "original-session", "v1")]


@pytest.mark.unit
def test_repeated_cycles_keep_current_keys_and_unmatched_archive(migration_db):
    engine, migrate = migration_db
    _seed_sessions(engine)
    migrate("downgrade")
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE user_sessions SET session_id = 'replacement-session' WHERE id = 1")
        )
    migrate("upgrade")
    with engine.begin() as connection:
        connection.execute(text("UPDATE user_sessions SET signing_key_id = 'v2' WHERE id = 1"))
    for _ in range(2):
        migrate("downgrade")
        migrate("upgrade")
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT signing_key_id FROM user_sessions WHERE id = 1")
                ).scalar_one()
                == "v2"
            )
            assert connection.execute(
                text(f"SELECT session_id, signing_key_id FROM {ARCHIVE}")
            ).all() == [("original-session", "v1")]


@pytest.mark.unit
def test_failed_restore_keeps_archive_for_retry(migration_db):
    engine, migrate = migration_db
    _seed_sessions(engine)
    migrate("downgrade")
    with engine.begin() as connection:
        connection.execute(
            text("""
            CREATE TRIGGER reject_restore BEFORE UPDATE ON user_sessions
            BEGIN SELECT RAISE(ABORT, 'synthetic restore failure'); END
        """)
        )
    with pytest.raises(DatabaseError, match="synthetic restore failure"):
        migrate("upgrade")
    with engine.begin() as connection:
        assert (
            connection.execute(text(f"SELECT signing_key_id FROM {ARCHIVE}")).scalar_one() == "v1"
        )
        assert "signing_key_id" not in {
            column["name"] for column in inspect(connection).get_columns("user_sessions")
        }
        connection.execute(text("DROP TRIGGER reject_restore"))
    migrate("upgrade")
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT signing_key_id FROM user_sessions WHERE id = 1")
            ).scalar_one()
            == "v1"
        )


def _alembic(*args: str, database_url: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "TRUST_COPILOT_TESTING": "1", "DATABASE_URL": database_url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(API_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _safe(output: str) -> str:
    redacted = re.sub(r"postgresql://\S+", "postgresql://redacted", output or "")
    return redacted[-500:]


def _ok(proc: subprocess.CompletedProcess) -> None:
    assert proc.returncode == 0, _safe(proc.stderr or proc.stdout)


def test_signing_key_column_round_trips_on_a_fresh_database() -> None:
    source = os.environ["DATABASE_URL"]
    parsed = urlparse(source)
    admin = urlunparse(parsed._replace(path="/postgres"))
    fresh = urlunparse(parsed._replace(path=f"/{FRESH_NAME}"))
    admin_engine = create_engine(admin, isolation_level="AUTOCOMMIT")
    fresh_engine = None
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {FRESH_NAME} WITH (FORCE)"))
            conn.execute(text(f"CREATE DATABASE {FRESH_NAME}"))
        admin_engine.dispose()
        _ok(_alembic("upgrade", "head", database_url=fresh))
        fresh_engine = create_engine(fresh)
        with fresh_engine.begin() as conn:
            user_id = conn.execute(
                text(
                    "INSERT INTO users (email, password_hash, display_name, email_verified) "
                    "VALUES ('synthetic-example-roundtrip@example.com', "
                    "'synthetic-example-hash', 'synthetic example', true) "
                    "RETURNING id"
                )
            ).scalar_one()
            session_id = conn.execute(
                text(
                    "INSERT INTO user_sessions (user_id, session_id, signing_key_id) "
                    "VALUES (:user_id, 'synthetic-example-session', 'v1') RETURNING id"
                ),
                {"user_id": user_id},
            ).scalar_one()
            replaced_id = conn.execute(
                text(
                    "INSERT INTO user_sessions (user_id, session_id, signing_key_id) "
                    "VALUES (:user_id, 'removed-session', 'retired') RETURNING id"
                ),
                {"user_id": user_id},
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO user_sessions (user_id, session_id) VALUES (:user_id, 'legacy-session')"
                ),
                {"user_id": user_id},
            )
        fresh_engine.dispose()
        fresh_engine = None
        _ok(_alembic("downgrade", PARENT, database_url=fresh))
        fresh_engine = create_engine(fresh)
        with fresh_engine.begin() as conn:
            columns = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'user_sessions'"
                    )
                )
            }
            assert "signing_key_id" not in columns
            kept = conn.execute(
                text("SELECT user_id, session_id FROM user_sessions WHERE id = :id"),
                {"id": session_id},
            ).one()
            assert kept.user_id == user_id
            assert kept.session_id == "synthetic-example-session"
            conn.execute(text("DELETE FROM user_sessions WHERE id = :id"), {"id": replaced_id})
            conn.execute(
                text(
                    "INSERT INTO user_sessions (id, user_id, session_id) VALUES (:id, :user_id, 'replacement-session')"
                ),
                {"id": replaced_id, "user_id": user_id},
            )
            conn.execute(
                text(
                    "INSERT INTO user_sessions (user_id, session_id) VALUES (:user_id, 'downgraded-session')"
                ),
                {"user_id": user_id},
            )
        fresh_engine.dispose()
        fresh_engine = None
        _ok(_alembic("upgrade", "head", database_url=fresh))
        fresh_engine = create_engine(fresh)
        with fresh_engine.begin() as conn:
            restored = conn.execute(
                text("SELECT session_id, signing_key_id FROM user_sessions WHERE id = :id"),
                {"id": session_id},
            ).one()
            assert restored.session_id == "synthetic-example-session"
            assert restored.signing_key_id == "v1"
            assert (
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM user_sessions WHERE id <> :id AND signing_key_id IS NOT NULL"
                    ),
                    {"id": session_id},
                ).scalar_one()
                == 0
            )
            assert conn.execute(
                text(f"SELECT session_id, signing_key_id FROM {ARCHIVE}")
            ).all() == [("removed-session", "retired")]
            conn.execute(
                text("UPDATE user_sessions SET signing_key_id = 'v2' WHERE id = :id"),
                {"id": session_id},
            )
        fresh_engine.dispose()
        fresh_engine = None
        _ok(_alembic("downgrade", PARENT, database_url=fresh))
        _ok(_alembic("upgrade", "head", database_url=fresh))
        fresh_engine = create_engine(fresh)
        with fresh_engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT signing_key_id FROM user_sessions WHERE id = :id"),
                    {"id": session_id},
                ).scalar_one()
                == "v2"
            )
            assert conn.execute(text("SELECT COUNT(*) FROM user_sessions")).scalar_one() == 4
            assert conn.execute(
                text(f"SELECT session_id, signing_key_id FROM {ARCHIVE}")
            ).all() == [("removed-session", "retired")]
        fresh_engine.dispose()
        fresh_engine = None
        heads = _alembic("heads", database_url=fresh)
        _ok(heads)
        head_lines = [line for line in heads.stdout.splitlines() if "(head)" in line]
        assert len(head_lines) == 1
        head_revision = head_lines[0].split()[0]
        current = _alembic("current", database_url=fresh)
        _ok(current)
        assert head_revision in current.stdout
        assert "(head)" in current.stdout
    finally:
        if fresh_engine is not None:
            fresh_engine.dispose()
        admin_engine = create_engine(admin, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {FRESH_NAME} WITH (FORCE)"))
        admin_engine.dispose()
