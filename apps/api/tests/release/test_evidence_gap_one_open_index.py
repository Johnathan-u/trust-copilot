"""TC-02-BUG-018c: one open evidence gap per question.

Synthetic rows on the side PostgreSQL test database. No model calls, no network.
Migration imports stay inside the tests so the file collects on a base without
this revision. A second open gap for one question is rejected here and accepted
on that base. Open control-check rows with a null question are allowed on both.

Each test records ``max(id)`` and the row count for the tables it can write,
then deletes every row with a higher id. The count must match afterwards.
Sequences are left alone: this file does not call ``setval``.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import bindparam, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Answer, Question, Questionnaire
from app.models.evidence_gap import EvidenceGap

API_ROOT = Path(__file__).resolve().parents[2]
REVISION = "bug018c_one_open_gap_per_question"
PARENT = "tc21005_mapping_version"
MIGRATION = API_ROOT / "alembic" / "versions" / f"{REVISION}.py"
_MARKER = "bug018c-synthetic"
# Children before parents. Same autouse shape as the TC-21-005 tests, with a
# max-id watermark like the 018b status-check tests. No shared helper exists.
_WATCHED = (
    "evidence_gaps",
    "answers",
    "questions",
    "questionnaires",
    "jobs",
    "audit_events",
    "workspaces",
)


def _watermark() -> dict[str, tuple[int, int]]:
    """``max(id)`` and row count for each watched table. ``max`` is 0 when empty."""
    from app.core.database import SessionLocal

    session = SessionLocal()
    try:
        found: dict[str, tuple[int, int]] = {}
        for name in _WATCHED:
            row = session.execute(text(f"SELECT COALESCE(MAX(id), 0), COUNT(*) FROM {name}")).one()
            found[name] = (int(row[0]), int(row[1]))
        return found
    finally:
        session.close()


def _delete_above(before: dict[str, tuple[int, int]]) -> dict[str, int]:
    """Delete rows created after the watermark. Returns the counts left behind."""
    from app.core.database import SessionLocal

    session = SessionLocal()
    try:
        for name in _WATCHED:
            session.execute(
                text(f"DELETE FROM {name} WHERE id > :max_id"),
                {"max_id": before[name][0]},
            )
        session.commit()
        counts: dict[str, int] = {}
        for name in _WATCHED:
            counts[name] = int(session.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar() or 0)
        return counts
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture(autouse=True)
def restored_rows(migrated_db):
    """Drop rows this test committed and require each watched table's count to match."""
    assert migrated_db
    before = _watermark()
    try:
        yield
    finally:
        after = _delete_above(before)
        expected = {name: before[name][1] for name in _WATCHED}
        assert after == expected, {"before": expected, "after": after}


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


def _norm_sql(sql: str) -> str:
    folded = " ".join(sql.replace("::text", "").split())
    # pg_indexes wraps each column: ((status) = 'open').
    return folded.replace("(status)", "status").replace("(gap_type)", "gap_type")


def _insert_qnr(conn) -> int:
    row = conn.execute(
        text(
            """
            INSERT INTO questionnaires (
                workspace_id, filename, status, created_at, updated_at
            ) VALUES (
                1, :filename, 'parsed',
                TIMESTAMP '2026-01-01 00:00:00', TIMESTAMP '2026-01-01 00:00:00'
            )
            RETURNING id
            """
        ),
        {"filename": f"bug018c-{uuid.uuid4().hex[:8]}.xlsx"},
    ).one()
    return int(row.id)


def _insert_question(conn, questionnaire_id: int) -> int:
    row = conn.execute(
        text(
            """
            INSERT INTO questions (questionnaire_id, text, created_at)
            VALUES (:questionnaire_id, :text, TIMESTAMP '2026-01-01 00:00:00')
            RETURNING id
            """
        ),
        {
            "questionnaire_id": questionnaire_id,
            "text": "Synthetic question for the one-open-gap index.",
        },
    ).one()
    return int(row.id)


