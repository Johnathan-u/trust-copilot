"""Answers API (AI-05, REV-04).

CRUD for answer rows (create/update/bulk status). **Bulk AI generation is not here** — the app
enqueues ``generate_answers`` via ``POST /api/exports/generate/{questionnaire_id}`` (see
``export_service.enqueue_generate_answers_job`` and ``docs/engineering/ANSWER_GENERATION_PIPELINE.md``).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StrictInt
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_review
from app.core.database import get_db
from app.core.workspace_refs import require_in_workspace
from app.models import Answer, Question, Questionnaire
from app.services.answer_generation import _lock_answer_write
from app.services.answer_revisions import (
    RevisionRejected,
    approve_draft_revision,
    generate_explicit_draft,
    insert_draft_revision,
    revision_payload,
)
from app.services.model_outcomes import ModelCallError

router = APIRouter(prefix="/answers", tags=["answers"])


class AnswerCreate(BaseModel):
    question_id: int
    text: str = ""
    status: str = "draft"


class AnswerUpdate(BaseModel):
    text: str | None = None
    status: str | None = None
    # The updated_at the editor loaded. It is the row revision, not a new value.
    updated_at: str | None = None


# Missing and mismatch both use this. The stored row is left unchanged.
_STALE_ANSWER = "This answer changed since it was loaded. Reload it and try again."


class BulkUpdateBody(BaseModel):
    question_ids: list[StrictInt]
    status: str


def _record_human_text(row: Answer, new_text: str) -> None:
    """Store text a person typed. That replacement is not a model placeholder."""
    if new_text != row.text:
        row.outcome_code = None
        row.insufficient_reason = None
    row.text = new_text


def answer_revision_token(value: datetime | None) -> str | None:
    """ISO form of ``answers.updated_at``. That existing column is the revision."""
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat()


def _reject_stale_answer(db: Session) -> None:
    db.rollback()
    raise HTTPException(status_code=409, detail=_STALE_ANSWER)


def _expected_answer_revision(db: Session, answer: Answer, body: AnswerUpdate) -> datetime | None:
    """409 unless the caller still holds the row's updated_at.

    The check runs after authorization and before any column is written.
    Omitting the value, sending it blank, or sending a different value are all 409.
    """
    if "updated_at" not in body.model_fields_set:
        _reject_stale_answer(db)
    if body.updated_at is None:
        if answer.updated_at is not None:
            _reject_stale_answer(db)
        return None
    if body.updated_at.strip() != answer_revision_token(answer.updated_at):
        _reject_stale_answer(db)
    return answer.updated_at


def _write_answer_if_current(
    db: Session, answer: Answer, body: AnswerUpdate, expected: datetime | None
) -> None:
    """Update the row only while ``updated_at`` is still the loaded revision."""
    values: dict[str, object] = {"updated_at": datetime.now(timezone.utc).replace(tzinfo=None)}
    if body.text is not None:
        values["text"] = body.text
        if body.text != answer.text:
            values["outcome_code"] = None
            values["insufficient_reason"] = None
    if body.status is not None:
        values["status"] = body.status
    stmt = update(Answer).where(Answer.id == answer.id)
    if expected is None:
        stmt = stmt.where(Answer.updated_at.is_(None))
    else:
        stmt = stmt.where(Answer.updated_at == expected)
    result = db.execute(stmt.values(**values))
    if result.rowcount != 1:
        _reject_stale_answer(db)


@router.post("")
@router.post("/")
def create_answer(
    body: AnswerCreate,
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Create or upsert answer for a question."""
    q = db.query(Question).filter(Question.id == body.question_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    qnr = db.query(Questionnaire).filter(Questionnaire.id == q.questionnaire_id).first()
    if qnr and qnr.workspace_id != session.get("workspace_id"):
        raise HTTPException(status_code=403, detail="Access denied")
    require_in_workspace(db, session.get("workspace_id"), "question", body.question_id)
    _lock_answer_write(db, body.question_id)
    existing = db.query(Answer).filter(Answer.question_id == body.question_id).first()
    if existing:
        if body.text:
            _record_human_text(existing, body.text)
        existing.status = body.status or existing.status
        db.commit()
        db.refresh(existing)
        return {
            "id": existing.id,
            "question_id": existing.question_id,
            "text": existing.text,
            "status": existing.status,
        }
    a = Answer(question_id=body.question_id, text=body.text, status=body.status)
    db.add(a)
    db.commit()
    db.refresh(a)
    return {"id": a.id, "question_id": a.question_id, "text": a.text, "status": a.status}


@router.patch("/bulk")
def bulk_update_status(
    body: BulkUpdateBody,
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Bulk update answer status. Creates answers if missing."""
    if (
        not body.question_ids
        or len(set(body.question_ids)) != len(body.question_ids)
        or any(qid <= 0 or qid > 2147483647 for qid in body.question_ids)
        or body.status
        not in (
            "draft",
            "approved",
            "rejected",
            "flagged",
            "pending",
            "insufficient_evidence",
        )
    ):
        raise HTTPException(status_code=400, detail="Invalid request")
    # Resolve the entire set through current, available workspace parents before
    # adding or changing any answer. Unknown and unauthorized IDs are identical.
    questions = (
        db.query(Question)
        .join(Questionnaire, Questionnaire.id == Question.questionnaire_id)
        .filter(
            Question.id.in_(body.question_ids),
            Questionnaire.workspace_id == session.get("workspace_id"),
            Questionnaire.deleted_at.is_(None),
        )
        .all()
    )
    if len(questions) != len(body.question_ids):
        raise HTTPException(status_code=404, detail="Question not found")
    # Sorted ids: two overlapping bulk writes cannot lock each other in opposite orders.
    for qid in sorted(body.question_ids):
        _lock_answer_write(db, qid)
    answers = db.query(Answer).filter(Answer.question_id.in_(body.question_ids)).all()
    existing_qids = {a.question_id for a in answers}
    for qid in body.question_ids:
        if qid not in existing_qids:
            a = Answer(question_id=qid, text="", status=body.status)
            db.add(a)
            existing_qids.add(qid)
        else:
            a = next(x for x in answers if x.question_id == qid)
            a.status = body.status
    db.commit()
    return {"updated": len(body.question_ids), "status": body.status}


@router.patch("/{answer_id}")
def update_answer(
    answer_id: int,
    body: AnswerUpdate,
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Update answer text and/or status.

    ``updated_at`` must be the value the editor loaded. A missing value or a
    mismatch is 409 and the stored row is left unchanged.
    """
    a = db.query(Answer).filter(Answer.id == answer_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Answer not found")
    q = db.query(Question).filter(Question.id == a.question_id).first()
    if q:
        qnr = db.query(Questionnaire).filter(Questionnaire.id == q.questionnaire_id).first()
        if qnr and qnr.workspace_id != session.get("workspace_id"):
            raise HTTPException(status_code=403, detail="Access denied")
    require_in_workspace(db, session.get("workspace_id"), "answer", answer_id)
    # The advisory lock serializes writers. It does not detect a stale editor.
    _lock_answer_write(db, a.question_id)
    db.refresh(a)
    expected = _expected_answer_revision(db, a, body)
    _write_answer_if_current(db, a, body, expected)
    db.commit()
    db.refresh(a)
    return {"id": a.id, "question_id": a.question_id, "text": a.text, "status": a.status}


def _approved_answer_for_regenerate(
    db: Session, session: dict, answer_id: int
) -> tuple[Answer, Question, Questionnaire]:
    """Load an answer the caller can review. Another workspace is access denied."""
    answer = db.query(Answer).filter(Answer.id == answer_id).first()
    if not answer:
        raise HTTPException(status_code=404, detail="Answer not found")
    question = db.query(Question).filter(Question.id == answer.question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    questionnaire = (
        db.query(Questionnaire).filter(Questionnaire.id == question.questionnaire_id).first()
    )
    if questionnaire is None or questionnaire.workspace_id != session.get("workspace_id"):
        raise HTTPException(status_code=403, detail="Access denied")
    require_in_workspace(db, session.get("workspace_id"), "answer", answer_id)
    return answer, question, questionnaire


def _answer_body(answer: Answer, draft: dict | None) -> dict:
    return {
        "id": answer.id,
        "question_id": answer.question_id,
        "text": answer.text,
        "status": answer.status,
        "citations": answer.citations,
        "draft_revision": draft,
    }


@router.post("/{answer_id}/regenerate")
def regenerate_answer(
    answer_id: int,
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Insert a draft revision. The approved answer row is not updated."""
    answer, question, questionnaire = _approved_answer_for_regenerate(db, session, answer_id)
    if answer.status != "approved":
        raise HTTPException(
            status_code=409,
            detail="Only an approved answer can be regenerated into a new draft.",
        )
    try:
        produced = generate_explicit_draft(db, question, questionnaire.workspace_id, questionnaire)
        revision = insert_draft_revision(db, answer, produced)
        db.commit()
    except ModelCallError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except RevisionRejected as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    db.refresh(answer)
    return _answer_body(answer, revision_payload(revision))


@router.post("/{answer_id}/revisions/{revision_id}/approve")
def approve_answer_revision(
    answer_id: int,
    revision_id: int,
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Make the draft the approved answer and keep the previous text as superseded."""
    answer, _question, _questionnaire = _approved_answer_for_regenerate(db, session, answer_id)
    try:
        current, _previous = approve_draft_revision(db, answer, revision_id)
        db.commit()
    except RevisionRejected as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    db.refresh(current)
    return _answer_body(current, None)
