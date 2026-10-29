"""Provenance ids on coverage recommended_evidence.

Synthetic rows only. Every table this module writes is counted and restored.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.password import hash_password
from app.models import Document, EvidenceGap, EvidenceItem, Question, Questionnaire
from app.models.answer import Answer
from app.models.user import User, WorkspaceMember
from app.models.workspace import Workspace
from app.models.workspace_control import WorkspaceControl
from app.services.compliance_coverage import CONTROL_COVERAGE_SCHEMA, get_compliance_coverage

_COUNTED = (
    "answers",
    "evidence_gaps",
    "questions",
    "questionnaires",
    "evidence_items",
    "documents",
    "workspace_controls",
    "user_sessions",
    "audit_events",
    "workspace_members",
    "users",
    "workspaces",
)
_DELETE_ORDER = (
    "audit_events",
    "user_sessions",
    "answers",
    "evidence_gaps",
    "questions",
    "questionnaires",
    "evidence_items",
    "documents",
    "workspace_controls",
    "workspace_members",
    "users",
    "workspaces",
)


def _db() -> Session:
    return SessionLocal()


def _counts() -> dict[str, int]:
    session = _db()
    try:
        return {
            name: int(session.execute(text(f"SELECT count(*) FROM {name}")).scalar() or 0)
            for name in _COUNTED
        }
    finally:
        session.close()


def _ids() -> dict[str, set[int]]:
    session = _db()
    try:
        found = {}
        for name in _COUNTED:
            rows = session.execute(text(f"SELECT id FROM {name}")).fetchall()
            found[name] = {row[0] for row in rows}
        return found
    finally:
        session.close()


def _delete_created(before: dict[str, set[int]]) -> None:
    session = _db()
    try:
        for name in _DELETE_ORDER:
            current = {row[0] for row in session.execute(text(f"SELECT id FROM {name}")).fetchall()}
            created = sorted(current - before[name])
            if not created:
                continue
            statement = text(f"DELETE FROM {name} WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            )
            session.execute(statement, {"ids": created})
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture
def restored_counts():
    before = _counts()
    before_ids = _ids()
    try:
        yield
    finally:
        _delete_created(before_ids)
        assert _counts() == before


def _coverage(workspace_id: int) -> dict:
    session = _db()
    try:
        return get_compliance_coverage(session, workspace_id)
    finally:
        session.close()


def _stamp() -> datetime:
    return datetime(2026, 4, 1, tzinfo=timezone.utc)


def test_recommendations_carry_live_same_workspace_ids(client: TestClient, restored_counts):
    token = uuid.uuid4().hex[:10]
    session = _db()
    try:
        workspace = Workspace(name="Synthetic coverage", slug=f"tc21007b-{token}")
        other = Workspace(name="Synthetic other", slug=f"tc21007b-other-{token}")
        session.add_all([workspace, other])
        session.flush()
        user = User(
            email=f"tc21007b-{token}@trust.local",
            password_hash=hash_password("example-synthetic-tc21007b"),
            display_name="Synthetic reviewer",
        )
        session.add(user)
        session.flush()
        session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="reviewer"))
        own_qnr = Questionnaire(
            workspace_id=workspace.id, filename=f"own-{token}.txt", status="parsed"
        )
        deleted_qnr = Questionnaire(
            workspace_id=workspace.id,
            filename=f"deleted-{token}.txt",
            status="parsed",
            deleted_at=_stamp(),
        )
        session.add_all([own_qnr, deleted_qnr])
        session.flush()
        own_question = Question(questionnaire_id=own_qnr.id, text="Synthetic own question")
        deleted_question = Question(
            questionnaire_id=deleted_qnr.id, text="Synthetic deleted question"
        )
        session.add_all([own_question, deleted_question])
        session.flush()
        own_doc = Document(
            workspace_id=workspace.id,
            storage_key=f"synthetic/{token}",
            filename=f"own-{token}.txt",
        )
        deleted_doc = Document(
            workspace_id=workspace.id,
            storage_key=f"synthetic/{token}-deleted",
            filename=f"deleted-{token}.txt",
            deleted_at=_stamp(),
        )
        foreign_doc = Document(
            workspace_id=other.id,
            storage_key=f"synthetic/{token}-other",
            filename=f"foreign-{token}.txt",
        )
        session.add_all([own_doc, deleted_doc, foreign_doc])
        session.flush()
        own_evidence = EvidenceItem(
            workspace_id=workspace.id,
            document_id=own_doc.id,
            source_type="document",
            title=f"Synthetic evidence {token}",
        )
        deleted_evidence = EvidenceItem(
            workspace_id=workspace.id,
            document_id=deleted_doc.id,
            source_type="document",
            title=f"Synthetic deleted evidence {token}",
        )
        foreign_evidence = EvidenceItem(
            workspace_id=other.id,
            document_id=foreign_doc.id,
            source_type="document",
            title=f"Synthetic foreign evidence {token}",
        )
        session.add_all([own_evidence, deleted_evidence, foreign_evidence])
        session.flush()
        own_control = WorkspaceControl(
            workspace_id=workspace.id,
            custom_name=f"Synthetic control {token}",
            status="not_implemented",
        )
        foreign_control = WorkspaceControl(
            workspace_id=other.id,
            custom_name=f"Synthetic other control {token}",
            status="not_implemented",
        )
        session.add_all([own_control, foreign_control])
        session.flush()
        sourced = EvidenceGap(
            workspace_id=workspace.id,
            gap_type="missing_evidence",
            status="open",
            suggested_evidence_doc_title=f"Synthetic sourced {token}",
            question_id=own_question.id,
            control_id=own_control.id,
            evidence_refs=json.dumps(
                [own_evidence.id, deleted_evidence.id, foreign_evidence.id, True]
            ),
            created_at=_stamp(),
            updated_at=_stamp(),
        )
        dropped = EvidenceGap(
            workspace_id=workspace.id,
            gap_type="missing_evidence",
            status="open",
            suggested_evidence_doc_title=f"Synthetic dropped {token}",
            question_id=deleted_question.id,
            control_id=foreign_control.id,
            evidence_refs=json.dumps([foreign_evidence.id, deleted_evidence.id]),
            created_at=_stamp(),
            updated_at=_stamp(),
        )
        empty = EvidenceGap(
            workspace_id=workspace.id,
            gap_type="missing_evidence",
            status="open",
            suggested_evidence_doc_title=f"Synthetic sourceless {token}",
            evidence_refs="[]",
            created_at=_stamp(),
            updated_at=_stamp(),
        )
        session.add_all([sourced, dropped, empty])
        session.commit()
        workspace_id = workspace.id
        email = user.email
        sourced_id = sourced.id
        own_evidence_id = own_evidence.id
        own_control_id = own_control.id
        own_question_id = own_question.id
        sourced_title = sourced.suggested_evidence_doc_title
        dropped_title = dropped.suggested_evidence_doc_title
        empty_title = empty.suggested_evidence_doc_title
    finally:
        session.close()

    payload = _coverage(workspace_id)
    assert payload["control_coverage"]["schema_version"] == CONTROL_COVERAGE_SCHEMA
    by_title = {item["title"]: item for item in payload["recommended_evidence"]}
    sourced_row = by_title[sourced_title]
    assert sourced_row["evidence_ids"] == [own_evidence_id]
    assert sourced_row["control_ids"] == [own_control_id]
    assert sourced_row["question_ids"] == [own_question_id]
    assert sourced_row["improves_questions"] == 1
    dropped_row = by_title[dropped_title]
    assert dropped_row["evidence_ids"] == []
    assert dropped_row["control_ids"] == []
    assert dropped_row["question_ids"] == []
    assert dropped_row["improves_questions"] == 1
    assert by_title[empty_title]["evidence_ids"] == []
    assert by_title[empty_title]["control_ids"] == []
    assert by_title[empty_title]["question_ids"] == []

    session = _db()
    try:
        before_stamp = session.execute(
            text("SELECT updated_at FROM evidence_gaps WHERE id = :id"),
            {"id": sourced_id},
        ).scalar()
    finally:
        session.close()
    client.cookies.clear()
    logged = client.post(
        "/api/auth/login", json={"email": email, "password": "example-synthetic-tc21007b"}
    )
    assert logged.status_code == 200, logged.text
    before = _counts()
    response = client.get("/api/compliance-coverage")
    assert response.status_code == 200, response.text
    body = {item["title"]: item for item in response.json()["recommended_evidence"]}
    assert body[sourced_title]["evidence_ids"] == [own_evidence_id]
    assert _counts() == before
    session = _db()
    try:
        after_stamp = session.execute(
            text("SELECT updated_at FROM evidence_gaps WHERE id = :id"),
            {"id": sourced_id},
        ).scalar()
    finally:
        session.close()
    assert after_stamp == before_stamp


def test_every_fixture_recommendation_has_a_drill_target(restored_counts):
    """Questions counted by improves_questions are the live question ids."""
    token = uuid.uuid4().hex[:10]
    session = _db()
    try:
        workspace = Workspace(name="Synthetic drill", slug=f"tc21007b-drill-{token}")
        session.add(workspace)
        session.flush()
        questionnaire = Questionnaire(
            workspace_id=workspace.id, filename=f"drill-{token}.txt", status="parsed"
        )
        session.add(questionnaire)
        session.flush()
        first_question = Question(questionnaire_id=questionnaire.id, text="Synthetic first")
        second_question = Question(questionnaire_id=questionnaire.id, text="Synthetic second")
        session.add_all([first_question, second_question])
        session.flush()
        document = Document(
            workspace_id=workspace.id,
            storage_key=f"synthetic/drill-{token}",
            filename=f"drill-{token}.txt",
        )
        session.add(document)
        session.flush()
        evidence = EvidenceItem(
            workspace_id=workspace.id,
            document_id=document.id,
            source_type="document",
            title=f"Synthetic drill evidence {token}",
        )
        session.add(evidence)
        session.flush()
        control = WorkspaceControl(
            workspace_id=workspace.id,
            custom_name=f"Synthetic drill control {token}",
            status="not_implemented",
        )
        session.add(control)
        session.flush()
        question_title = f"Synthetic questions {token}"
        evidence_title = f"Synthetic evidence doc {token}"
        control_title = f"Synthetic control doc {token}"
        session.add_all(
            [
                EvidenceGap(
                    workspace_id=workspace.id,
                    gap_type="missing_evidence",
                    status="open",
                    suggested_evidence_doc_title=question_title,
                    question_id=first_question.id,
                    created_at=_stamp(),
                    updated_at=_stamp(),
                ),
                EvidenceGap(
                    workspace_id=workspace.id,
                    gap_type="missing_evidence",
                    status="open",
                    suggested_evidence_doc_title=question_title,
                    question_id=second_question.id,
                    created_at=_stamp(),
                    updated_at=_stamp(),
                ),
                EvidenceGap(
                    workspace_id=workspace.id,
                    gap_type="missing_evidence",
                    status="open",
                    suggested_evidence_doc_title=evidence_title,
                    evidence_refs=json.dumps([evidence.id]),
                    created_at=_stamp(),
                    updated_at=_stamp(),
                ),
                EvidenceGap(
                    workspace_id=workspace.id,
                    gap_type="missing_evidence",
                    status="open",
                    suggested_evidence_doc_title=control_title,
                    control_id=control.id,
                    created_at=_stamp(),
                    updated_at=_stamp(),
                ),
            ]
        )
        session.commit()
        workspace_id = workspace.id
        question_ids = [first_question.id, second_question.id]
        evidence_id = evidence.id
        control_id = control.id
    finally:
        session.close()

    payload = _coverage(workspace_id)
    rows = payload["recommended_evidence"]
    assert rows
    for item in rows:
        assert item["evidence_ids"] or item["control_ids"] or item["question_ids"], item
    questions = next(item for item in rows if item["title"] == question_title)
    assert questions["improves_questions"] == 2
    assert questions["question_ids"] == sorted(question_ids)
    evidence_row = next(item for item in rows if item["title"] == evidence_title)
    assert evidence_row["evidence_ids"] == [evidence_id]
    control_row = next(item for item in rows if item["title"] == control_title)
    assert control_row["control_ids"] == [control_id]


def test_inferred_recommendation_uses_the_stored_question(restored_counts):
    token = uuid.uuid4().hex[:10]
    session = _db()
    try:
        workspace = Workspace(name="Synthetic infer", slug=f"tc21007b-infer-{token}")
        session.add(workspace)
        session.flush()
        questionnaire = Questionnaire(
            workspace_id=workspace.id, filename=f"infer-{token}.txt", status="parsed"
        )
        session.add(questionnaire)
        session.flush()
        question = Question(questionnaire_id=questionnaire.id, text="Synthetic insufficient")
        session.add(question)
        session.flush()
        session.add(
            Answer(
                question_id=question.id,
                text="",
                status="insufficient_evidence",
                confidence=10,
                primary_categories_json=json.dumps(
                    {"frameworks": ["Synthetic"], "subjects": ["Synthetic Subject"]}
                ),
                citations="[]",
            )
        )
        session.commit()
        workspace_id = workspace.id
        question_id = question.id
    finally:
        session.close()

    payload = _coverage(workspace_id)
    match = [
        item for item in payload["recommended_evidence"] if question_id in item["question_ids"]
    ]
    assert len(match) == 1
    assert match[0]["evidence_ids"] == []
    assert match[0]["control_ids"] == []
    assert match[0]["improves_questions"] >= 1
    assert payload["control_coverage"]["schema_version"] == CONTROL_COVERAGE_SCHEMA
