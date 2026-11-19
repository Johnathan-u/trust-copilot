"""TC-05-001c: mfa_satisfied defaults false and does not survive a downgrade."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect, text

API_ROOT = Path(__file__).resolve().parents[2]
REVISION = "tc05001c_mfa_satisfied"
PARENT = "tc17001_article_versions"


def _revisions() -> dict[str, str | None]:
    found: dict[str, str | None] = {}
    for path in (API_ROOT / "alembic" / "versions").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        revision = down = None
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "revision" in names and isinstance(node.value, ast.Constant):
                revision = node.value.value
            if "down_revision" in names and isinstance(node.value, ast.Constant):
                down = node.value.value
        if isinstance(revision, str):
            found[revision] = down if isinstance(down, str) else None
    return found


@pytest.mark.unit
def test_mfa_satisfied_revision_is_the_only_head():
    revisions = _revisions()
    assert revisions[REVISION] == PARENT
    heads = [revision for revision in revisions if revision not in set(revisions.values())]
    assert heads == [REVISION]


@pytest.fixture
def migration_db():
    path = API_ROOT / "alembic/versions/tc05001c_mfa_satisfied.py"
    spec = importlib.util.spec_from_file_location("mfa_satisfied_migration_under_test", path)
    assert spec is not None and spec.loader is not None
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
                user_agent VARCHAR(512), ip_address VARCHAR(64),
                signing_key_id VARCHAR(64)
            )
        """)
        )
        connection.execute(
            text("""
            INSERT INTO user_sessions (id, user_id, session_id, signing_key_id)
            VALUES (1, 10, 'challenged-later', 'v1'),
                   (2, 11, 'password-only', NULL)
        """)
        )

    def migrate(direction):
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                getattr(migration, direction)()

    try:
        yield engine, migrate
    finally:
        engine.dispose()


def _flag(connection, session_id: str):
    return connection.execute(
        text("SELECT mfa_satisfied FROM user_sessions WHERE session_id = :sid"),
        {"sid": session_id},
    ).scalar_one()


def _false(value) -> bool:
    return value in (0, False)


@pytest.mark.unit
def test_upgrade_downgrade_upgrade_fails_closed(migration_db):
    engine, migrate = migration_db
    migrate("upgrade")
    with engine.begin() as connection:
        assert _false(_flag(connection, "challenged-later"))
        assert _false(_flag(connection, "password-only"))
        connection.execute(
            text("UPDATE user_sessions SET mfa_satisfied = 1 WHERE session_id = 'challenged-later'")
        )
        connection.execute(
            text(
                "INSERT INTO user_sessions (user_id, session_id) VALUES (12, 'inserted-after-upgrade')"
            )
        )
        assert _false(_flag(connection, "inserted-after-upgrade"))
        kept = connection.execute(
            text("SELECT session_id, signing_key_id FROM user_sessions WHERE id = 1")
        ).one()
        assert tuple(kept) == ("challenged-later", "v1")
    migrate("downgrade")
    with engine.connect() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("user_sessions")}
        assert "mfa_satisfied" not in columns
        assert connection.execute(text("SELECT COUNT(*) FROM user_sessions")).scalar_one() == 3
        assert (
            connection.execute(
                text("SELECT signing_key_id FROM user_sessions WHERE id = 1")
            ).scalar_one()
            == "v1"
        )
    migrate("upgrade")
    with engine.connect() as connection:
        assert _false(_flag(connection, "challenged-later"))
        assert _false(_flag(connection, "password-only"))
        assert _false(_flag(connection, "inserted-after-upgrade"))
