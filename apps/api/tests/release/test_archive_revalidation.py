"""TC-08-006: archive and replacement mark the approved revision stale.

The historical approved text stays readable. Retrieval already drops a
soft-deleted or replaced chunk. Final export stays blocked until a new
revision is approved against a document that is still active. Accepting a
suggested chunk rejects a document that is soft-deleted or not eligible.

Fixtures are synthetic. No customer document and no credential material.
"""

from __future__ import annotations

import json
import uuid
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api.routes.answers import AnswerUpdate, answer_revision_token, update_answer
from app.api.routes.compliance_controls import (
    AcceptSuggestedEvidenceBody,
    accept_suggested_evidence,
)
from app.api.routes.documents import delete_document, restore_document
from app.api.routes.exports import _export_claimed
from app.api.routes.questionnaires import get_questionnaire
from app.core.corpus_version import get_corpus_version
from app.core.job_errors import TerminalJobError
from app.models import (
    Answer,
    Chunk,
    Document,
    EvidenceItem,
    Job,
    Question,
    Questionnaire,
    Workspace,
    WorkspaceControl,
)
from app.services.answer_revisions import approve_draft_revision, insert_draft_revision
from app.services.retrieval import RetrievalService
from app.worker import run_export

APPROVED_TEXT = "Access reviews run each quarter."
REVISED_TEXT = "Access reviews run each quarter against the current policy."
INSUFFICIENT_TEXT = "Insufficient evidence."


def _sync_sequences(db: Session) -> None:
    for table in (
        "workspaces",
        "documents",
        "chunks",
        "questionnaires",
        "questions",
        "answers",
        "workspace_controls",
        "jobs",
        "evidence_items",
        "answer_revisions",
        "export_records",
    ):
        db.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"GREATEST((SELECT COALESCE(MAX(id), 0) FROM {table}), 1))"
            )
        )


def _session(workspace_id: int) -> dict:
    return {
        "workspace_id": workspace_id,
        "user_id": None,
        "email": "synthetic@example.com",
    }


def _request() -> Request:
    return Request({"type": "http", "headers": [(b"host", b"localhost")]})


def _cleanup(db: Session, workspace_id: int) -> None:
    db.rollback()
    if workspace_id <= 3:
        raise RuntimeError(f"refusing to delete seed workspace {workspace_id}")
    db.execute(text("DELETE FROM audit_events WHERE workspace_id = :w"), {"w": workspace_id})
    db.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": workspace_id})
    db.commit()


def _workspace(db: Session, marker: str) -> Workspace:
    row = Workspace(name=f"tc08006-{marker}", slug=f"tc08006-{marker}")
    db.add(row)
    db.flush()
    return row


def _questionnaire(db: Session, workspace_id: int, marker: str) -> Questionnaire:
    row = Questionnaire(
        workspace_id=workspace_id,
        filename=f"synthetic-{marker}.xlsx",
        storage_key=f"synthetic/{marker}/questionnaire.xlsx",
        status="parsed",
    )
    db.add(row)
    db.flush()
    return row


def _question(db: Session, questionnaire_id: int, text_value: str) -> Question:
    row = Question(questionnaire_id=questionnaire_id, text=text_value)
    db.add(row)
    db.flush()
    return row


def _document(
    db: Session,
    workspace_id: int,
    marker: str,
    role: str,
    *,
    status: str = "indexed",
    storage_key: str | None = None,
) -> Document:
    row = Document(
        workspace_id=workspace_id,
        storage_key=storage_key or f"synthetic/{marker}/{role}.txt",
        filename=f"{role}-{marker}.txt",
        status=status,
    )
    db.add(row)
    db.flush()
    return row