def _insert_gap(
    conn,
    *,
    questionnaire_id: int | None,
    question_id: int | None,
    status: str,
    gap_type: str = "missing_evidence",
    reason: str,
) -> int:
    row = conn.execute(
        text(
            """
            INSERT INTO evidence_gaps (
                workspace_id, questionnaire_id, question_id, gap_type, reason, status,
                created_at, updated_at
            ) VALUES (
                1, :questionnaire_id, :question_id, :gap_type, :reason, :status,
                TIMESTAMP '2026-01-01 00:00:00', TIMESTAMP '2026-01-01 00:00:00'
            )
            RETURNING id
            """
        ),
        {
            "questionnaire_id": questionnaire_id,
            "question_id": question_id,
            "gap_type": gap_type,
            "reason": reason,
            "status": status,
        },
    ).one()
    return int(row.id)


def _snapshot(conn, gap_id: int):
    return conn.execute(
        text(
            """
            SELECT status, close_reason, reason, question_id, gap_type
            FROM evidence_gaps WHERE id = :id
            """
        ),
        {"id": gap_id},
    ).one()


def _delete_ids(conn, table: str, ids: list[int]) -> None:
    if not ids:
        return
    if table not in {"evidence_gaps", "questions", "questionnaires"}:
        raise RuntimeError(f"refusing delete from {table}")
    conn.execute(
        text(f"DELETE FROM {table} WHERE id IN :ids").bindparams(bindparam("ids", expanding=True)),
        {"ids": ids},
    )


def _index_names(conn) -> set[str]:
    rows = conn.execute(
        text("SELECT indexname FROM pg_indexes WHERE tablename = 'evidence_gaps'")
    ).all()
    return {row[0] for row in rows}


def _insufficient(question_id: int) -> Answer:
    return Answer(
        question_id=question_id,
        text="Insufficient evidence.",
        status="insufficient_evidence",
        outcome_code="no_evidence",
        insufficient_reason="no_citations",
    )


def test_second_open_gap_for_the_same_question_is_rejected(db_session: Session):
    questionnaire = Questionnaire(
        workspace_id=1,
        filename=f"bug018c-{uuid.uuid4().hex[:8]}.xlsx",
        status="parsed",
    )
    db_session.add(questionnaire)
    db_session.flush()
    first = Question(questionnaire_id=questionnaire.id, text="Synthetic question A.")
    second = Question(questionnaire_id=questionnaire.id, text="Synthetic question B.")
    db_session.add_all([first, second])
    db_session.flush()
    db_session.add(
        EvidenceGap(
            workspace_id=1,
            questionnaire_id=questionnaire.id,
            question_id=first.id,
            gap_type="missing_evidence",
            reason=_MARKER,
            status="open",
        )
    )
    db_session.add(
        EvidenceGap(
            workspace_id=1,
            questionnaire_id=questionnaire.id,
            question_id=second.id,
            gap_type="missing_evidence",
            reason=_MARKER,
            status="open",
        )
    )
    db_session.commit()
    with pytest.raises(IntegrityError) as caught:
        db_session.add(
            EvidenceGap(
                workspace_id=1,
                questionnaire_id=questionnaire.id,
                question_id=first.id,
                gap_type="missing_evidence",
                reason=_MARKER + "-dup",
                status="open",
            )
        )
        db_session.flush()
    db_session.rollback()
    assert "uq_evidence_gaps_one_open_per_question" in str(caught.value)
    db_session.expire_all()
    open_rows = (
        db_session.query(EvidenceGap)
        .filter(EvidenceGap.question_id == first.id, EvidenceGap.status == "open")
        .count()
    )
    assert open_rows == 1


