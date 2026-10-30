"""Answers API (AI-05, REV-04).

CRUD for answer rows (create/update/bulk status). **Bulk AI generation is not here** — the app
enqueues ``generate_answers`` via ``POST /api/exports/generate/{questionnaire_id}`` (see
``export_service.enqueue_generate_answers_job`` and ``docs/engineering/ANSWER_GENERATION_PIPELINE.md``).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StrictInt
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_review
from app.core.database import get_db
from app.models import Answer, Question, Questionnaire

router = APIRouter(prefix="/answers", tags=["answers"])


class AnswerCreate(BaseModel):
    question_id: int
    text: str = ""
    status: str = "draft"


class AnswerUpdate(BaseModel):
    text: str | None = None
    status: str | None = None


class BulkUpdateBody(BaseModel):
    question_ids: list[StrictInt]
    status: str


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
    if not qnr or qnr.workspace_id != session.get("workspace_id"):
        raise HTTPException(status_code=403, detail="Access denied")
    existing = db.query(Answer).filter(Answer.question_id == body.question_id).first()
    if existing:
        if body.text and body.text != existing.text:
            existing.outcome_code = None  # TC-11-001: human-authored text has no model outcome
        existing.text = body.text or existing.text
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
    """Update answer text and/or status."""
    a = db.query(Answer).filter(Answer.id == answer_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Answer not found")
    q = db.query(Question).filter(Question.id == a.question_id).first()
    if q:
        qnr = db.query(Questionnaire).filter(Questionnaire.id == q.questionnaire_id).first()
        if qnr and qnr.workspace_id != session.get("workspace_id"):
            raise HTTPException(status_code=403, detail="Access denied")
    if body.text is not None:
        if body.text != a.text:
            a.outcome_code = None  # TC-11-001: human-authored text has no model outcome
        a.text = body.text
    if body.status is not None:
        a.status = body.status
    db.commit()
    db.refresh(a)
    return {"id": a.id, "question_id": a.question_id, "text": a.text, "status": a.status}