def _chunk(
    db: Session,
    workspace_id: int,
    document: Document,
    role: str,
    *,
    source_version: str | None = None,
) -> Chunk:
    metadata: dict = {"document_id": document.id, "filename": document.filename}
    if source_version is not None:
        metadata["source_version"] = source_version
    row = Chunk(
        workspace_id=workspace_id,
        document_id=document.id,
        text=f"Synthetic designated policy for {role}.",
        metadata_=metadata,
    )
    db.add(row)
    db.flush()
    return row


def _answer(
    db: Session,
    question_id: int,
    text_value: str,
    status: str,
    citations: list[dict],
) -> Answer:
    row = Answer(
        question_id=question_id,
        text=text_value,
        status=status,
        citations=json.dumps(citations),
    )
    db.add(row)
    db.flush()
    return row


def _read(db: Session, questionnaire_id: int, workspace_id: int) -> dict:
    return get_questionnaire(
        questionnaire_id,
        workspace_id=workspace_id,
        session=_session(workspace_id),
        db=db,
    )


def _answer_on(body: dict, question_id: int) -> dict:
    for question in body["questions"]:
        if question["id"] == question_id:
            return question["answer"]
    raise AssertionError(f"question {question_id} missing")


def _export(db: Session, questionnaire_id: int, workspace_id: int):
    return _export_claimed(
        questionnaire_id,
        workspace_id,
        None,
        _session(workspace_id),
        db,
        None,
        None,
    )


def _approve_new_revision(db: Session, answer: Answer, document: Document, chunk: Chunk) -> None:
    db.refresh(answer)
    revision = insert_draft_revision(
        db,
        answer,
        {
            "text": REVISED_TEXT,
            "citations": [
                {
                    "chunk_id": chunk.id,
                    "document_id": document.id,
                    "snippet": "current policy",
                }
            ],
        },
    )
    db.commit()
    db.refresh(answer)
    approve_draft_revision(db, answer, revision.id)
    db.commit()


@pytest.fixture
def db(db_session: Session, _ensure_test_data: bool) -> Session:
    if _ensure_test_data is False:
        pytest.skip("database unavailable")
    _sync_sequences(db_session)
    return db_session


def test_approval_binds_the_supporting_document(db: Session) -> None:
    marker = uuid.uuid4().hex[:12]
    workspace = _workspace(db, marker)
    try:
        questionnaire = _questionnaire(db, workspace.id, marker)
        question = _question(db, questionnaire.id, "How often are access reviews run?")
        document = _document(db, workspace.id, marker, "policy")
        chunk = _chunk(db, workspace.id, document, "policy", source_version=document.storage_key)
        answer = _answer(
            db,
            question.id,
            APPROVED_TEXT,
            "draft",
            [{"chunk_id": chunk.id, "snippet": "synthetic evidence"}],
        )
        db.commit()
        db.refresh(answer)
        update_answer(
            answer.id,
            AnswerUpdate(
                status="approved",
                updated_at=answer_revision_token(answer.updated_at),
            ),
            session=_session(workspace.id),
            db=db,
        )
        db.refresh(answer)
        parsed = json.loads(answer.citations or "[]")
        assert parsed[0]["chunk_id"] == chunk.id
        assert parsed[0].get("document_id") == document.id
        assert parsed[0].get("support_stale") is not True
        assert answer.status == "approved"
        assert answer.text == APPROVED_TEXT
    finally:
        _cleanup(db, workspace.id)


