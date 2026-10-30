"""TC-07-002: signing_key_id downgrades to its parent and upgrades again.

The round trip uses a database of its own, the same shape as the parent-move
test. It does not touch the shared test database.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine, text

API_ROOT = Path(__file__).resolve().parents[2]
REVISION = "tc07002_session_key_id"
PARENT = "tc19010_inbox_receipts"
FRESH_NAME = "tc07002_signing_key_roundtrip_test"


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
        fresh_engine.dispose()
        fresh_engine = None
        _ok(_alembic("downgrade", PARENT, database_url=fresh))
        fresh_engine = create_engine(fresh)
        with fresh_engine.connect() as conn:
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
        fresh_engine.dispose()
        fresh_engine = None
        _ok(_alembic("upgrade", "head", database_url=fresh))
        fresh_engine = create_engine(fresh)
        with fresh_engine.connect() as conn:
            restored = conn.execute(
                text("SELECT session_id, signing_key_id FROM user_sessions WHERE id = :id"),
                {"id": session_id},
            ).one()
            assert restored.session_id == "synthetic-example-session"
            assert restored.signing_key_id is None
        fresh_engine.dispose()
        fresh_engine = None
        heads = _alembic("heads", database_url=fresh)
        _ok(heads)
        head_lines = [line for line in heads.stdout.splitlines() if "(head)" in line]
        assert head_lines == [f"{REVISION} (head)"]
        current = _alembic("current", database_url=fresh)
        _ok(current)
        assert REVISION in current.stdout
        assert "(head)" in current.stdout
    finally:
        if fresh_engine is not None:
            fresh_engine.dispose()
        admin_engine = create_engine(admin, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {FRESH_NAME} WITH (FORCE)"))
        admin_engine.dispose()
