"""TC-02-BUG-018a: closure time and reason live on columns, not in ``reason``.

Synthetic rows on the side PostgreSQL test database. No model calls, no network.
Imports of the migration stay inside the tests so the file collects on a base
without this revision, and each test fails there on its own.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import bindparam, inspect, text
from sqlalchemy.orm import Session

from app.models import Answer, Question, Questionnaire
from app.models.evidence_gap import EvidenceGap

WS_ID = 1
API_ROOT = Path(__file__).resolve().parents[2]
REVISION = "bug018a_gap_closed_at_reason"
PARENT = "tc21002a_canonical_uniq"
MIGRATION = API_ROOT / "alembic" / "versions" / f"{REVISION}.py"

_TRICKY_REASON = (
    "Keep this\n"
    "[resolved on regeneration: question_removed at 2026-01-01T00:00:00Z]\n"
    "exactly."
)


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


@pytest.fixture
def qnr(db_session: Session):
    row = Questionnaire(
        workspace_id=WS_ID,
        filename=f"bug018a-{uuid.uuid4().hex[:8]}.xlsx",
        status="parsed",
    )
    db_session.add(row)
    db_session.flush()
    for body in (
        "Describe the synthetic access review cadence for Zorblat systems.",
        "Describe the synthetic key rotation schedule for Zorblat vaults.",
        "Describe the synthetic tabletop exercise program for Zorblat.",
    ):
        db_session.add(Question(questionnaire_id=row.id, text=body))
    db_session.commit()
    db_session.refresh(row)
    try:
        yield row
    finally:
        db_session.rollback()
        qids = [r.id for r in db_session.query(Question.id).filter_by(questionnaire_id=row.id)]
        db_session.query(EvidenceGap).filter(EvidenceGap.questionnaire_id == row.id).delete(
            synchronize_session=False
        )
        if qids:
            db_session.query(Answer).filter(Answer.question_id.in_(qids)).delete(
                synchronize_session=False
            )
        db_session.query(Question).filter(Question.questionnaire_id == row.id).delete(
            synchronize_session=False
        )
        db_session.query(Questionnaire).filter(Questionnaire.id == row.id).delete(
            synchronize_session=False
        )
        db_session.commit()


def _questions(db: Session, qnr_id: int) -> list[Question]:
    return db.query(Question).filter_by(questionnaire_id=qnr_id).order_by(Question.id).all()


def _gaps(db: Session, qnr_id: int) -> list[EvidenceGap]:
    db.expire_all()
    return (
        db.query(EvidenceGap)
        .filter(EvidenceGap.questionnaire_id == qnr_id)
        .order_by(EvidenceGap.id)
        .all()
    )


def _insufficient(question_id: int) -> Answer:
    return Answer(
        question_id=question_id,
        text="Insufficient evidence.",
        status="insufficient_evidence",
        outcome_code="no_evidence",
        insufficient_reason="no_citations",
    )


def _set_answer(db: Session, question_id: int, **fields) -> None:
    db.query(Answer).filter(Answer.question_id == question_id).update(
        fields, synchronize_session=False
    )
    db.commit()


_SUFFICIENT = {
    "text": "Synthetic grounded draft.",
    "status": "draft",
    "outcome_code": None,
    "insufficient_reason": None,
}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def test_closing_sets_columns_when_answer_becomes_sufficient(db_session: Session, qnr):
    from app.services.evidence_gap_service import generate_gaps_for_questionnaire

    db = db_session
    q1, q2, _q3 = _questions(db, qnr.id)
    db.add_all([_insufficient(q1.id), _insufficient(q2.id)])
    db.commit()
    generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    gap1 = next(g for g in _gaps(db, qnr.id) if g.question_id == q1.id)
    opened_reason = gap1.reason

    _set_answer(db, q1.id, **_SUFFICIENT)
    result = generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    closed = next(g for g in _gaps(db, qnr.id) if g.id == gap1.id)
    still_open = next(g for g in _gaps(db, qnr.id) if g.question_id == q2.id)

    assert result["resolved"] == 1
    assert closed.status == "resolved"
    assert closed.close_reason == "answer_sufficient"
    assert closed.closed_at is not None
    assert closed.updated_at is not None
    assert _utc(closed.closed_at) == _utc(closed.updated_at)
    assert closed.reason == opened_reason
    assert still_open.status == "open"
    assert still_open.closed_at is None and still_open.close_reason is None


def test_closing_sets_columns_when_question_is_removed(db_session: Session, qnr):
    from app.services.evidence_gap_service import generate_gaps_for_questionnaire

    db = db_session
    q1, q2, _q3 = _questions(db, qnr.id)
    db.add_all([_insufficient(q1.id), _insufficient(q2.id)])
    db.commit()
    generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    gap2 = next(g for g in _gaps(db, qnr.id) if g.question_id == q2.id)
    opened_reason = gap2.reason

    db.query(Answer).filter(Answer.question_id == q2.id).delete(synchronize_session=False)
    db.query(Question).filter(Question.id == q2.id).delete(synchronize_session=False)
    db.commit()
    result = generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    removed = next(g for g in _gaps(db, qnr.id) if g.id == gap2.id)

    assert result["resolved"] == 1
    assert removed.question_id is None
    assert removed.status == "resolved"
    assert removed.close_reason == "question_removed"
    assert removed.closed_at is not None
    assert removed.reason == opened_reason


def test_closing_preserves_reason_text_including_an_embedded_note(db_session: Session, qnr):
    from app.services.evidence_gap_service import generate_gaps_for_questionnaire

    db = db_session
    q1, _q2, _q3 = _questions(db, qnr.id)
    db.add(_insufficient(q1.id))
    db.commit()
    generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    gap = _gaps(db, qnr.id)[0]
    gap.reason = _TRICKY_REASON
    db.commit()

    _set_answer(db, q1.id, **_SUFFICIENT)
    generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    closed = _gaps(db, qnr.id)[0]
    assert closed.reason == _TRICKY_REASON
    assert closed.close_reason == "answer_sufficient"
    assert "question_removed" not in (closed.close_reason or "")


def test_accepted_and_dismissed_gaps_keep_null_closure_columns(db_session: Session, qnr):
    from app.services.evidence_gap_service import generate_gaps_for_questionnaire

    db = db_session
    q1, q2, q3 = _questions(db, qnr.id)
    db.add_all([_insufficient(q.id) for q in (q1, q2, q3)])
    db.commit()
    generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    by_q = {g.question_id: g for g in _gaps(db, qnr.id)}
    by_q[q1.id].status = "accepted"
    by_q[q2.id].status = "dismissed"
    db.commit()
    before = {
        g.question_id: (g.status, g.reason, g.updated_at, g.closed_at, g.close_reason)
        for g in _gaps(db, qnr.id)
        if g.question_id in (q1.id, q2.id)
    }

    for q in (q1, q2, q3):
        _set_answer(db, q.id, **_SUFFICIENT)
    generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    after = {g.question_id: g for g in _gaps(db, qnr.id)}
    for qid, snapshot in before.items():
        row = after[qid]
        assert (row.status, row.reason, row.updated_at, row.closed_at, row.close_reason) == snapshot
        assert row.closed_at is None and row.close_reason is None
    assert after[q3.id].status == "resolved"
    assert after[q3.id].close_reason == "answer_sufficient"


def test_llm_error_placeholder_does_not_write_closure_columns(db_session: Session, qnr):
    from app.services.evidence_gap_service import generate_gaps_for_questionnaire

    db = db_session
    q1, q2, _q3 = _questions(db, qnr.id)
    db.add(_insufficient(q1.id))
    db.commit()
    generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    before = _gaps(db, qnr.id)[0]
    before_snapshot = (before.id, before.status, before.reason, before.updated_at)
    assert before.closed_at is None and before.close_reason is None

    _set_answer(db, q1.id, outcome_code="model_timeout", insufficient_reason="llm_error")
    db.add(
        Answer(
            question_id=q2.id,
            text="Insufficient evidence.",
            status="insufficient_evidence",
            outcome_code="model_timeout",
            insufficient_reason="llm_error",
        )
    )
    db.commit()
    result = generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    rows = _gaps(db, qnr.id)
    assert result == {"generated": 0, "total_insufficient": 0, "resolved": 0}
    assert len(rows) == 1
    gap = rows[0]
    assert (gap.id, gap.status, gap.reason, gap.updated_at) == before_snapshot
    assert gap.closed_at is None and gap.close_reason is None


def test_manual_status_changes_do_not_write_closure_columns(db_session: Session, qnr):
    from app.services.evidence_gap_service import (
        bulk_update_by_title,
        update_evidence_gap_status,
    )

    db = db_session
    q1, q2, _q3 = _questions(db, qnr.id)
    title = f"Synthetic policy {uuid.uuid4().hex[:8]}"
    closed_at = datetime(2026, 10, 27, 14, 30, 15, tzinfo=timezone.utc)
    db.add_all(
        [
            EvidenceGap(
                workspace_id=WS_ID,
                questionnaire_id=qnr.id,
                question_id=q1.id,
                gap_type="missing_evidence",
                reason="Synthetic open gap.",
                suggested_evidence_doc_title=title,
                status="open",
            ),
            EvidenceGap(
                workspace_id=WS_ID,
                questionnaire_id=qnr.id,
                question_id=q2.id,
                gap_type="missing_evidence",
                reason="Synthetic resolved gap.",
                status="resolved",
                closed_at=closed_at,
                close_reason="answer_sufficient",
            ),
        ]
    )
    db.commit()
    open_gap, resolved_gap = _gaps(db, qnr.id)

    count = bulk_update_by_title(db, WS_ID, title, "dismissed")
    assert count == 1
    db.refresh(open_gap)
    assert open_gap.status == "dismissed"
    assert open_gap.closed_at is None and open_gap.close_reason is None

    updated = update_evidence_gap_status(db, open_gap.id, WS_ID, "accepted")
    assert updated is not None
    assert updated["status"] == "accepted"
    assert updated["closed_at"] is None
    assert updated["close_reason"] is None
    db.refresh(open_gap)
    assert open_gap.closed_at is None and open_gap.close_reason is None

    moved = update_evidence_gap_status(db, resolved_gap.id, WS_ID, "open")
    assert moved is not None
    assert moved["status"] == "open"
    assert moved["close_reason"] == "answer_sufficient"
    db.refresh(resolved_gap)
    assert resolved_gap.status == "open"
    assert resolved_gap.close_reason == "answer_sufficient"
    assert _utc(resolved_gap.closed_at) == closed_at


def test_reinsufficient_question_keeps_the_resolved_row(db_session: Session, qnr):
    from app.services.evidence_gap_service import generate_gaps_for_questionnaire

    db = db_session
    q1, _q2, _q3 = _questions(db, qnr.id)
    db.add(_insufficient(q1.id))
    db.commit()
    generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    _set_answer(db, q1.id, **_SUFFICIENT)
    generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    resolved = _gaps(db, qnr.id)[0]
    resolved_at = resolved.closed_at
    assert resolved.close_reason == "answer_sufficient"

    _set_answer(
        db,
        q1.id,
        text="Insufficient evidence.",
        status="insufficient_evidence",
        outcome_code="no_evidence",
        insufficient_reason="no_citations",
    )
    again = generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    assert again == {"generated": 1, "total_insufficient": 1, "resolved": 0}
    rows = _gaps(db, qnr.id)
    assert [g.status for g in rows] == ["resolved", "open"]
    assert rows[0].id == resolved.id
    assert rows[0].close_reason == "answer_sufficient"
    assert rows[0].closed_at == resolved_at
    assert rows[1].closed_at is None and rows[1].close_reason is None


def test_gap_payload_exposes_closure_columns(db_session: Session, qnr):
    from app.services.evidence_gap_service import get_evidence_gap, list_evidence_gaps

    db = db_session
    q1, _q2, _q3 = _questions(db, qnr.id)
    closed_at = datetime(2026, 10, 27, 14, 30, 15, tzinfo=timezone.utc)
    db.add(
        EvidenceGap(
            workspace_id=WS_ID,
            questionnaire_id=qnr.id,
            question_id=q1.id,
            gap_type="missing_evidence",
            reason="Synthetic resolved gap.",
            status="resolved",
            closed_at=closed_at,
            close_reason="question_removed",
        )
    )
    db.commit()
    gap_id = _gaps(db, qnr.id)[0].id
    one = get_evidence_gap(db, gap_id, WS_ID)
    listed = list_evidence_gaps(db, WS_ID, questionnaire_id=qnr.id)
    assert one is not None
    for payload in (one, listed[0]):
        assert payload["close_reason"] == "question_removed"
        assert payload["closed_at"] is not None
        assert "reason" in payload and "status" in payload and "updated_at" in payload
    assert set(one) == {
        "id",
        "workspace_id",
        "questionnaire_id",
        "question_id",
        "answer_id",
        "gap_type",
        "reason",
        "proposed_policy_addition",
        "suggested_evidence_doc_title",
        "confidence",
        "status",
        "created_at",
        "updated_at",
        "closed_at",
        "close_reason",
    }


def test_historical_note_matches_the_backfill_pattern():
    from app.services.evidence_gap_service import append_resolution_note

    module = _load_migration()
    at = datetime(2026, 10, 27, 9, 30, 15, 123456, tzinfo=timezone(timedelta(hours=-5)))
    samples = (
        append_resolution_note("Original\nreason.", "question_removed", at),
        append_resolution_note(None, "answer_sufficient", at),
    )
    assert samples[0].splitlines()[-1] == (
        "[resolved on regeneration: question_removed at 2026-10-27T14:30:15Z]"
    )
    for sample in samples:
        assert re.fullmatch(module.NOTE_LINE_RE, sample.splitlines()[-1])
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert imported
    assert not any(name == "app" or name.startswith("app.") for name in imported)
    assert module.revision == REVISION
    assert module.down_revision == PARENT


def _insert_legacy(conn, *, reason: str | None, status: str, updated_at: datetime) -> int:
    row = conn.execute(
        text(
            """
            INSERT INTO evidence_gaps (
                workspace_id, gap_type, reason, status, created_at, updated_at
            ) VALUES (
                1, 'missing_evidence', :reason, :status,
                TIMESTAMP '2026-01-01 00:00:00', :updated_at
            )
            RETURNING id
            """
        ),
        {"reason": reason, "status": status, "updated_at": updated_at},
    ).one()
    return int(row.id)


def _fetch(conn, gap_id: int):
    """Read under a non-UTC session timezone so a naive-timestamp cast cannot hide."""
    conn.execute(text("SET TIME ZONE 'America/New_York'"))
    try:
        return conn.execute(
            text(
                "SELECT reason, status, close_reason, closed_at "
                "FROM evidence_gaps WHERE id = :id"
            ),
            {"id": gap_id},
        ).one()
    finally:
        conn.execute(text("SET TIME ZONE 'UTC'"))


def test_backfill_parses_old_notes_and_falls_back_to_updated_at(db_session: Session):
    """Rows already resolved before the columns exist are filled on upgrade.

    The last note line wins. A missing or unrecognized line leaves ``close_reason``
    NULL and sets ``closed_at`` from ``updated_at`` as UTC. ``reason`` is not rewritten.
    Open, accepted and dismissed rows are left NULL even when ``reason`` contains a note.
    """
    from app.core.database import engine

    module = _load_migration()
    db_session.rollback()
    engine.dispose()
    ids: list[int] = []
    note_sufficient = (
        "Opening text.\n"
        "[resolved on regeneration: question_removed at 2026-01-01T00:00:00Z]\n"
        "[resolved on regeneration: answer_sufficient at 2026-10-27T14:30:15Z]"
    )
    note_removed = (
        "Original\nreason.\n[resolved on regeneration: question_removed at 2026-10-27T14:30:15Z]"
    )
    note_only = "[resolved on regeneration: answer_sufficient at 2026-04-01T00:00:01Z]"
    no_note = "Synthetic resolved gap with no closure note."
    malformed = "Synthetic.\n[resolved on regeneration: not_a_code at 2026-10-27T14:30:15Z]"
    fallback_at = datetime(2026, 3, 4, 12, 0, 0)
    malformed_at = datetime(2026, 5, 5, 6, 7, 8)
    null_reason_at = datetime(2026, 6, 6, 1, 2, 3)
    try:
        _alembic_ok("downgrade", module.down_revision)
        with engine.begin() as conn:
            ids.append(
                _insert_legacy(
                    conn,
                    reason=note_sufficient,
                    status="resolved",
                    updated_at=datetime(2020, 1, 1, 0, 0, 0),
                )
            )
            ids.append(
                _insert_legacy(
                    conn,
                    reason=note_removed,
                    status="resolved",
                    updated_at=datetime(2020, 2, 2, 0, 0, 0),
                )
            )
            ids.append(
                _insert_legacy(
                    conn,
                    reason=note_only,
                    status="resolved",
                    updated_at=datetime(2020, 3, 3, 0, 0, 0),
                )
            )
            ids.append(
                _insert_legacy(conn, reason=no_note, status="resolved", updated_at=fallback_at)
            )
            ids.append(
                _insert_legacy(conn, reason=malformed, status="resolved", updated_at=malformed_at)
            )
            ids.append(
                _insert_legacy(conn, reason=None, status="resolved", updated_at=null_reason_at)
            )
            ids.append(
                _insert_legacy(
                    conn,
                    reason=note_only,
                    status="open",
                    updated_at=datetime(2026, 7, 7, 0, 0, 0),
                )
            )
            ids.append(
                _insert_legacy(
                    conn,
                    reason=note_removed,
                    status="accepted",
                    updated_at=datetime(2026, 8, 8, 0, 0, 0),
                )
            )
            ids.append(
                _insert_legacy(
                    conn,
                    reason="User dismissed this.",
                    status="dismissed",
                    updated_at=datetime(2026, 9, 9, 0, 0, 0),
                )
            )
        _alembic_ok("upgrade", REVISION)

        def read() -> list:
            with engine.connect() as conn:
                return [_fetch(conn, gap_id) for gap_id in ids]

        rows = read()
        assert rows[0].reason == note_sufficient
        assert rows[0].close_reason == "answer_sufficient"
        assert _utc(rows[0].closed_at) == datetime(2026, 10, 27, 14, 30, 15, tzinfo=timezone.utc)
        assert rows[1].reason == note_removed
        assert rows[1].close_reason == "question_removed"
        assert _utc(rows[1].closed_at) == datetime(2026, 10, 27, 14, 30, 15, tzinfo=timezone.utc)
        assert rows[2].reason == note_only
        assert rows[2].close_reason == "answer_sufficient"
        assert _utc(rows[2].closed_at) == datetime(2026, 4, 1, 0, 0, 1, tzinfo=timezone.utc)
        assert rows[3].reason == no_note
        assert rows[3].close_reason is None
        assert _utc(rows[3].closed_at) == fallback_at.replace(tzinfo=timezone.utc)
        assert rows[4].reason == malformed
        assert rows[4].close_reason is None
        assert _utc(rows[4].closed_at) == malformed_at.replace(tzinfo=timezone.utc)
        assert rows[5].reason is None
        assert rows[5].close_reason is None
        assert _utc(rows[5].closed_at) == null_reason_at.replace(tzinfo=timezone.utc)
        for untouched in rows[6:]:
            assert untouched.close_reason is None
            assert untouched.closed_at is None

        with engine.begin() as conn:
            conn.execute(text(module.backfill_sql()))
        assert read() == rows

        _alembic_ok("downgrade", module.down_revision)
        engine.dispose()
        names = {col["name"] for col in inspect(engine).get_columns("evidence_gaps")}
        assert "closed_at" not in names and "close_reason" not in names
        with engine.connect() as conn:
            kept = conn.execute(
                text("SELECT id, reason FROM evidence_gaps WHERE id IN :ids").bindparams(
                    bindparam("ids", expanding=True)
                ),
                {"ids": ids},
            ).all()
        assert {row.id: row.reason for row in kept} == {
            ids[0]: note_sufficient,
            ids[1]: note_removed,
            ids[2]: note_only,
            ids[3]: no_note,
            ids[4]: malformed,
            ids[5]: None,
            ids[6]: note_only,
            ids[7]: note_removed,
            ids[8]: "User dismissed this.",
        }
        _alembic_ok("upgrade", "head")
        assert read() == rows

        with engine.begin() as conn:
            conn.execute(
                text("UPDATE evidence_gaps SET updated_at = :updated_at WHERE id = :id"),
                {"updated_at": datetime(2030, 1, 1, 0, 0, 0), "id": ids[3]},
            )
            conn.execute(text(module.backfill_sql()))
        assert read() == rows
    finally:
        _alembic("upgrade", "head")
        if ids:
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM evidence_gaps WHERE id IN :ids").bindparams(
                        bindparam("ids", expanding=True)
                    ),
                    {"ids": ids},
                )


def test_migration_upgrade_downgrade_upgrade_round_trip(db_session: Session):
    from app.core.database import engine

    module = _load_migration()
    assert module.down_revision == PARENT
    db_session.rollback()
    engine.dispose()

    def names() -> set[str]:
        engine.dispose()
        return {col["name"] for col in inspect(engine).get_columns("evidence_gaps")}

    try:
        assert {"closed_at", "close_reason"} <= names()
        info = {col["name"]: col for col in inspect(engine).get_columns("evidence_gaps")}
        assert info["closed_at"]["nullable"] is True
        assert info["close_reason"]["nullable"] is True
        assert getattr(info["closed_at"]["type"], "timezone", None) is True
        assert info["close_reason"]["type"].length == 32

        _alembic_ok("downgrade", PARENT)
        assert "closed_at" not in names()
        assert "close_reason" not in names()
        _alembic_ok("upgrade", "head")
        assert {"closed_at", "close_reason"} <= names()
        heads = [line for line in _alembic_ok("heads").splitlines() if line.strip()]
        assert len(heads) == 1
        assert REVISION in heads[0] and "(head)" in heads[0]
    finally:
        _alembic("upgrade", "head")


def test_offline_sql_adds_and_drops_the_columns():
    module = _load_migration()
    upgrade = _alembic_ok("upgrade", f"{module.down_revision}:{module.revision}", "--sql")
    downgrade = _alembic_ok("downgrade", f"{module.revision}:{module.down_revision}", "--sql")
    folded = upgrade.upper()
    assert "ADD COLUMN CLOSED_AT" in folded
    assert "TIMESTAMP WITH TIME ZONE" in folded
    assert "ADD COLUMN CLOSE_REASON" in folded
    assert "VARCHAR(32)" in folded
    assert "UPDATE EVIDENCE_GAPS" in folded
    assert "question_removed" in upgrade and "answer_sufficient" in upgrade
    assert "AT TIME ZONE 'UTC'" in upgrade
    assert "SET REASON" not in folded
    assert "DROP COLUMN" not in folded
    down = downgrade.upper()
    assert "DROP COLUMN CLOSE_REASON" in down
    assert "DROP COLUMN CLOSED_AT" in down
    assert "ADD COLUMN" not in down