def test_archive_keeps_the_approved_text_and_marks_it_stale(db: Session) -> None:
    marker = uuid.uuid4().hex[:12]
    workspace = _workspace(db, marker)
    try:
        questionnaire = _questionnaire(db, workspace.id, marker)
        question = _question(db, questionnaire.id, "How often are access reviews run?")
        document = _document(db, workspace.id, marker, "policy")
        chunk = _chunk(db, workspace.id, document, "policy", source_version=document.storage_key)
        answer = _answer(
            db,
            question.id,
            APPROVED_TEXT,
            "approved",
            [{"chunk_id": chunk.id, "document_id": document.id, "snippet": "synthetic evidence"}],
        )
        db.commit()
        service = RetrievalService(db)
        before = service.search(workspace.id, "designated policy", limit=10)
        assert chunk.id in {row.get("id") for row in before}
        delete_document(
            document.id,
            workspace_id=workspace.id,
            session=_session(workspace.id),
            db=db,
        )
        after = service.search(workspace.id, "designated policy", limit=10)
        assert chunk.id not in {row.get("id") for row in after}
        body = _read(db, questionnaire.id, workspace.id)
        shown = _answer_on(body, question.id)
        assert shown["text"] == APPROVED_TEXT
        assert shown["status"] == "approved"
        assert shown.get("support_stale") is True
        db.refresh(answer)
        assert answer.text == APPROVED_TEXT
        assert answer.status == "approved"
    finally:
        _cleanup(db, workspace.id)


def test_archive_hides_the_chunk_and_bumps_the_corpus(db: Session) -> None:
    marker = uuid.uuid4().hex[:12]
    workspace = _workspace(db, marker)
    try:
        document = _document(db, workspace.id, marker, "policy")
        chunk = _chunk(db, workspace.id, document, "policy", source_version=document.storage_key)
        db.commit()
        version = get_corpus_version(db, workspace.id)
        delete_document(
            document.id,
            workspace_id=workspace.id,
            session=_session(workspace.id),
            db=db,
        )
        assert get_corpus_version(db, workspace.id) != version
        found = RetrievalService(db).search(workspace.id, "designated policy", limit=10)
        assert chunk.id not in {row.get("id") for row in found}
        stored = db.get(Chunk, chunk.id)
        assert stored is not None
        assert (stored.metadata_ or {}).get("retrieval_tombstone") == "soft_deleted"
    finally:
        _cleanup(db, workspace.id)


def test_restored_source_keeps_the_revision_stale(db: Session) -> None:
    marker = uuid.uuid4().hex[:12]
    workspace = _workspace(db, marker)
    try:
        questionnaire = _questionnaire(db, workspace.id, marker)
        question = _question(db, questionnaire.id, "How often are access reviews run?")
        document = _document(db, workspace.id, marker, "policy")
        chunk = _chunk(db, workspace.id, document, "policy", source_version=document.storage_key)
        answer = _answer(
            db,
            question.id,
            APPROVED_TEXT,
            "approved",
            [{"chunk_id": chunk.id, "document_id": document.id, "snippet": "synthetic evidence"}],
        )
        db.commit()
        delete_document(
            document.id,
            workspace_id=workspace.id,
            session=_session(workspace.id),
            db=db,
        )
        restore_document(
            document.id,
            workspace_id=workspace.id,
            session=_session(workspace.id),
            db=db,
        )
        shown = _answer_on(_read(db, questionnaire.id, workspace.id), question.id)
        assert shown["text"] == APPROVED_TEXT
        assert shown["status"] == "approved"
        assert shown.get("support_stale") is True
        with pytest.raises(HTTPException) as caught:
            _export(db, questionnaire.id, workspace.id)
        assert caught.value.status_code == 409
        detail = caught.value.detail
        assert isinstance(detail, dict)
        assert answer.id in {item["answer_id"] for item in detail["answers"]}
    finally:
        _cleanup(db, workspace.id)


