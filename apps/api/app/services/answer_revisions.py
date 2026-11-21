"""Explicit regenerate of an approved answer (TC-12-004a).

Bulk generation still skips an approved row. This path is the explicit one:
it inserts a draft revision and does not update the approved answer. Export
and questionnaire reads keep using that answer until the draft is approved.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.answer_revision import (
    REVISION_APPLIED,
    REVISION_DRAFT,
    REVISION_SUPERSEDED,
    AnswerRevision,
)
from app.services.answer_generation import _lock_answer_write
from app.services.model_outcomes import ModelCallError, ModelFailure, ModelOutcomeCode


class RevisionRejected(Exception):
    """The regenerate or reapproval cannot proceed. The approved row is unchanged."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _citations_json(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _raw_answer(db: Session, answer_id: int) -> dict[str, Any]:
    row = (
        db.execute(
            sql_text("SELECT * FROM answers WHERE id = :id"),
            {"id": answer_id},
        )
        .mappings()
        .one()
    )
    return {key: row[key] for key in row.keys()}


def _next_number(db: Session, answer_id: int) -> int:
    current = db.execute(
        sql_text(
            "SELECT COALESCE(MAX(revision_number), 0) FROM answer_revisions WHERE answer_id = :id"
        ),
        {"id": answer_id},
    ).scalar()
    return int(current or 0) + 1


def _close_open_drafts(db: Session, answer_id: int) -> None:
    now = datetime.utcnow()
    db.query(AnswerRevision).filter(
        AnswerRevision.answer_id == answer_id,
        AnswerRevision.status == REVISION_DRAFT,
    ).update(
        {"status": REVISION_SUPERSEDED, "updated_at": now},
        synchronize_session=False,
    )


def revision_payload(row: AnswerRevision | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "revision_number": row.revision_number,
        "text": row.text,
        "citations": row.citations,
        "status": row.status,
        "confidence": row.confidence,
        "outcome_code": row.outcome_code,
    }


def open_drafts_by_answer(db: Session, answer_ids: list[int]) -> dict[int, AnswerRevision]:
    """Latest open draft for each answer. Empty when nothing is waiting for reapproval."""
    if not answer_ids:
        return {}
    rows = (
        db.query(AnswerRevision)
        .filter(
            AnswerRevision.answer_id.in_(answer_ids),
            AnswerRevision.status == REVISION_DRAFT,
        )
        .order_by(AnswerRevision.revision_number.asc())
        .all()
    )
    found: dict[int, AnswerRevision] = {}
    for row in rows:
        found[row.answer_id] = row
    return found


def approved_export_source(answer: Answer | None) -> tuple[str | None, str | None]:
    """Export uses the answer row. An open draft revision is not the exported text."""
    if answer is None:
        return None, None
    return answer.text, answer.status


def answers_for_export(
    questions: list[Any], answers_by_question: dict[int, Answer]
) -> dict[int, str]:
    """Customer export cells. The source is the approved answer row, not a draft revision."""
    from app.services.answer_evidence_policy import answer_text_for_export

    exported: dict[int, str] = {}
    for question in questions:
        answer = answers_by_question.get(question.id)
        text, status = approved_export_source(answer)
        exported[question.id] = answer_text_for_export(text=text, status=status)
    return exported


def generate_explicit_draft(
    db: Session, question: Any, workspace_id: int, questionnaire: Any
) -> dict:
    """One retrieval and one completion. This does not write an answer row."""
    from openai import OpenAI

    from app.core.config import get_settings
    from app.models.workspace import Workspace
    from app.services.answer_generation import (
        ANSWER_SYSTEM_PROMPT,
        DEFAULT_RESPONSE_STYLE,
        EVIDENCE_LIMIT_PER_GROUP,
        _generate_single_question_answer,
        resolve_model,
        resolve_temperature_from_style,
    )
    from app.services.embedding_service import embed_texts
    from app.services.question_normalizer import evidence_fingerprint_hash
    from app.services.questionnaire_answer_evidence import parse_answer_evidence_document_ids
    from app.services.retrieval import RetrievalService

    settings = get_settings()
    if not (settings.openai_api_key or "").strip():
        raise ModelCallError(ModelFailure(code=ModelOutcomeCode.MODEL_CREDENTIALS_MISSING))
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    model_name = resolve_model(
        (workspace.ai_completion_model if workspace and workspace.ai_completion_model else None)
        or settings.completion_model
    )
    if workspace is not None and workspace.ai_temperature is not None:
        temperature = max(0.0, min(1.5, float(workspace.ai_temperature)))
    else:
        temperature = resolve_temperature_from_style(DEFAULT_RESPONSE_STYLE)
    evidence_scope = parse_answer_evidence_document_ids(questionnaire)
    doc_ids = sorted(evidence_scope) if evidence_scope else None
    embeddings = embed_texts([question.text or ""])
    embedding = embeddings[0] if embeddings else None
    found = RetrievalService(db).batch_search(
        workspace_id,
        [(question.text or "", embedding)],
        limit=EVIDENCE_LIMIT_PER_GROUP,
        document_ids=doc_ids,
    )
    evidence = found[0] if found else []
    chunk_ids = [item["id"] for item in evidence if item.get("id") is not None]
    fingerprint = evidence_fingerprint_hash(chunk_ids) if chunk_ids else None
    client = OpenAI(api_key=settings.openai_api_key, timeout=30.0)
    generated = _generate_single_question_answer(
        question,
        evidence,
        workspace_id,
        questionnaire.id,
        model_name,
        temperature,
        ANSWER_SYSTEM_PROMPT,
        client,
    )
    return {
        "text": generated.text,
        "citations": generated.citations,
        "confidence": generated.confidence,
        "outcome_code": generated.outcome.value,
        "insufficient_reason": None,
        "gating_reason": None,
        "primary_categories_json": None,
        "evidence_fingerprint": fingerprint,
    }


