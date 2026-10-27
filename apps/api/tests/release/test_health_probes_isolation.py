"""TC-02-BUG-014 release check: tests/release/test_health_probes.py passes on its own.

The workerz tests used to rely on another test (or the TC_REQUIRE_DB=1 session hook) having run the
migrations first. This check creates a throwaway, never-migrated local ``*_test`` database next to
the configured one, runs only that file in a child pytest with TC_REQUIRE_DB unset (so nothing
pre-migrates), then drops the database. Synthetic data only; local test Postgres only.
"""

from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy
from sqlalchemy import text
from sqlalchemy.engine import make_url

from tests import _safety

API_DIR = Path(__file__).resolve().parents[2]
TARGET = "tests/release/test_health_probes.py"


def _admin_engine(url: str):
    return sqlalchemy.create_engine(url, isolation_level="AUTOCOMMIT")


@pytest.fixture
def fresh_test_db_url():
    base = make_url(_safety.validate_test_database_url(os.environ["DATABASE_URL"]))
    name = f"tc_iso_{secrets.token_hex(4)}_test"
    # Yield a sqlalchemy URL: its repr masks the password if pytest prints the fixture value.
    url = base.set(database=name)
    _safety.validate_test_database_url(url.render_as_string(hide_password=False))
    admin = _admin_engine(base.render_as_string(hide_password=False))
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except Exception as exc:  # no server / no CREATEDB privilege
        admin.dispose()
        msg = f"cannot create a throwaway test database: {type(exc).__name__}"
        if os.environ.get("TC_REQUIRE_DB") == "1":
            pytest.fail(f"TC_REQUIRE_DB=1: {msg}")
        pytest.skip(msg)
    try:
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def test_health_probes_file_passes_alone_on_fresh_db(fresh_test_db_url):
    dsn = fresh_test_db_url.render_as_string(hide_password=False)
    eng = sqlalchemy.create_engine(dsn)
    try:
        with eng.connect() as conn:
            tables = conn.execute(
                text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
            ).scalar()
    finally:
        eng.dispose()
    assert tables == 0, "throwaway database is not fresh"

    env = {
        **os.environ,
        "DATABASE_URL": dsn,
        "TC_TEST_DATABASE_URL": dsn,
    }
    env.pop("TC_REQUIRE_DB", None)  # the session hook would migrate up front and hide the bug
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", TARGET, "-q", "-rfs", "-p", "no:cacheprovider"],
        cwd=str(API_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    rc = proc.returncode  # assert on a plain int so pytest never echoes raw child output
    password = fresh_test_db_url.password or "\0"
    out = (proc.stdout + proc.stderr).replace(password, "***")
    summary = out.strip().splitlines()[-1] if out.strip() else ""
    assert rc == 0, f"{TARGET} fails when run alone on a fresh DB:\n{out[-4000:]}"
    assert re.search(r"\d+ passed", summary), summary
    assert not re.search(r"failed|error|skipped", summary), summary