def test_open_and_resolved_for_the_same_question_are_allowed(db_session: Session):
    questionnaire = Questionnaire(
        workspace_id=1,
        filename=f"bug018c-{uuid.uuid4().hex[:8]}.xlsx",
        status="parsed",
    )
    db_session.add(questionnaire)
    db_session.flush()
    question = Question(questionnaire_id=questionnaire.id, text="Synthetic question.")
    db_session.add(question)
    db_session.flush()
    db_session.add_all(
        [
            EvidenceGap(
                workspace_id=1,
                questionnaire_id=questionnaire.id,
                question_id=question.id,
                gap_type="missing_evidence",
                reason=_MARKER,
                status="open",
            ),
            EvidenceGap(
                workspace_id=1,
                questionnaire_id=questionnaire.id,
                question_id=question.id,
                gap_type="missing_evidence",
                reason=_MARKER + "-resolved",
                status="resolved",
                close_reason="answer_sufficient",
            ),
        ]
    )
    db_session.flush()
    stored = (
        db_session.query(EvidenceGap.status)
        .filter(EvidenceGap.question_id == question.id)
        .order_by(EvidenceGap.id)
        .all()
    )
    assert [row.status for row in stored] == ["open", "resolved"]
    db_session.rollback()


def test_several_open_control_checks_with_null_question_are_allowed(db_session: Session):
    """TC-21-006 scan rows have no question and several may be open at once."""
    rows = [
        EvidenceGap(
            workspace_id=1,
            gap_type="control_check",
            reason=_MARKER + f"-scan-{i}",
            status="open",
        )
        for i in range(3)
    ]
    db_session.add_all(rows)
    db_session.flush()
    assert all(row.question_id is None and row.questionnaire_id is None for row in rows)
    assert len({row.id for row in rows}) == 3
    db_session.rollback()


def test_committed_gap_row_is_removed_after_the_test(db_session: Session):
    """A committed row above the watermark is deleted by teardown, not by this test."""
    before = db_session.execute(text("SELECT COALESCE(MAX(id), 0) FROM evidence_gaps")).scalar()
    row = EvidenceGap(
        workspace_id=1,
        gap_type="missing_evidence",
        reason=_MARKER + "-leftover",
        status="open",
    )
    db_session.add(row)
    db_session.commit()
    assert row.id > int(before)


def test_generation_still_opens_one_gap_and_can_open_again_after_resolve(db_session: Session):
    from app.services.evidence_gap_service import generate_gaps_for_questionnaire

    questionnaire = Questionnaire(
        workspace_id=1,
        filename=f"bug018c-{uuid.uuid4().hex[:8]}.xlsx",
        status="parsed",
    )
    db_session.add(questionnaire)
    db_session.flush()
    question = Question(questionnaire_id=questionnaire.id, text="Synthetic question.")
    db_session.add(question)
    db_session.flush()
    db_session.add(_insufficient(question.id))
    db_session.commit()

    first = generate_gaps_for_questionnaire(db_session, 1, questionnaire.id)
    assert first["generated"] == 1
    second = generate_gaps_for_questionnaire(db_session, 1, questionnaire.id)
    assert second == {"generated": 0, "total_insufficient": 1, "resolved": 0}
    db_session.expire_all()
    answer = db_session.query(Answer).filter(Answer.question_id == question.id).one()
    answer.status = "draft"
    answer.outcome_code = None
    answer.insufficient_reason = None
    db_session.commit()
    closed = generate_gaps_for_questionnaire(db_session, 1, questionnaire.id)
    assert closed["resolved"] == 1
    assert closed["generated"] == 0

    db_session.expire_all()
    answer = db_session.query(Answer).filter(Answer.question_id == question.id).one()
    answer.status = "insufficient_evidence"
    answer.outcome_code = "no_evidence"
    answer.insufficient_reason = "no_citations"
    db_session.commit()
    reopened = generate_gaps_for_questionnaire(db_session, 1, questionnaire.id)
    assert reopened["generated"] == 1
    db_session.expire_all()
    gaps = (
        db_session.query(EvidenceGap)
        .filter(EvidenceGap.question_id == question.id)
        .order_by(EvidenceGap.id)
        .all()
    )
    assert [gap.status for gap in gaps] == ["resolved", "open"]


