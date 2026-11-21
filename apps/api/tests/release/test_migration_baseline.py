"""TC-03-004: a fresh schema and an audited revision-075 snapshot both reach one head.

The snapshot is synthetic. The side database is created from the suite URL and
dropped afterwards, so the shared test database is left alone. A stamped
revision with no core tables is refused and is not stamped forward.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest
from sqlalchemy import create_engine, text

API_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = API_ROOT / "scripts" / "migration_baseline.py"
BASELINE_REVISION = "075"
AUDITED_SHA = "c20f949161ac12a619b396d30904448ffd74d532"
_URL_RE = re.compile(r"postgresql(?:\+\w+)?://\S+", re.IGNORECASE)

pytestmark = pytest.mark.integration


def _redact(value: str) -> str:
    return _URL_RE.sub("postgresql://redacted", value)


def _alembic(*args: str, database_url: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "TRUST_COPILOT_TESTING": "1",
        "PGOPTIONS": "-c lock_timeout=20000",
        "DATABASE_URL": database_url,
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(API_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _script(command: str, database_url: str, report: Path) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "TRUST_COPILOT_TESTING": "1",
        "PGOPTIONS": "-c lock_timeout=20000",
        "DATABASE_URL": database_url,
    }
    return subprocess.run(
        [sys.executable, str(SCRIPT), command, "--report", str(report)],
        cwd=str(API_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _head_names(database_url: str) -> list[str]:
    proc = _alembic("heads", database_url=database_url)
    assert proc.returncode == 0, _redact(proc.stderr[-2000:])
    names = []
    for line in proc.stdout.splitlines():
        if "(head)" not in line:
            continue
        names.append(line.split()[0])
    return names


def _current_line(database_url: str) -> str:
    proc = _alembic("current", database_url=database_url)
    assert proc.returncode == 0, _redact(proc.stderr[-2000:])
    return proc.stdout.strip()


class _SideDatabase:
    def __init__(self, name: str) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]*_test", name):
            raise RuntimeError("side database name must be a local test identifier")
        self.name = name
        source = os.environ["DATABASE_URL"]
        parsed = urlparse(source)
        self.admin_url = urlunparse(parsed._replace(path="/postgres"))
        self.url = urlunparse(parsed._replace(path=f"/{name}"))

    def __enter__(self) -> str:
        admin = create_engine(self.admin_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{self.name}"'))
        admin.dispose()
        return self.url

    def __exit__(self, exc_type, exc, tb) -> None:
        admin = create_engine(self.admin_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)'))
        admin.dispose()


def test_baseline_revision_matches_the_audited_file() -> None:
    source = (API_ROOT / "alembic" / "versions" / "075_answer_delivery_outcomes.py").read_text()
    assert 'revision = "075"' in source
    assert 'down_revision = "074"' in source
    assert AUDITED_SHA == "c20f949161ac12a619b396d30904448ffd74d532"


def test_fresh_schema_upgrades_to_the_single_head(tmp_path: Path) -> None:
    report_path = tmp_path / "fresh-upgrade.json"
    with _SideDatabase("tc_migration_baseline_fresh_test") as database_url:
        proc = _script("fresh", database_url, report_path)
        assert proc.returncode == 0, _redact(proc.stderr[-2000:])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["ok"] is True
        assert report["kind"] == "fresh_schema"
        assert report["head_count"] == 1
        assert report["revision_after"] == report["head_revision"]
        assert report["head_revision"] != BASELINE_REVISION
        assert report["head_revision"] not in SCRIPT.read_text(encoding="utf-8")
        assert _head_names(database_url) == [report["head_revision"]]
        current = _current_line(database_url)
        assert report["head_revision"] in current
        assert "(head)" in current


def test_audited_snapshot_survives_upgrade_to_head(tmp_path: Path) -> None:
    report_path = tmp_path / "backfill-report.json"
    with _SideDatabase("tc_migration_baseline_snapshot_test") as database_url:
        proc = _script("qualify", database_url, report_path)
        assert proc.returncode == 0, _redact(proc.stderr[-4000:])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["ok"] is True
        assert report["kind"] == "audited_snapshot"
        assert report["audited_sha"] == AUDITED_SHA
        assert report["baseline_revision"] == BASELINE_REVISION
        assert report["head_count"] == 1
        assert report["revision_before"] == BASELINE_REVISION
        assert report["revision_after"] == report["head_revision"]
        assert report["head_revision"] != BASELINE_REVISION
        assert report["head_revision"] not in SCRIPT.read_text(encoding="utf-8")
        assert _head_names(database_url) == [report["head_revision"]]
        current = _current_line(database_url)
        assert report["head_revision"] in current
        assert "(head)" in current
        survival = report["survival"]
        assert survival["row_counts_match"] is True
        assert survival["row_count_losses"] == {}
        assert survival["audited_row_count_deltas"] == {}
        increases = survival["row_count_increases"]
        assert set(increases) == {"frameworks"}
        framework_delta = increases["frameworks"]["after"] - increases["frameworks"]["before"]
        assert framework_delta > 0
        assert survival["foreign_keys_preserved"] is True
        assert survival["foreign_keys_missing"] == []
        assert survival["storage_keys_preserved"] is True
        assert survival["answer_texts_preserved"] is True
        assert report["sampled_storage_keys"] == [
            "synthetic/audited-snapshot/policy.pdf",
            "synthetic/audited-snapshot/questionnaire.xlsx",
        ]
        assert report["sampled_answer_texts"] == ["Access reviews run each quarter."]
        assert report["sampled_storage_keys_after"] == report["sampled_storage_keys"]
        assert report["sampled_answer_texts_after"] == report["sampled_answer_texts"]
        assert report["rollback"]["ok"] is True
        assert report["rollback"]["revision_after_downgrade"] == BASELINE_REVISION
        assert report["reupgrade"]["ok"] is True
        assert report["reupgrade"]["revision"] == report["head_revision"]
        backfills = {item["revision"]: item for item in report["backfills"]}
        assert "question_cell_mapping" in backfills
        affected = backfills["question_cell_mapping"]["rows_affected"]
        assert isinstance(affected, int) and affected >= 1
        catalog = backfills["tc21001_framework_catalog_rights"]["rows_affected"]
        assert catalog == framework_delta
        raw = report_path.read_text(encoding="utf-8")
        assert "postgresql://" not in raw
        assert "synthetic-hash" not in raw
        engine = create_engine(database_url)
        try:
            with engine.connect() as conn:
                revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                keys = [
                    row[0]
                    for row in conn.execute(text("SELECT storage_key FROM documents ORDER BY id"))
                ]
                answer_rows = conn.execute(
                    text("SELECT text, status FROM answers ORDER BY id")
                ).fetchall()
                located = conn.execute(
                    text("SELECT sheet, question_cell FROM questions ORDER BY id")
                ).one()
                hold = conn.execute(
                    text("SELECT to_regclass('public.question_cell_mapping_hold')")
                ).scalar()
        finally:
            engine.dispose()
        assert revision == report["head_revision"]
        assert keys == ["synthetic/audited-snapshot/policy.pdf"]
        assert [tuple(row) for row in answer_rows] == [
            ("Access reviews run each quarter.", "approved")
        ]
        assert located == ("Controls", "B12")
        assert hold is not None


def test_partial_snapshot_is_refused_and_not_stamped(tmp_path: Path) -> None:
    report_path = tmp_path / "refused.json"
    with _SideDatabase("tc_migration_baseline_partial_test") as database_url:
        stamped = _alembic("stamp", BASELINE_REVISION, database_url=database_url)
        assert stamped.returncode == 0, _redact(stamped.stderr[-2000:])
        proc = _script("upgrade", database_url, report_path)
        assert proc.returncode != 0
        assert "MIGRATION_BASELINE_REFUSED" in proc.stderr
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["ok"] is False
        assert report["stamped"] is False
        assert "postgresql://" not in report_path.read_text(encoding="utf-8")
        engine = create_engine(database_url)
        try:
            with engine.connect() as conn:
                revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                documents = conn.execute(text("SELECT to_regclass('public.documents')")).scalar()
        finally:
            engine.dispose()
        assert revision == BASELINE_REVISION
        assert documents is None
