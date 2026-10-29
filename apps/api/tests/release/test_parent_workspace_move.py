"""TC-02-BUG-001a: a parent workspace move must not leave a child in the old workspace.

Synthetic fixtures only. Legacy rows are inserted with user triggers disabled so the
fixture can represent data that already crossed workspaces.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from fastapi import Depends

from app.core.database import get_db
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
MOVE_PATH = "/api/example-synthetic-parent-move"
API_ROOT = Path(__file__).resolve().parents[2]


def _ensure_move_route() -> None:
    if any(getattr(route, "path", None) == MOVE_PATH for route in app.router.routes):
        return

    @app.post(MOVE_PATH)
    def move(body: dict, db: Session = Depends(get_db)):
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
        return {"ok": True}


@pytest.fixture(autouse=True)
def _route():
    _ensure_move_route()


def _doc(db: Session, ws: int, tag: str) -> Document:
    row = Document(
        workspace_id=ws,
        storage_key=f"synthetic/example-parent-{tag}.pdf",
        filename=f"example-parent-{tag}.pdf",
        status="indexed",
    )
    db.add(row)
    db.flush()
    return row


def _chain(db: Session, ws: int, tag: str):
    qnr = Questionnaire(workspace_id=ws, filename=f"example-{tag}.xlsx", status="parsed")
    db.add(qnr)
    db.flush()
    question = Question(questionnaire_id=qnr.id, text=f"Synthetic {tag} question?")
    db.add(question)
    db.flush()
    answer = Answer(question_id=question.id, text=f"Synthetic {tag} answer", status="draft")
    db.add(answer)
    db.flush()
    return qnr, question, answer


def _legacy_parent_move(db: Session, table: str, row_id: int, workspace_id: int) -> None:
    db.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
    db.execute(
        text(f"UPDATE {table} SET workspace_id = :ws WHERE id = :i"),
        {"ws": workspace_id, "i": row_id},
    )
    db.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))


def _move(client: TestClient, **body):
    return client.post(MOVE_PATH, json=body)


@pytest.mark.parametrize(
    "kind",
    ["document", "questionnaire_export", "questionnaire_gap", "question", "answer"],
)
def test_parent_move_with_child_is_409_and_unchanged(
    client: TestClient, db_session: Session, kind
) -> None:
    doc = _doc(db_session, OWN, "held")
    qnr, question, answer = _chain(db_session, OWN, "held")
    other_qnr, other_question, _other_answer = _chain(db_session, OTHER, "dest")
    if kind == "document":
        db_session.add(
            EvidenceItem(
                workspace_id=OWN,
                title="synthetic example evidence",
                document_id=doc.id,
            )
        )
        payload = {"kind": "document", "id": doc.id, "workspace_id": OTHER}
        column_sql = "SELECT workspace_id FROM documents WHERE id = :i"
        row_id = doc.id
    elif kind == "questionnaire_export":
        db_session.add(
            ExportRecord(
                workspace_id=OWN,
                questionnaire_id=qnr.id,
                storage_key="synthetic/example-export.xlsx",
                filename="example-export.xlsx",
            )
        )
        payload = {"kind": "questionnaire", "id": qnr.id, "workspace_id": OTHER}
        column_sql = "SELECT workspace_id FROM questionnaires WHERE id = :i"
        row_id = qnr.id
    elif kind == "questionnaire_gap":
        db_session.add(
            EvidenceGap(
                workspace_id=OWN,
                questionnaire_id=qnr.id,
                question_id=question.id,
                answer_id=answer.id,
            )
        )
        payload = {"kind": "questionnaire", "id": qnr.id, "workspace_id": OTHER}
        column_sql = "SELECT workspace_id FROM questionnaires WHERE id = :i"
        row_id = qnr.id
    elif kind == "question":
        db_session.add(
            EvidenceGap(workspace_id=OWN, questionnaire_id=qnr.id, question_id=question.id)
        )
        payload = {
            "kind": "question",
            "id": question.id,
            "questionnaire_id": other_qnr.id,
        }
        column_sql = "SELECT questionnaire_id FROM questions WHERE id = :i"
        row_id = question.id
    else:
        db_session.add(EvidenceGap(workspace_id=OWN, questionnaire_id=qnr.id, answer_id=answer.id))
        payload = {"kind": "answer", "id": answer.id, "question_id": other_question.id}
        column_sql = "SELECT question_id FROM answers WHERE id = :i"
        row_id = answer.id
    db_session.commit()
    before = db_session.execute(text(column_sql), {"i": row_id}).scalar()
    response = _move(client, **payload)
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": PARENT_MOVE_DETAIL}
    assert "TC-" not in response.json()["detail"]
    db_session.expire_all()
    after = db_session.execute(text(column_sql), {"i": row_id}).scalar()
    assert after == before


def test_parent_move_without_children_succeeds(client: TestClient, db_session: Session) -> None:
    doc = _doc(db_session, OWN, "free")
    qnr, question, answer = _chain(db_session, OWN, "free")
    dest, dest_question, _dest_answer = _chain(db_session, OTHER, "free-dest")
    db_session.commit()
    assert _move(client, kind="document", id=doc.id, workspace_id=OTHER).status_code == 200
    assert _move(client, kind="questionnaire", id=qnr.id, workspace_id=OTHER).status_code == 200
    lone = Question(questionnaire_id=qnr.id, text="Synthetic lone question?")
    db_session.add(lone)
    db_session.commit()
    assert _move(client, kind="question", id=lone.id, questionnaire_id=dest.id).status_code == 200
    lone_answer = Answer(question_id=question.id, text="Synthetic lone answer", status="draft")
    db_session.add(lone_answer)
    db_session.commit()
    assert (
        _move(client, kind="answer", id=lone_answer.id, question_id=dest_question.id).status_code
        == 200
    )


def test_service_raises_for_internal_callers(db_session: Session) -> None:
    doc = _doc(db_session, OWN, "service")
    db_session.add(
        EvidenceItem(workspace_id=OWN, title="synthetic example item", document_id=doc.id)
    )
    db_session.flush()
    with pytest.raises(ParentWorkspaceMoveBlocked):
        reassign_parent_workspace(db_session, doc, workspace_id=OTHER)
    db_session.refresh(doc)
    assert doc.workspace_id == OWN


def test_legacy_row_reads_and_unrelated_update_succeed_but_move_does_not(
    client: TestClient, db_session: Session
) -> None:
    doc = _doc(db_session, OWN, "legacy")
    item = EvidenceItem(workspace_id=OWN, title="synthetic example legacy", document_id=doc.id)
    db_session.add(item)
    db_session.flush()
    _legacy_parent_move(db_session, "documents", doc.id, OTHER)
    db_session.commit()
    db_session.refresh(doc)
    db_session.refresh(item)
    assert doc.workspace_id == OTHER
    assert item.document_id == doc.id
    item.title = "synthetic example legacy renamed"
    db_session.commit()
    doc.filename = "example-legacy-renamed.pdf"
    db_session.commit()
    # Seed workspaces use explicit ids, so a fresh database's sequence still points at them.
    db_session.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('workspaces', 'id'), "
            "(SELECT COALESCE(MAX(id), 1) FROM workspaces))"
        )
    )
    third = Workspace(name="Synthetic example third", slug=f"example-third-{doc.id}")
    db_session.add(third)
    db_session.commit()
    response = _move(client, kind="document", id=doc.id, workspace_id=third.id)
    assert response.status_code == 409
    db_session.refresh(doc)
    assert doc.workspace_id == OTHER
    assert doc.filename == "example-legacy-renamed.pdf"


def test_detection_script_counts_fixture_rows(db_session: Session) -> None:
    doc = _doc(db_session, OWN, "count")
    qnr, question, answer = _chain(db_session, OWN, "count")
    db_session.add(
        EvidenceItem(workspace_id=OWN, title="synthetic example count", document_id=doc.id)
    )
    db_session.add(
        ExportRecord(
            workspace_id=OWN,
            questionnaire_id=qnr.id,
            storage_key="synthetic/example-count.xlsx",
            filename="example-count.xlsx",
        )
    )
    db_session.add(
        EvidenceGap(
            workspace_id=OWN,
            questionnaire_id=qnr.id,
            question_id=question.id,
            answer_id=answer.id,
        )
    )
    db_session.flush()
    _legacy_parent_move(db_session, "documents", doc.id, OTHER)
    _legacy_parent_move(db_session, "questionnaires", qnr.id, OTHER)
    db_session.commit()
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