def test_generation_treats_unique_violation_as_already_open(db_session: Session):
    from app.core.database import engine
    from app.services.evidence_gap_service import generate_gaps_for_questionnaire

    questionnaire = Questionnaire(
        workspace_id=1,
        filename=f"bug018c-{uuid.uuid4().hex[:8]}.xlsx",
        status="parsed",
    )
    db_session.add(questionnaire)
    db_session.flush()
    question = Question(questionnaire_id=questionnaire.id, text="Synthetic question.")
    db_session.add(question)
    db_session.flush()
    db_session.add(_insufficient(question.id))
    db_session.commit()
    question_id = question.id
    questionnaire_id = questionnaire.id
    done = {"n": 0}

    def before_flush(session, flush_context, instances):
        if done["n"]:
            return
        pending = [
            obj
            for obj in session.new
            if isinstance(obj, EvidenceGap) and obj.question_id == question_id
        ]
        if not pending:
            return
        done["n"] = 1
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO evidence_gaps (
                        workspace_id, questionnaire_id, question_id, gap_type, reason, status,
                        created_at, updated_at
                    ) VALUES (
                        1, :questionnaire_id, :question_id, 'missing_evidence', :reason, 'open',
                        TIMESTAMP '2026-01-01 00:00:00', TIMESTAMP '2026-01-01 00:00:00'
                    )
                    """
                ),
                {
                    "questionnaire_id": questionnaire_id,
                    "question_id": question_id,
                    "reason": _MARKER + "-already-open",
                },
            )

    event.listen(db_session, "before_flush", before_flush)
    try:
        result = generate_gaps_for_questionnaire(db_session, 1, questionnaire_id)
    finally:
        event.remove(db_session, "before_flush", before_flush)
    assert done["n"] == 1
    assert result["generated"] == 0
    db_session.expire_all()
    gaps = (
        db_session.query(EvidenceGap)
        .filter(EvidenceGap.question_id == question_id, EvidenceGap.status == "open")
        .all()
    )
    assert len(gaps) == 1
    assert gaps[0].reason == _MARKER + "-already-open"


def test_status_update_treats_unique_violation_as_already_open(db_session: Session):
    from app.services.evidence_gap_service import update_evidence_gap_status

    questionnaire = Questionnaire(
        workspace_id=1,
        filename=f"bug018c-{uuid.uuid4().hex[:8]}.xlsx",
        status="parsed",
    )
    db_session.add(questionnaire)
    db_session.flush()
    question = Question(questionnaire_id=questionnaire.id, text="Synthetic question.")
    db_session.add(question)
    db_session.flush()
    open_gap = EvidenceGap(
        workspace_id=1,
        questionnaire_id=questionnaire.id,
        question_id=question.id,
        gap_type="missing_evidence",
        reason=_MARKER + "-open",
        status="open",
    )
    resolved = EvidenceGap(
        workspace_id=1,
        questionnaire_id=questionnaire.id,
        question_id=question.id,
        gap_type="missing_evidence",
        reason=_MARKER + "-resolved",
        status="resolved",
        close_reason="answer_sufficient",
    )
    db_session.add_all([open_gap, resolved])
    db_session.commit()
    result = update_evidence_gap_status(db_session, resolved.id, 1, "open")
    assert result is not None
    assert result["id"] == open_gap.id
    assert result["status"] == "open"
    db_session.expire_all()
    kept = db_session.get(EvidenceGap, resolved.id)
    assert kept is not None
    assert kept.status == "resolved"
    assert kept.close_reason == "answer_sufficient"
    assert (
        db_session.query(EvidenceGap)
        .filter(EvidenceGap.question_id == question.id, EvidenceGap.status == "open")
        .count()
        == 1
    )


def test_model_index_matches_the_migration():
    module = _load_migration()
    from app.models.evidence_gap import (
        GAP_STATUS_OPEN,
        GAP_TYPE_CONTROL_CHECK,
        ONE_OPEN_GAP_INDEX_COLUMNS,
        ONE_OPEN_GAP_INDEX_WHERE,
        UQ_EVIDENCE_GAPS_ONE_OPEN_PER_QUESTION,
    )

    assert module.revision == REVISION
    assert module.down_revision == PARENT
    assert module.OPEN_STATUS == GAP_STATUS_OPEN == "open"
    assert module.EXCLUDED_GAP_TYPE == GAP_TYPE_CONTROL_CHECK == "control_check"
    assert module.INDEX_NAME == UQ_EVIDENCE_GAPS_ONE_OPEN_PER_QUESTION
    assert module.INDEX_COLUMNS == ONE_OPEN_GAP_INDEX_COLUMNS
    assert module.INDEX_WHERE == ONE_OPEN_GAP_INDEX_WHERE
    assert module.INDEX_WHERE == (
        "status = 'open' AND question_id IS NOT NULL AND gap_type <> 'control_check'"
    )
    assert "superseded" not in module.DEDUPE_SQL
    assert "evidence_sufficient" not in module.DEDUPE_SQL
    assert "control_check" in module.DEDUPE_SQL
    indexes = [
        idx
        for idx in EvidenceGap.__table__.indexes
        if idx.name == UQ_EVIDENCE_GAPS_ONE_OPEN_PER_QUESTION
    ]
    assert len(indexes) == 1
    index = indexes[0]
    assert index.unique is True
    assert tuple(column.name for column in index.columns) == ONE_OPEN_GAP_INDEX_COLUMNS
    where = index.dialect_options["postgresql"]["where"]
    assert str(where) == ONE_OPEN_GAP_INDEX_WHERE
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert imported
    assert not any(name == "app" or name.startswith("app.") for name in imported)


def test_prescan_fails_on_duplicate_open_gaps_and_passes_on_clean_data(db_session: Session):
    from app.core.database import engine

    module = _load_migration()
    db_session.rollback()
    engine.dispose()
    gap_ids: list[int] = []
    question_ids: list[int] = []
    questionnaire_ids: list[int] = []
    try:
        _alembic_ok("upgrade", "head")
        with engine.begin() as conn:
            questionnaire_id = _insert_qnr(conn)
            questionnaire_ids.append(questionnaire_id)
            question_a = _insert_question(conn, questionnaire_id)
            question_b = _insert_question(conn, questionnaire_id)
            question_c = _insert_question(conn, questionnaire_id)
            question_ids.extend([question_a, question_b, question_c])
            kept = [
                _insert_gap(
                    conn,
                    questionnaire_id=questionnaire_id,
                    question_id=question_c,
                    status="open",
                    reason=_MARKER + "-kept-open",
                ),
                _insert_gap(
                    conn,
                    questionnaire_id=questionnaire_id,
                    question_id=question_c,
                    status="resolved",
                    reason=_MARKER + "-kept-resolved",
                ),
            ]
            scans = [
                _insert_gap(
                    conn,
                    questionnaire_id=None,
                    question_id=None,
                    status="open",
                    gap_type="control_check",
                    reason=_MARKER + f"-scan-{i}",
                )
                for i in range(3)
            ]
            gap_ids.extend(kept + scans)
        with engine.connect() as conn:
            before = {gap_id: _snapshot(conn, gap_id) for gap_id in gap_ids}

        _alembic_ok("downgrade", module.down_revision)
        with engine.begin() as conn:
            dup_a = [
                _insert_gap(
                    conn,
                    questionnaire_id=questionnaire_id,
                    question_id=question_a,
                    status="open",
                    reason=_MARKER + "-dup-a",
                )
                for _ in range(module.EXAMPLE_LIMIT + 1)
            ]
            dup_b = [
                _insert_gap(
                    conn,
                    questionnaire_id=questionnaire_id,
                    question_id=question_b,
                    status="open",
                    reason=_MARKER + "-dup-b",
                )
                for _ in range(2)
            ]
            gap_ids.extend(dup_a + dup_b)
            questions, open_rows, examples = module.duplicate_open_gaps(conn)
        assert questions == 2
        assert open_rows == module.EXAMPLE_LIMIT + 1 + 2
        assert examples == sorted(dup_a)[: module.EXAMPLE_LIMIT]
        assert dup_a[-1] not in examples
        assert not set(examples) & set(dup_b)
        assert not set(examples) & set(scans)

        failed = _alembic("upgrade", REVISION)
        assert failed.returncode != 0
        message = failed.stderr + failed.stdout
        assert "No rows were changed" in message
        assert f"{questions} question(s) have more than one open gap" in message
        assert f"({open_rows} open row(s))" in message
        assert "Example gap ids: " + ", ".join(str(i) for i in examples) in message
        assert "not run by this migration" in message
        assert "superseded" in message

        with engine.connect() as conn:
            assert {gap_id: _snapshot(conn, gap_id) for gap_id in before} == before
            for gap_id in dup_a + dup_b:
                assert _snapshot(conn, gap_id).status == "open"
            assert module.INDEX_NAME not in _index_names(conn)

        with engine.begin() as conn:
            _delete_ids(conn, "evidence_gaps", dup_a + dup_b)
            for gap_id in dup_a + dup_b:
                gap_ids.remove(gap_id)
            assert module.duplicate_open_gaps(conn) == (0, 0, [])

        _alembic_ok("upgrade", "head")
        with engine.connect() as conn:
            assert {gap_id: _snapshot(conn, gap_id) for gap_id in before} == before
            assert module.INDEX_NAME in _index_names(conn)
            indexdef = conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"),
                {"name": module.INDEX_NAME},
            ).scalar()
        folded = _norm_sql(str(indexdef))
        assert "UNIQUE" in folded.upper()
        assert "status = 'open'" in folded
        assert "question_id IS NOT NULL" in folded
        assert "gap_type <> 'control_check'" in folded
        for column in module.INDEX_COLUMNS:
            assert column in folded
    finally:
        with engine.begin() as conn:
            _delete_ids(conn, "evidence_gaps", gap_ids)
            _delete_ids(conn, "questions", question_ids)
            _delete_ids(conn, "questionnaires", questionnaire_ids)
        _alembic("upgrade", "head")
        engine.dispose()


def test_documented_dedupe_closes_older_rows_without_deleting(db_session: Session):
    from app.core.database import engine

    module = _load_migration()
    db_session.rollback()
    engine.dispose()
    gap_ids: list[int] = []
    question_ids: list[int] = []
    questionnaire_ids: list[int] = []
    try:
        _alembic_ok("downgrade", module.down_revision)
        with engine.begin() as conn:
            questionnaire_id = _insert_qnr(conn)
            questionnaire_ids.append(questionnaire_id)
            question_id = _insert_question(conn, questionnaire_id)
            question_ids.append(question_id)
            older = [
                _insert_gap(
                    conn,
                    questionnaire_id=questionnaire_id,
                    question_id=question_id,
                    status="open",
                    reason=_MARKER + f"-old-{i}",
                )
                for i in range(2)
            ]
            newest = _insert_gap(
                conn,
                questionnaire_id=questionnaire_id,
                question_id=question_id,
                status="open",
                reason=_MARKER + "-newest",
            )
            scans = [
                _insert_gap(
                    conn,
                    questionnaire_id=None,
                    question_id=None,
                    status="open",
                    gap_type="control_check",
                    reason=_MARKER + f"-scan-{i}",
                )
                for i in range(2)
            ]
            gap_ids.extend(older + [newest] + scans)
            before_count = int(
                conn.execute(text("SELECT count(*) FROM evidence_gaps")).scalar() or 0
            )
            conn.execute(text(module.DEDUPE_SQL))
            after_count = int(
                conn.execute(text("SELECT count(*) FROM evidence_gaps")).scalar() or 0
            )
            assert after_count == before_count
            for gap_id in older:
                row = _snapshot(conn, gap_id)
                assert row.status == "resolved"
                assert row.close_reason is None
                assert row.reason == _MARKER + f"-old-{older.index(gap_id)}"
            newest_row = _snapshot(conn, newest)
            assert newest_row.status == "open"
            assert newest_row.reason == _MARKER + "-newest"
            for gap_id in scans:
                row = _snapshot(conn, gap_id)
                assert row.status == "open"
                assert row.question_id is None
                assert row.gap_type == "control_check"
    finally:
        with engine.begin() as conn:
            _delete_ids(conn, "evidence_gaps", gap_ids)
            _delete_ids(conn, "questions", question_ids)
            _delete_ids(conn, "questionnaires", questionnaire_ids)
        _alembic("upgrade", "head")
        engine.dispose()


def test_upgrade_downgrade_upgrade_round_trip(db_session: Session):
    from app.core.database import engine

    module = _load_migration()
    assert module.down_revision == PARENT
    db_session.rollback()
    engine.dispose()
    gap_ids: list[int] = []
    question_ids: list[int] = []
    questionnaire_ids: list[int] = []
    try:
        _alembic_ok("upgrade", "head")
        with engine.begin() as conn:
            questionnaire_id = _insert_qnr(conn)
            questionnaire_ids.append(questionnaire_id)
            question_id = _insert_question(conn, questionnaire_id)
            question_ids.append(question_id)
            for status in ("open", "resolved", "accepted"):
                gap_ids.append(
                    _insert_gap(
                        conn,
                        questionnaire_id=questionnaire_id,
                        question_id=question_id,
                        status=status,
                        reason=f"{_MARKER}-{status}",
                    )
                )
            gap_ids.append(
                _insert_gap(
                    conn,
                    questionnaire_id=None,
                    question_id=None,
                    status="open",
                    gap_type="control_check",
                    reason=_MARKER + "-scan",
                )
            )
        with engine.connect() as conn:
            original = {gap_id: _snapshot(conn, gap_id) for gap_id in gap_ids}
            assert module.INDEX_NAME in _index_names(conn)

        _alembic_ok("downgrade", module.down_revision)
        with engine.connect() as conn:
            assert module.INDEX_NAME not in _index_names(conn)
            assert {gap_id: _snapshot(conn, gap_id) for gap_id in gap_ids} == original

        _alembic_ok("upgrade", "head")
        with engine.connect() as conn:
            assert module.INDEX_NAME in _index_names(conn)
            assert {gap_id: _snapshot(conn, gap_id) for gap_id in gap_ids} == original
        _revision_reaches_every_head(REVISION)
    finally:
        with engine.begin() as conn:
            _delete_ids(conn, "evidence_gaps", gap_ids)
            _delete_ids(conn, "questions", question_ids)
            _delete_ids(conn, "questionnaires", questionnaire_ids)
        _alembic("upgrade", "head")
        engine.dispose()


def test_revision_is_head_or_ancestor_of_every_head():
    _load_migration()
    _revision_reaches_every_head(REVISION)


def test_offline_sql_creates_partial_unique_index_and_downgrade_drops_it():
    module = _load_migration()
    upgrade = _alembic_ok("upgrade", f"{module.down_revision}:{module.revision}", "--sql")
    downgrade = _alembic_ok("downgrade", f"{module.revision}:{module.down_revision}", "--sql")
    folded = _norm_sql(upgrade)
    upper = folded.upper()
    assert f"CREATE UNIQUE INDEX {module.INDEX_NAME}" in folded
    assert "status = 'open'" in folded
    assert "question_id IS NOT NULL" in folded
    assert "control_check" in folded
    for column in module.INDEX_COLUMNS:
        assert column in folded
    assert "UPDATE EVIDENCE_GAPS" not in upper
    assert "DELETE FROM EVIDENCE_GAPS" not in upper
    assert "INSERT INTO EVIDENCE_GAPS" not in upper
    down = _norm_sql(downgrade)
    down_upper = down.upper()
    assert f"DROP INDEX {module.INDEX_NAME}" in down
    assert "CREATE UNIQUE INDEX" not in down_upper
    assert "UPDATE EVIDENCE_GAPS" not in down_upper
    assert "DELETE FROM EVIDENCE_GAPS" not in down_upper
    assert "INSERT INTO EVIDENCE_GAPS" not in down_upper