def test_export_blocked_until_new_revision_on_active_source(db: Session) -> None:
    marker = uuid.uuid4().hex[:12]
    workspace = _workspace(db, marker)
    try:
        questionnaire = _questionnaire(db, workspace.id, marker)
        approved_question = _question(db, questionnaire.id, "How often are access reviews run?")
        placeholder = _question(db, questionnaire.id, "Is there a spare question?")
        document = _document(db, workspace.id, marker, "old")
        chunk = _chunk(db, workspace.id, document, "old", source_version=document.storage_key)
        citation = [
            {"chunk_id": chunk.id, "document_id": document.id, "snippet": "synthetic evidence"}
        ]
        answer = _answer(db, approved_question.id, APPROVED_TEXT, "approved", citation)
        placeholder_answer = _answer(
            db, placeholder.id, INSUFFICIENT_TEXT, "insufficient_evidence", citation
        )
        db.commit()
        delete_document(
            document.id,
            workspace_id=workspace.id,
            session=_session(workspace.id),
            db=db,
        )
        with pytest.raises(HTTPException) as caught:
            _export(db, questionnaire.id, workspace.id)
        assert caught.value.status_code == 409
        detail = caught.value.detail
        assert isinstance(detail, dict)
        assert "active source" in detail["message"]
        listed = {item["answer_id"] for item in detail["answers"]}
        assert answer.id in listed
        assert placeholder_answer.id not in listed
        assert str(answer.id) in detail["message"]
        replacement = _document(db, workspace.id, marker, "current")
        replacement_chunk = _chunk(
            db,
            workspace.id,
            replacement,
            "current",
            source_version=replacement.storage_key,
        )
        db.commit()
        _approve_new_revision(db, answer, replacement, replacement_chunk)
        shown = _answer_on(_read(db, questionnaire.id, workspace.id), approved_question.id)
        assert shown["text"] == REVISED_TEXT
        assert shown["status"] == "approved"
        assert shown.get("support_stale") is False
        result = _export(db, questionnaire.id, workspace.id)
        assert result["status"] == "queued"
        assert isinstance(result["job_id"], int)
    finally:
        _cleanup(db, workspace.id)


def test_worker_refuses_export_of_a_stale_revision(db: Session) -> None:
    marker = uuid.uuid4().hex[:12]
    workspace = _workspace(db, marker)
    try:
        questionnaire = _questionnaire(db, workspace.id, marker)
        question = _question(db, questionnaire.id, "How often are access reviews run?")
        document = _document(db, workspace.id, marker, "policy")
        chunk = _chunk(db, workspace.id, document, "policy", source_version=document.storage_key)
        answer = _answer(
            db,
            question.id,
            APPROVED_TEXT,
            "approved",
            [{"chunk_id": chunk.id, "document_id": document.id, "snippet": "synthetic evidence"}],
        )
        job = Job(
            workspace_id=workspace.id,
            kind="export",
            status="running",
            payload=json.dumps(
                {
                    "questionnaire_id": questionnaire.id,
                    "workspace_id": workspace.id,
                    "format": "xlsx",
                }
            ),
        )
        db.add(job)
        db.commit()
        delete_document(
            document.id,
            workspace_id=workspace.id,
            session=_session(workspace.id),
            db=db,
        )
        with pytest.raises(TerminalJobError) as caught:
            run_export(
                job,
                db,
                {
                    "questionnaire_id": questionnaire.id,
                    "workspace_id": workspace.id,
                    "format": "xlsx",
                },
            )
        assert caught.value.code == "export_support_stale"
        assert str(answer.id) in caught.value.message
    finally:
        _cleanup(db, workspace.id)


def test_replaced_source_marks_the_revision_stale_and_blocks_export(db: Session) -> None:
    marker = uuid.uuid4().hex[:12]
    workspace = _workspace(db, marker)
    try:
        questionnaire = _questionnaire(db, workspace.id, marker)
        question = _question(db, questionnaire.id, "How often are access reviews run?")
        original_key = f"synthetic/{marker}/policy-v1.txt"
        document = _document(db, workspace.id, marker, "policy", storage_key=original_key)
        chunk = _chunk(db, workspace.id, document, "policy", source_version=original_key)
        answer = _answer(
            db,
            question.id,
            APPROVED_TEXT,
            "approved",
            [{"chunk_id": chunk.id, "document_id": document.id, "snippet": "synthetic evidence"}],
        )
        db.commit()
        document.storage_key = f"synthetic/{marker}/policy-v2.txt"
        db.commit()
        found = RetrievalService(db).search(workspace.id, "designated policy", limit=10)
        assert chunk.id not in {row.get("id") for row in found}
        shown = _answer_on(_read(db, questionnaire.id, workspace.id), question.id)
        assert shown["text"] == APPROVED_TEXT
        assert shown["status"] == "approved"
        assert shown.get("support_stale") is True
        with pytest.raises(HTTPException) as caught:
            _export(db, questionnaire.id, workspace.id)
        assert caught.value.status_code == 409
        detail = caught.value.detail
        assert answer.id in {item["answer_id"] for item in detail["answers"]}
    finally:
        _cleanup(db, workspace.id)


