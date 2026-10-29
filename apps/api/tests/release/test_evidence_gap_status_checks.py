"""TC-02-BUG-018b: check constraints on evidence gap status and close_reason.

Synthetic rows on the side PostgreSQL test database. No model calls, no network.
Migration imports stay inside the tests so the file collects on a base without
this revision. Tests that only insert values the column already accepts pass on
that base; the rejection, pre-scan, round trip and offline SQL tests do not.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.evidence_gap import ALL_GAP_STATUSES, EvidenceGap
from app.services.evidence_gap_service import (
    RESOLVED_ANSWER_SUFFICIENT,
    RESOLVED_QUESTION_REMOVED,
)

API_ROOT = Path(__file__).resolve().parents[2]
REVISION = "bug018b_gap_status_checks"
PARENT = "tc21005_mapping_version"
MIGRATION = API_ROOT / "alembic" / "versions" / f"{REVISION}.py"
_MARKER = "bug018b-synthetic"


def _load_migration():
    assert MIGRATION.is_file(), MIGRATION
    spec = importlib.util.spec_from_file_location(REVISION, MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "TRUST_COPILOT_TESTING": "1",
        "DATABASE_URL": os.environ["DATABASE_URL"],
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _alembic_ok(*args: str) -> str:
    result = _alembic(*args)
    assert result.returncode == 0, result.stderr[-2000:] + result.stdout[-2000:]
    return result.stdout


def _revision_reaches_every_head(revision: str) -> None:
    """``revision`` is a head, or an ancestor of every head. Does not pin the head id."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(API_ROOT / "alembic.ini")))
    heads = script.get_heads()
    assert heads

    def reaches(current: str | None, seen: set[str] | None = None) -> bool:
        walked: set[str] = set() if seen is None else seen
        while current and current not in walked:
            if current == revision:
                return True
            walked.add(current)
            down = script.get_revision(current).down_revision
            if isinstance(down, tuple):
                return all(reaches(item, set(walked)) for item in down)
            current = down
        return False

    assert all(reaches(head) for head in heads), (heads, revision)


def _insert(conn, *, status: str, close_reason: str | None, reason: str) -> int:
    row = conn.execute(
        text(
            """
            INSERT INTO evidence_gaps (
                workspace_id, gap_type, reason, status, close_reason,
                created_at, updated_at
            ) VALUES (
                1, 'missing_evidence', :reason, :status, :close_reason,
                TIMESTAMP '2026-01-01 00:00:00', TIMESTAMP '2026-01-01 00:00:00'
            )
            RETURNING id
            """
        ),
        {"reason": reason, "status": status, "close_reason": close_reason},
    ).one()
    return int(row.id)


def _snapshot(conn, gap_id: int):
    return conn.execute(
        text("SELECT status, close_reason, reason FROM evidence_gaps WHERE id = :id"),
        {"id": gap_id},
    ).one()


