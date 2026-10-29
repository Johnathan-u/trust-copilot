"""TC-02-BUG-001a: a parent workspace move must not leave a child in the old workspace.

Synthetic fixtures only. A legacy cross-workspace parent is seeded while the parent-move
migration is downgraded, then the migration is upgraded again. Tests do not disable triggers.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.orm import Session

from app.core.database import engine
from app.main import app
from app.models import Document, Workspace
from app.models.answer import Answer
from app.models.evidence_gap import EvidenceGap
from app.models.evidence_item import EvidenceItem
from app.models.export_record import ExportRecord
from app.models.questionnaire import Question, Questionnaire
from app.services.cross_workspace_audit import run_audit
from app.services.workspace_integrity import (
    PARENT_MOVE_DETAIL,
    ParentWorkspaceMoveBlocked,
    reassign_parent_workspace,
)

OWN = 1
OTHER = 2
API_ROOT = Path(__file__).resolve().parents[2]
PARENT_REVISION = "tc02001a_parent_ws_move"
_PARENT_TABLES = ("documents", "questionnaires")
_DELETE_ORDER = (
    "evidence_gaps",
    "export_records",
    "evidence_items",
    "answers",
    "questions",
    "questionnaires",
    "documents",
    "workspaces",
)
_TRACKED: dict[str, list[int]] = {}


def _track(table: str, row_id: int) -> None:
    _TRACKED.setdefault(table, []).append(row_id)


def _counts(db: Session) -> dict[str, int]:
    return {
        table: db.execute(text(f"SELECT count(*) FROM {table}")).scalar() for table in _DELETE_ORDER
    }


def _delete_tracked(db: Session) -> None:
    for table in _DELETE_ORDER:
        ids = _TRACKED.get(table) or []
        if not ids:
            continue
        statement = text(f"DELETE FROM {table} WHERE id IN :ids").bindparams(
            bindparam("ids", expanding=True)
        )
        db.execute(statement, {"ids": ids})
    db.commit()


@pytest.fixture(autouse=True)
def _committed_rows_return_to_baseline(db_session: Session):
    """Delete rows this module committed. db_session only rolls back its open transaction."""
    _TRACKED.clear()
    before = _counts(db_session)
    yield
    _delete_tracked(db_session)
    assert _counts(db_session) == before
    _TRACKED.clear()


def _alembic(*args: str, database_url: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "TRUST_COPILOT_TESTING": "1", "PGOPTIONS": "-c lock_timeout=20000"}
    if database_url is not None:
        env["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(API_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _parent_down_revision() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    down = ScriptDirectory.from_config(cfg).get_revision(PARENT_REVISION).down_revision
    if not isinstance(down, str):
        raise RuntimeError("parent-move revision must have one parent")
    return down


def move_parent_before_triggers(db: Session, table: str, row_id: int, workspace_id: int) -> None:
    """Move a parent while this migration is downgraded, then return the database to head.

    The row has to be committed so the migration's connection can see it. Callers that
    still need the row reload it afterwards.
    """
    if table not in _PARENT_TABLES:
        raise ValueError(table)
    db.commit()
    db.close()
    down_rev = _parent_down_revision()
    try:
        down = _alembic("downgrade", down_rev)
        if down.returncode != 0:
            raise RuntimeError(down.stderr[-2000:])
        with engine.begin() as conn:
            conn.execute(
                text(f"UPDATE {table} SET workspace_id = :ws WHERE id = :i"),
                {"ws": workspace_id, "i": row_id},
            )
    finally:
        up = _alembic("upgrade", "head")
        if up.returncode != 0:
            raise RuntimeError(up.stderr[-2000:])


def _doc(db: Session, ws: int, tag: str) -> Document:
    row = Document(
        workspace_id=ws,
        storage_key=f"synthetic/example-parent-{tag}.pdf",
        filename=f"example-parent-{tag}.pdf",
        status="indexed",
    )
    db.add(row)
    db.flush()
    _track("documents", row.id)
    return row


def _chain(db: Session, ws: int, tag: str):
    qnr = Questionnaire(workspace_id=ws, filename=f"example-{tag}.xlsx", status="parsed")
    db.add(qnr)
    db.flush()
    _track("questionnaires", qnr.id)
    question = Question(questionnaire_id=qnr.id, text=f"Synthetic {tag} question?")
    db.add(question)
    db.flush()
    _track("questions", question.id)
    answer = Answer(question_id=question.id, text=f"Synthetic {tag} answer", status="draft")
    db.add(answer)
    db.flush()
    _track("answers", answer.id)
    return qnr, question, answer


def _add(db: Session, row, table: str):
    db.add(row)
    db.flush()
    _track(table, row.id)
    return row


def _move(db: Session, **body) -> None:
    model = {
        "document": Document,
        "questionnaire": Questionnaire,
        "question": Question,
        "answer": Answer,
    }[body["kind"]]
    row = db.get(model, body["id"])
    reassign_parent_workspace(
        db,
        row,
        workspace_id=body.get("workspace_id"),
        questionnaire_id=body.get("questionnaire_id"),
        question_id=body.get("question_id"),
    )
    db.commit()


@pytest.mark.parametrize(
    "kind",
    ["document", "questionnaire_export", "questionnaire_gap", "question", "answer"],
)
def test_parent_move_with_child_is_blocked_and_unchanged(db_session: Session, kind) -> None:
    doc = _doc(db_session, OWN, "held")
    qnr, question, answer = _chain(db_session, OWN, "held")
    other_qnr, other_question, _other_answer = _chain(db_session, OTHER, "dest")
    if kind == "document":
        _add(
            db_session,
            EvidenceItem(workspace_id=OWN, title="synthetic example evidence", document_id=doc.id),
            "evidence_items",
        )
        payload = {"kind": "document", "id": doc.id, "workspace_id": OTHER}
        column_sql = "SELECT workspace_id FROM documents WHERE id = :i"
        row_id = doc.id
    elif kind == "questionnaire_export":
        _add(
            db_session,
            ExportRecord(
                workspace_id=OWN,
                questionnaire_id=qnr.id,
                storage_key="synthetic/example-export.xlsx",
                filename="example-export.xlsx",
            ),
            "export_records",
        )
        payload = {"kind": "questionnaire", "id": qnr.id, "workspace_id": OTHER}
        column_sql = "SELECT workspace_id FROM questionnaires WHERE id = :i"
        row_id = qnr.id
    elif kind == "questionnaire_gap":
        _add(
            db_session,
            EvidenceGap(
                workspace_id=OWN,
                questionnaire_id=qnr.id,
                question_id=question.id,
                answer_id=answer.id,
            ),
            "evidence_gaps",
        )
        payload = {"kind": "questionnaire", "id": qnr.id, "workspace_id": OTHER}
        column_sql = "SELECT workspace_id FROM questionnaires WHERE id = :i"
        row_id = qnr.id
    elif kind == "question":
        _add(
            db_session,
            EvidenceGap(workspace_id=OWN, questionnaire_id=qnr.id, question_id=question.id),
            "evidence_gaps",
        )
        payload = {"kind": "question", "id": question.id, "questionnaire_id": other_qnr.id}
        column_sql = "SELECT questionnaire_id FROM questions WHERE id = :i"
        row_id = question.id
    else:
        _add(
            db_session,
            EvidenceGap(workspace_id=OWN, questionnaire_id=qnr.id, answer_id=answer.id),
            "evidence_gaps",
        )
        payload = {"kind": "answer", "id": answer.id, "question_id": other_question.id}
        column_sql = "SELECT question_id FROM answers WHERE id = :i"
        row_id = answer.id
    db_session.commit()
    before = db_session.execute(text(column_sql), {"i": row_id}).scalar()
    with pytest.raises(ParentWorkspaceMoveBlocked):
        _move(db_session, **payload)
    db_session.expire_all()
    after = db_session.execute(text(column_sql), {"i": row_id}).scalar()
    assert after == before


def test_blocked_parent_move_response_is_generic() -> None:
    handler = app.exception_handlers[ParentWorkspaceMoveBlocked]
    response = handler(None, ParentWorkspaceMoveBlocked())
    body = json.loads(response.body)
    assert response.status_code == 409
    assert body == {"detail": PARENT_MOVE_DETAIL}
    assert "TC-" not in response.body.decode()
    assert all(
        getattr(route, "path", None) != "/api/example-synthetic-parent-move"
        for route in app.router.routes
    )


def test_parent_move_without_children_succeeds(db_session: Session) -> None:
    doc = _doc(db_session, OWN, "free")
    qnr, question, answer = _chain(db_session, OWN, "free")
    dest, dest_question, _dest_answer = _chain(db_session, OTHER, "free-dest")
    db_session.commit()
    _move(db_session, kind="document", id=doc.id, workspace_id=OTHER)
    _move(db_session, kind="questionnaire", id=qnr.id, workspace_id=OTHER)
    lone = _add(
        db_session,
        Question(questionnaire_id=qnr.id, text="Synthetic lone question?"),
        "questions",
    )
    db_session.commit()
    _move(db_session, kind="question", id=lone.id, questionnaire_id=dest.id)
    lone_answer = _add(
        db_session,
        Answer(question_id=question.id, text="Synthetic lone answer", status="draft"),
        "answers",
    )
    db_session.commit()
    _move(db_session, kind="answer", id=lone_answer.id, question_id=dest_question.id)
    assert answer.id


def test_service_raises_for_internal_callers(db_session: Session) -> None:
    doc = _doc(db_session, OWN, "service")
    _add(
        db_session,
        EvidenceItem(workspace_id=OWN, title="synthetic example item", document_id=doc.id),
        "evidence_items",
    )
    with pytest.raises(ParentWorkspaceMoveBlocked):
        reassign_parent_workspace(db_session, doc, workspace_id=OTHER)
    db_session.refresh(doc)
    assert doc.workspace_id == OWN


def test_legacy_row_reads_and_unrelated_update_succeed_but_move_does_not(
    db_session: Session,
) -> None:
    doc = _doc(db_session, OWN, "legacy")
    item = _add(
        db_session,
        EvidenceItem(workspace_id=OWN, title="synthetic example legacy", document_id=doc.id),
        "evidence_items",
    )
    doc_id = doc.id
    item_id = item.id
    move_parent_before_triggers(db_session, "documents", doc_id, OTHER)
    doc = db_session.get(Document, doc_id)
    item = db_session.get(EvidenceItem, item_id)
    assert doc.workspace_id == OTHER
    assert item.document_id == doc.id
    item.title = "synthetic example legacy renamed"
    db_session.commit()
    doc.filename = "example-legacy-renamed.pdf"
    db_session.commit()
    db_session.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('workspaces', 'id'), "
            "(SELECT COALESCE(MAX(id), 1) FROM workspaces))"
        )
    )
    third = _add(
        db_session,
        Workspace(name="Synthetic example third", slug=f"example-third-{doc.id}"),
        "workspaces",
    )
    db_session.commit()
    with pytest.raises(ParentWorkspaceMoveBlocked):
        _move(db_session, kind="document", id=doc.id, workspace_id=third.id)
    db_session.refresh(doc)
    assert doc.workspace_id == OTHER
    assert doc.filename == "example-legacy-renamed.pdf"


def test_detection_script_counts_fixture_rows(db_session: Session) -> None:
    doc = _doc(db_session, OWN, "count")
    qnr, question, answer = _chain(db_session, OWN, "count")
    _add(
        db_session,
        EvidenceItem(workspace_id=OWN, title="synthetic example count", document_id=doc.id),
        "evidence_items",
    )
    _add(
        db_session,
        ExportRecord(
            workspace_id=OWN,
            questionnaire_id=qnr.id,
            storage_key="synthetic/example-count.xlsx",
            filename="example-count.xlsx",
        ),
        "export_records",
    )
    _add(
        db_session,
        EvidenceGap(
            workspace_id=OWN,
            questionnaire_id=qnr.id,
            question_id=question.id,
            answer_id=answer.id,
        ),
        "evidence_gaps",
    )
    doc_id = doc.id
    qnr_id = qnr.id
    move_parent_before_triggers(db_session, "documents", doc_id, OTHER)
    move_parent_before_triggers(db_session, "questionnaires", qnr_id, OTHER)
    report = run_audit(db_session.connection(), read_only=False)
    counts = {row["check"]: row["count"] for row in report["checks"]}
    assert counts["evidence_items.document_id"] >= 1
    assert counts["export_records.questionnaire_id"] >= 1
    assert counts["evidence_gaps.questionnaire_id"] >= 1
    assert counts["evidence_gaps.question_id"] >= 1
    assert counts["evidence_gaps.answer_id"] >= 1

    env = os.environ.copy()
    proc = subprocess.run(
        [sys.executable, "scripts/detect_parent_workspace_drift.py"],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, proc.stderr
    payload = json.loads(proc.stdout)
    names = {row["check"] for row in payload["checks"]}
    assert names == {
        "evidence_items.document_id",
        "export_records.questionnaire_id",
        "evidence_gaps.questionnaire_id",
        "evidence_gaps.question_id",
        "evidence_gaps.answer_id",
    }
    assert payload["total"] >= 5


def test_downgrade_round_trip_on_a_fresh_database() -> None:
    """A database of its own: downgrade lets the move through, upgrade brings the 409 back."""
    source = os.environ["DATABASE_URL"]
    parsed = urlparse(source)
    name = "tc_parent_move_roundtrip_test"
    admin = urlunparse(parsed._replace(path="/postgres"))
    fresh = urlunparse(parsed._replace(path=f"/{name}"))
    fresh_engine = None
    admin_engine = create_engine(admin, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {name}"))
    admin_engine.dispose()
    try:
        upgraded = _alembic("upgrade", "head", database_url=fresh)
        assert upgraded.returncode == 0, upgraded.stderr[-2000:]
        fresh_engine = create_engine(fresh)
        with fresh_engine.begin() as conn:
            conn.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence('workspaces', 'id'), "
                    "(SELECT COALESCE(MAX(id), 1) FROM workspaces))"
                )
            )
        from sqlalchemy.orm import sessionmaker

        FreshSession = sessionmaker(bind=fresh_engine)
        fresh_db = FreshSession()
        home = Workspace(name="synthetic example roundtrip", slug="example-roundtrip")
        away = Workspace(name="synthetic example roundtrip other", slug="example-roundtrip-other")
        third = Workspace(name="synthetic example roundtrip third", slug="example-roundtrip-third")
        fresh_db.add_all([home, away, third])
        fresh_db.flush()
        doc = Document(
            workspace_id=home.id,
            storage_key="synthetic/example-roundtrip.pdf",
            filename="example-roundtrip.pdf",
            status="indexed",
        )
        fresh_db.add(doc)
        fresh_db.flush()
        fresh_db.add(
            EvidenceItem(
                workspace_id=home.id,
                title="synthetic example roundtrip",
                document_id=doc.id,
            )
        )
        fresh_db.commit()
        document_id = doc.id
        away_id = away.id
        third_id = third.id
        try:
            with pytest.raises(ParentWorkspaceMoveBlocked):
                reassign_parent_workspace(fresh_db, doc, workspace_id=away_id)
            fresh_db.rollback()
            fresh_db.close()
            down = _alembic("downgrade", _parent_down_revision(), database_url=fresh)
            assert down.returncode == 0, down.stderr[-2000:]
            fresh_db = FreshSession()
            doc = fresh_db.get(Document, document_id)
            reassign_parent_workspace(fresh_db, doc, workspace_id=away_id)
            fresh_db.commit()
            assert fresh_db.get(Document, document_id).workspace_id == away_id
        finally:
            fresh_db.close()
            up = _alembic("upgrade", "head", database_url=fresh)
            assert up.returncode == 0, up.stderr[-2000:]
        fresh_db = FreshSession()
        try:
            doc = fresh_db.get(Document, document_id)
            with pytest.raises(ParentWorkspaceMoveBlocked):
                reassign_parent_workspace(fresh_db, doc, workspace_id=third_id)
            fresh_db.rollback()
        finally:
            fresh_db.close()
        heads = _alembic("heads", database_url=fresh)
        assert heads.returncode == 0, heads.stderr[-2000:]
        head_lines = [line for line in heads.stdout.splitlines() if "(head)" in line]
        assert len(head_lines) == 1
        current = _alembic("current", database_url=fresh)
        assert current.returncode == 0, current.stderr[-2000:]
        assert "(head)" in current.stdout
    finally:
        if fresh_engine is not None:
            fresh_engine.dispose()
        admin_engine = create_engine(admin, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        admin_engine.dispose()