def insert_draft_revision(db: Session, answer: Answer, produced: dict) -> AnswerRevision:
    """Insert a draft. The approved answer row is read back and must be unchanged."""
    _lock_answer_write(db, answer.question_id)
    current = db.query(Answer).filter(Answer.id == answer.id).populate_existing().one()
    if current.status != "approved":
        raise RevisionRejected(
            409,
            "Only an approved answer can be regenerated into a new draft.",
        )
    before = _raw_answer(db, current.id)
    _close_open_drafts(db, current.id)
    row = AnswerRevision(
        answer_id=current.id,
        question_id=current.question_id,
        revision_number=_next_number(db, current.id),
        text=produced.get("text"),
        citations=_citations_json(produced.get("citations")),
        confidence=produced.get("confidence"),
        insufficient_reason=produced.get("insufficient_reason"),
        gating_reason=produced.get("gating_reason"),
        primary_categories_json=produced.get("primary_categories_json"),
        evidence_fingerprint=produced.get("evidence_fingerprint"),
        outcome_code=produced.get("outcome_code"),
        status=REVISION_DRAFT,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    after = _raw_answer(db, current.id)
    if before != after:
        raise RevisionRejected(500, "The approved answer was changed during regenerate.")
    return row


def approve_draft_revision(
    db: Session, answer: Answer, revision_id: int
) -> tuple[Answer, str | None]:
    """Copy the draft onto the answer and keep the previous approved text as superseded."""
    _lock_answer_write(db, answer.question_id)
    current = db.query(Answer).filter(Answer.id == answer.id).populate_existing().one()
    revision = (
        db.query(AnswerRevision)
        .filter(
            AnswerRevision.id == revision_id,
            AnswerRevision.answer_id == current.id,
        )
        .populate_existing()
        .one_or_none()
    )
    if revision is None:
        raise RevisionRejected(404, "Draft revision not found")
    if revision.status != REVISION_DRAFT:
        raise RevisionRejected(409, "That revision is not an open draft.")
    if current.status != "approved":
        raise RevisionRejected(409, "The saved answer is no longer approved.")
    previous = current.text
    snapshot = AnswerRevision(
        answer_id=current.id,
        question_id=current.question_id,
        revision_number=_next_number(db, current.id),
        text=current.text,
        citations=current.citations,
        confidence=current.confidence,
        insufficient_reason=current.insufficient_reason,
        gating_reason=current.gating_reason,
        primary_categories_json=current.primary_categories_json,
        evidence_fingerprint=current.evidence_fingerprint,
        outcome_code=current.outcome_code,
        status=REVISION_SUPERSEDED,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(snapshot)
    current.text = revision.text
    current.citations = revision.citations
    current.confidence = revision.confidence
    current.insufficient_reason = revision.insufficient_reason
    current.gating_reason = revision.gating_reason
    current.primary_categories_json = revision.primary_categories_json
    current.evidence_fingerprint = revision.evidence_fingerprint
    current.outcome_code = revision.outcome_code
    current.status = "approved"
    from app.services.answer_support import bind_approved_support

    bound = bind_approved_support(db, current, clear_stale=True)
    if bound is not None:
        current.citations = bound
    revision.status = REVISION_APPLIED
    revision.updated_at = datetime.utcnow()
    db.flush()
    return current, previous