def _delete(conn, ids: list[int]) -> None:
    if not ids:
        return
    conn.execute(
        text("DELETE FROM evidence_gaps WHERE id IN :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"ids": ids},
    )


def _checks(conn) -> dict[str, bool]:
    rows = conn.execute(
        text(
            """
            SELECT conname, convalidated
            FROM pg_constraint
            WHERE conrelid = 'evidence_gaps'::regclass AND contype = 'c'
            """
        )
    ).all()
    return {row.conname: bool(row.convalidated) for row in rows}


def test_unknown_status_is_rejected(db_session: Session):
    with pytest.raises(IntegrityError) as caught:
        db_session.execute(
            text(
                """
                INSERT INTO evidence_gaps (
                    workspace_id, gap_type, status, created_at, updated_at
                ) VALUES (
                    1, 'missing_evidence', 'archived',
                    TIMESTAMP '2026-01-01 00:00:00', TIMESTAMP '2026-01-01 00:00:00'
                )
                """
            )
        )
        db_session.flush()
    db_session.rollback()
    assert "ck_evidence_gaps_status" in str(caught.value)


def test_unknown_close_reason_is_rejected(db_session: Session):
    with pytest.raises(IntegrityError) as caught:
        db_session.execute(
            text(
                """
                INSERT INTO evidence_gaps (
                    workspace_id, gap_type, status, close_reason,
                    created_at, updated_at
                ) VALUES (
                    1, 'missing_evidence', 'open', 'not_a_code',
                    TIMESTAMP '2026-01-01 00:00:00', TIMESTAMP '2026-01-01 00:00:00'
                )
                """
            )
        )
        db_session.flush()
    db_session.rollback()
    assert "ck_evidence_gaps_close_reason" in str(caught.value)


def test_values_the_app_writes_are_accepted(db_session: Session):
    """Every status and close_reason the app and the 018a backfill store.

    Passes on a database without these checks: the columns are unconstrained
    varchar and already accept the same literals.
    """
    written = [
        ("open", None),
        ("accepted", None),
        ("dismissed", None),
        ("resolved", None),
        ("resolved", RESOLVED_QUESTION_REMOVED),
        ("resolved", RESOLVED_ANSWER_SUFFICIENT),
    ]
    assert {status for status, _reason in written} == set(ALL_GAP_STATUSES)
    assert {reason for _status, reason in written if reason} == {
        RESOLVED_QUESTION_REMOVED,
        RESOLVED_ANSWER_SUFFICIENT,
    }
    rows = [
        EvidenceGap(
            workspace_id=1,
            gap_type="missing_evidence",
            reason=_MARKER,
            status=status,
            close_reason=close_reason,
        )
        for status, close_reason in written
    ]
    db_session.add_all(rows)
    db_session.flush()
    stored = {(row.status, row.close_reason) for row in rows}
    assert stored == set(written)
    db_session.rollback()


def test_non_resolved_row_may_keep_close_reason(db_session: Session):
    """The presence check was not added. Manual status changes leave the code.

    Passes without the new checks as well: nothing forbids this pair today,
    and the branch keeps it that way on purpose.
    """
    for status in ("open", "accepted", "dismissed"):
        db_session.add(
            EvidenceGap(
                workspace_id=1,
                gap_type="missing_evidence",
                reason=_MARKER,
                status=status,
                close_reason=RESOLVED_ANSWER_SUFFICIENT,
            )
        )
    db_session.flush()
    db_session.rollback()


def test_model_checks_match_the_migration():
    from sqlalchemy import CheckConstraint

    from app.models.evidence_gap import (
        CK_EVIDENCE_GAPS_CLOSE_REASON,
        CK_EVIDENCE_GAPS_STATUS,
        CLOSE_REASON_CHECK_SQL,
        GAP_CLOSE_REASONS,
        STATUS_CHECK_SQL,
    )

    module = _load_migration()
    assert module.revision == REVISION
    assert module.down_revision == PARENT
    assert module.STATUS_VALUES == ALL_GAP_STATUSES
    assert module.CLOSE_REASON_VALUES == GAP_CLOSE_REASONS
    assert module.STATUS_CHECK_SQL == STATUS_CHECK_SQL
    assert module.CLOSE_REASON_CHECK_SQL == CLOSE_REASON_CHECK_SQL
    assert module.CK_EVIDENCE_GAPS_STATUS == CK_EVIDENCE_GAPS_STATUS
    assert module.CK_EVIDENCE_GAPS_CLOSE_REASON == CK_EVIDENCE_GAPS_CLOSE_REASON
    assert "was not added" in module.SKIPPED_PRESENCE_CHECK
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in EvidenceGap.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert checks == {
        CK_EVIDENCE_GAPS_STATUS: STATUS_CHECK_SQL,
        CK_EVIDENCE_GAPS_CLOSE_REASON: CLOSE_REASON_CHECK_SQL,
    }
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert imported
    assert not any(name == "app" or name.startswith("app.") for name in imported)


def test_prescan_fails_on_violations_and_passes_on_clean_data(db_session: Session):
    from app.core.database import engine

    module = _load_migration()
    db_session.rollback()
    engine.dispose()
    ids: list[int] = []
    try:
        _alembic_ok("upgrade", "head")
        with engine.begin() as conn:
            kept = _insert(
                conn,
                status="resolved",
                close_reason=RESOLVED_ANSWER_SUFFICIENT,
                reason=_MARKER + "-kept",
            )
            ids.append(kept)
        before = None
        with engine.connect() as conn:
            before = _snapshot(conn, kept)

        _alembic_ok("downgrade", module.down_revision)
        with engine.begin() as conn:
            assert module.CK_EVIDENCE_GAPS_STATUS not in _checks(conn)
            for _ in range(module.EXAMPLE_LIMIT + 1):
                ids.append(
                    _insert(
                        conn,
                        status="archived",
                        close_reason=None,
                        reason=_MARKER + "-bad-status",
                    )
                )
            ids.append(
                _insert(
                    conn,
                    status="open",
                    close_reason="not_a_code",
                    reason=_MARKER + "-bad-reason",
                )
            )
            bad_status_ids = ids[1:-1]
            bad_reason_id = ids[-1]
            reports = module.violation_reports(conn)
        by_name = {name: (count, examples) for name, count, examples in reports}
        status_count, status_examples = by_name[module.CK_EVIDENCE_GAPS_STATUS]
        reason_count, reason_examples = by_name[module.CK_EVIDENCE_GAPS_CLOSE_REASON]
        assert status_count == module.EXAMPLE_LIMIT + 1
        assert status_examples == sorted(bad_status_ids)[: module.EXAMPLE_LIMIT]
        assert bad_status_ids[-1] not in status_examples
        assert reason_count == 1
        assert reason_examples == [bad_reason_id]

        failed = _alembic("upgrade", REVISION)
        assert failed.returncode != 0
        message = failed.stderr + failed.stdout
        assert "No rows were changed" in message
        assert f"{module.CK_EVIDENCE_GAPS_STATUS}: {status_count} violating row(s)" in message
        assert f"example ids: {', '.join(str(i) for i in status_examples)}" in message
        assert f"{module.CK_EVIDENCE_GAPS_CLOSE_REASON}: 1 violating row(s)" in message
        assert str(bad_reason_id) in message

        with engine.connect() as conn:
            assert _snapshot(conn, kept) == before
            for gap_id in bad_status_ids:
                assert _snapshot(conn, gap_id).status == "archived"
                assert _snapshot(conn, gap_id).close_reason is None
            assert _snapshot(conn, bad_reason_id).status == "open"
            assert _snapshot(conn, bad_reason_id).close_reason == "not_a_code"
            assert module.CK_EVIDENCE_GAPS_STATUS not in _checks(conn)

        with engine.begin() as conn:
            _delete(conn, ids[1:])
            ids[:] = [kept]
            assert module.violation_reports(conn) == []

        _alembic_ok("upgrade", "head")
        with engine.connect() as conn:
            assert _snapshot(conn, kept) == before
            checks = _checks(conn)
            assert checks[module.CK_EVIDENCE_GAPS_STATUS] is True
            assert checks[module.CK_EVIDENCE_GAPS_CLOSE_REASON] is True
    finally:
        _alembic("upgrade", "head")
        if ids:
            with engine.begin() as conn:
                _delete(conn, ids)
        engine.dispose()


def test_upgrade_downgrade_upgrade_round_trip(db_session: Session):
    from app.core.database import engine

    module = _load_migration()
    assert module.down_revision == PARENT
    db_session.rollback()
    engine.dispose()
    ids: list[int] = []
    try:
        _alembic_ok("upgrade", "head")
        with engine.begin() as conn:
            for status, close_reason in (
                ("open", None),
                ("accepted", None),
                ("dismissed", None),
                ("resolved", None),
                ("resolved", RESOLVED_QUESTION_REMOVED),
                ("open", RESOLVED_ANSWER_SUFFICIENT),
            ):
                ids.append(
                    _insert(
                        conn,
                        status=status,
                        close_reason=close_reason,
                        reason=f"{_MARKER}-{status}-{close_reason}",
                    )
                )
        with engine.connect() as conn:
            original = {gap_id: _snapshot(conn, gap_id) for gap_id in ids}
            assert _checks(conn)[module.CK_EVIDENCE_GAPS_STATUS] is True

        _alembic_ok("downgrade", module.down_revision)
        with engine.connect() as conn:
            assert _checks(conn) == {}
            assert {gap_id: _snapshot(conn, gap_id) for gap_id in ids} == original

        _alembic_ok("upgrade", "head")
        with engine.connect() as conn:
            checks = _checks(conn)
            assert checks[module.CK_EVIDENCE_GAPS_STATUS] is True
            assert checks[module.CK_EVIDENCE_GAPS_CLOSE_REASON] is True
            assert {gap_id: _snapshot(conn, gap_id) for gap_id in ids} == original
        _revision_reaches_every_head(REVISION)
    finally:
        _alembic("upgrade", "head")
        if ids:
            with engine.begin() as conn:
                _delete(conn, ids)
        engine.dispose()


def test_revision_is_head_or_ancestor_of_every_head():
    _load_migration()
    _revision_reaches_every_head(REVISION)


def test_offline_sql_adds_not_valid_then_validates():
    module = _load_migration()
    upgrade = _alembic_ok("upgrade", f"{module.down_revision}:{module.revision}", "--sql")
    downgrade = _alembic_ok("downgrade", f"{module.revision}:{module.down_revision}", "--sql")
    folded = " ".join(upgrade.split())
    upper = folded.upper()
    for name, expression in (
        (module.CK_EVIDENCE_GAPS_STATUS, module.STATUS_CHECK_SQL),
        (module.CK_EVIDENCE_GAPS_CLOSE_REASON, module.CLOSE_REASON_CHECK_SQL),
    ):
        add_at = folded.index(f"ADD CONSTRAINT {name} CHECK ({expression}) NOT VALID")
        validate_at = folded.index(f"VALIDATE CONSTRAINT {name}")
        assert add_at < validate_at
    assert upper.count("ADD CONSTRAINT") == 2
    assert "UPDATE EVIDENCE_GAPS" not in upper
    assert "DELETE FROM EVIDENCE_GAPS" not in upper
    assert "INSERT INTO EVIDENCE_GAPS" not in upper
    assert "status = 'resolved'" not in upgrade
    down = " ".join(downgrade.split())
    down_upper = down.upper()
    assert f"DROP CONSTRAINT {module.CK_EVIDENCE_GAPS_STATUS}" in down
    assert f"DROP CONSTRAINT {module.CK_EVIDENCE_GAPS_CLOSE_REASON}" in down
    assert "ADD CONSTRAINT" not in down_upper
    assert "UPDATE EVIDENCE_GAPS" not in down_upper
    assert "DELETE FROM EVIDENCE_GAPS" not in down_upper
    assert "INSERT INTO EVIDENCE_GAPS" not in down_upper