def _control(db: Session, workspace_id: int, marker: str) -> WorkspaceControl:
    row = WorkspaceControl(workspace_id=workspace_id, custom_name=f"tc08006-{marker}")
    db.add(row)
    db.flush()
    return row


def _accept(db: Session, workspace_id: int, control_id: int, chunk_id: int):
    return accept_suggested_evidence(
        control_id,
        AcceptSuggestedEvidenceBody(chunk_id=chunk_id, confidence=0.4),
        _request(),
        session=_session(workspace_id),
        db=db,
    )


def test_accept_suggested_rejects_a_soft_deleted_chunk(db: Session) -> None:
    marker = uuid.uuid4().hex[:12]
    workspace = _workspace(db, marker)
    try:
        document = _document(db, workspace.id, marker, "policy")
        chunk = _chunk(db, workspace.id, document, "policy", source_version=document.storage_key)
        control = _control(db, workspace.id, marker)
        db.commit()
        delete_document(
            document.id,
            workspace_id=workspace.id,
            session=_session(workspace.id),
            db=db,
        )
        before = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == workspace.id).count()
        with pytest.raises(HTTPException) as caught:
            _accept(db, workspace.id, control.id, chunk.id)
        assert caught.value.status_code == 409
        assert "not eligible" in caught.value.detail
        after = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == workspace.id).count()
        assert after == before
    finally:
        _cleanup(db, workspace.id)


def test_accept_suggested_rejects_a_chunk_that_is_not_eligible(db: Session) -> None:
    marker = uuid.uuid4().hex[:12]
    workspace = _workspace(db, marker)
    try:
        pending = _document(db, workspace.id, marker, "pending", status="uploaded")
        pending_chunk = _chunk(db, workspace.id, pending, "pending")
        replaced_key = f"synthetic/{marker}/replaced-v2.txt"
        replaced = _document(db, workspace.id, marker, "replaced", storage_key=replaced_key)
        replaced_chunk = _chunk(
            db,
            workspace.id,
            replaced,
            "replaced",
            source_version=f"synthetic/{marker}/replaced-v1.txt",
        )
        control = _control(db, workspace.id, marker)
        db.commit()
        before = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == workspace.id).count()
        for chunk_id in (pending_chunk.id, replaced_chunk.id):
            with pytest.raises(HTTPException) as caught:
                _accept(db, workspace.id, control.id, chunk_id)
            assert caught.value.status_code == 409
            assert "not eligible" in caught.value.detail
        after = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == workspace.id).count()
        assert after == before
    finally:
        _cleanup(db, workspace.id)


def test_accept_suggested_accepts_an_eligible_chunk(db: Session) -> None:
    marker = uuid.uuid4().hex[:12]
    workspace = _workspace(db, marker)
    try:
        document = _document(db, workspace.id, marker, "policy")
        chunk = _chunk(db, workspace.id, document, "policy", source_version=document.storage_key)
        control = _control(db, workspace.id, marker)
        db.commit()
        created = _accept(db, workspace.id, control.id, chunk.id)
        assert isinstance(created, dict)
        assert created["evidence"]["document_id"] == document.id
    finally:
        _cleanup(db, workspace.id)
