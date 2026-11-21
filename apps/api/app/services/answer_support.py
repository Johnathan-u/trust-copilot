"""Bind an approved answer to the documents that support it.

Citations already carry ``document_id`` and ``chunk_id``. Approval fills a
missing document id from the chunk. Archive, soft-delete, and a replaced
source set ``support_stale`` on those citation objects. The answer text and
``approved`` status stay. A later approval of a draft clears that marker only
when the new citations name a document that is still eligible.

The marker lives on the existing citations text. No new column.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Answer, Chunk, Document, Question, Questionnaire
from app.services.active_sources import SOURCE_VERSION_KEY, citations_are_stale
from app.services.answer_evidence_policy import (
    EXPORT_NOT_READY_PLACEHOLDER,
    answer_text_for_export,
)

EXPORT_BLOCKED_MESSAGE = "Export blocked until a new revision is approved against an active source."


class ExportBlocked(Exception):
    """Final export cannot include an answer whose support is revoked or stale."""

    def __init__(self, answers: list[dict[str, int]]):
        self.answers = answers
        super().__init__(EXPORT_BLOCKED_MESSAGE)


def export_block_detail(answers: list[dict[str, int]]) -> dict[str, object]:
    """409 body. Lists answer ids and does not include answer text."""
    listed = ", ".join(str(item["answer_id"]) for item in answers)
    return {
        "message": f"{EXPORT_BLOCKED_MESSAGE} Answers: {listed}.",
        "answers": answers,
    }


def _positive_int(value: object) -> int | None:
    if type(value) is int and value > 0:
        return value
    return None


def _parse(raw: str | None) -> list:
    if not raw:
        return []
    try:
        loaded = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(loaded, list):
        return []
    return loaded


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _workspace_id(db: Session, answer: Answer) -> int | None:
    row = (
        db.query(Questionnaire.workspace_id)
        .join(Question, Question.questionnaire_id == Questionnaire.id)
        .filter(Question.id == answer.question_id)
        .first()
    )
    if row is None:
        return None
    return int(row[0])


def _flagged(citations: list) -> bool:
    return any(isinstance(item, dict) and item.get("support_stale") is True for item in citations)


def support_is_stale(db: Session, workspace_id: int, citations_json: str | None) -> bool:
    """True when this revision was marked stale or still cites an ineligible source."""
    citations = _parse(citations_json)
    if _flagged(citations):
        return True
    if not citations:
        return False
    return citations_are_stale(db, workspace_id, citations)


def _chunks_by_id(db: Session, workspace_id: int, citations: list) -> dict[int, Chunk]:
    ids = [
        chunk_id
        for item in citations
        if isinstance(item, dict)
        for chunk_id in [_positive_int(item.get("chunk_id"))]
        if chunk_id is not None
    ]
    if not ids:
        return {}
    rows = db.query(Chunk).filter(Chunk.workspace_id == workspace_id, Chunk.id.in_(ids)).all()
    return {row.id: row for row in rows}


def bind_approved_support(db: Session, answer: Answer, *, clear_stale: bool) -> str | None:
    """Return rewritten citations when the binding changes, else None.

    ``clear_stale`` is for a newly approved draft. Re-selecting approved on the
    same revision does not drop a marker that archive already wrote.
    """
    workspace_id = _workspace_id(db, answer)
    if workspace_id is None:
        return None
    citations = _parse(answer.citations)
    if not citations:
        return None
    chunks = _chunks_by_id(db, workspace_id, citations)
    changed = False
    for item in citations:
        if not isinstance(item, dict):
            continue
        if _positive_int(item.get("document_id")) is None:
            chunk_id = _positive_int(item.get("chunk_id"))
            chunk = chunks.get(chunk_id) if chunk_id is not None else None
            if chunk is not None and chunk.document_id is not None:
                item["document_id"] = chunk.document_id
                changed = True
        revoked = citations_are_stale(db, workspace_id, [item])
        if revoked:
            if item.get("support_stale") is not True:
                item["support_stale"] = True
                changed = True
        elif clear_stale and "support_stale" in item:
            item.pop("support_stale", None)
            changed = True
    if not changed:
        return None
    return json.dumps(citations)


def _workspace_answers(db: Session, workspace_id: int) -> list[Answer]:
    return (
        db.query(Answer)
        .join(Question, Question.id == Answer.question_id)
        .join(Questionnaire, Questionnaire.id == Question.questionnaire_id)
        .filter(Questionnaire.workspace_id == workspace_id)
        .all()
    )


def mark_answers_stale_for_document(db: Session, workspace_id: int, document_id: int) -> int:
    """Mark answers in this workspace that cite the document. Text and status stay."""
    chunk_ids = {
        row.id for row in db.query(Chunk.id).filter(Chunk.document_id == document_id).all()
    }
    changed_rows = 0
    now = _now()
    for answer in _workspace_answers(db, workspace_id):
        citations = _parse(answer.citations)
        if not citations:
            continue
        touched = False
        for item in citations:
            if not isinstance(item, dict):
                continue
            doc_id = _positive_int(item.get("document_id"))
            chunk_id = _positive_int(item.get("chunk_id"))
            cites = doc_id == document_id or (chunk_id is not None and chunk_id in chunk_ids)
            if not cites:
                continue
            if doc_id is None:
                item["document_id"] = document_id
                touched = True
            if item.get("support_stale") is not True:
                item["support_stale"] = True
                touched = True
        if touched:
            answer.citations = json.dumps(citations)
            answer.updated_at = now
            changed_rows += 1
    return changed_rows


def note_reindex_replacement(db: Session, document: Document) -> None:
    """Mark citing answers when indexed chunks came from an older storage key.

    Call before those chunks are deleted. A reindex of the same key is not a
    replacement and does not mark answers.
    """
    rows = db.query(Chunk).filter(Chunk.document_id == document.id).all()
    current = document.storage_key or ""
    for row in rows:
        meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        version = meta.get(SOURCE_VERSION_KEY)
        if isinstance(version, str) and version and version != current:
            mark_answers_stale_for_document(db, document.workspace_id, document.id)
            return


def _included(answer: Answer) -> bool:
    rendered = answer_text_for_export(
        text=answer.text,
        status=answer.status,
        citations_json=answer.citations,
    )
    return bool(rendered) and rendered != EXPORT_NOT_READY_PLACEHOLDER


def _stamp_live(db: Session, workspace_id: int, answer: Answer) -> None:
    citations = _parse(answer.citations)
    changed = False
    for item in citations:
        if not isinstance(item, dict) or item.get("support_stale") is True:
            continue
        if citations_are_stale(db, workspace_id, [item]):
            item["support_stale"] = True
            changed = True
    if changed:
        answer.citations = json.dumps(citations)
        answer.updated_at = _now()


def blocking_answers(db: Session, workspace_id: int, questionnaire_id: int) -> list[dict[str, int]]:
    """Included answers whose support is revoked or whose revision is still stale.

    An insufficient-evidence placeholder is not included. The marker is written
    when the source is revoked now, so a later restore does not clear it.
    """
    questions = db.query(Question.id).filter(Question.questionnaire_id == questionnaire_id).all()
    if not questions:
        return []
    question_ids = [row[0] for row in questions]
    answers = db.query(Answer).filter(Answer.question_id.in_(question_ids)).all()
    blocked: list[dict[str, int]] = []
    for answer in answers:
        if not _included(answer):
            continue
        if not support_is_stale(db, workspace_id, answer.citations):
            continue
        _stamp_live(db, workspace_id, answer)
        blocked.append({"answer_id": answer.id, "question_id": answer.question_id})
    blocked.sort(key=lambda item: item["answer_id"])
    return blocked
