"""Record and list answer delivery outcomes (E6-31)."""

from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.answer_delivery_outcome import AnswerDeliveryOutcome, OUTCOME_CHANNELS
from app.models.questionnaire import Question, Questionnaire


def _answer_workspace(db: Session, answer_id: int) -> tuple[int, int] | None:
    """Return (workspace_id, questionnaire_id) for an answer, or None."""
    row = (
        db.query(Answer, Questionnaire.workspace_id, Questionnaire.id)
        .join(Question, Answer.question_id == Question.id)
        .join(Questionnaire, Question.questionnaire_id == Questionnaire.id)
        .filter(Answer.id == answer_id)
        .first()
    )
    if not row:
        return None
    _, ws_id, qnr_id = row
    return (ws_id, qnr_id)


def record_outcome(
    db: Session,
    workspace_id: int,
    answer_id: int,
    *,
    questionnaire_id: int | None = None,
    deal_id: int | None = None,
    golden_answer_id: int | None = None,
    accepted_without_edits: bool | None = None,
    was_edited: bool | None = None,
    edit_diff_json: str | None = None,
    follow_up_requested: bool | None = None,
    buyer_pushback: bool | None = None,
    deal_closed: bool | None = None,
    review_cycle_hours: float | None = None,
    channel: str = "manual",
    notes: str | None = None,
    created_by_user_id: int | None = None,
) -> dict | None:
    if channel not in OUTCOME_CHANNELS:
        return None
    scope = _answer_workspace(db, answer_id)
    if not scope:
        return None
    ws_from_answer, default_qnr = scope
    if ws_from_answer != workspace_id:
        return None
    qid = questionnaire_id if questionnaire_id is not None else default_qnr
    row = AnswerDeliveryOutcome(
        workspace_id=workspace_id,
        answer_id=answer_id,
        questionnaire_id=qid,
        deal_id=deal_id,
        golden_answer_id=golden_answer_id,
        accepted_without_edits=accepted_without_edits,
        was_edited=was_edited,
        edit_diff_json=edit_diff_json,
        follow_up_requested=follow_up_requested,
        buyer_pushback=buyer_pushback,
        deal_closed=deal_closed,
        review_cycle_hours=review_cycle_hours,
        channel=channel,
        notes=notes,
        created_by_user_id=created_by_user_id,
    )
    db.add(row)
    db.flush()
    return _serialize(row)


def list_for_answer(db: Session, workspace_id: int, answer_id: int) -> list[dict]:
    rows = (
        db.query(AnswerDeliveryOutcome)
        .filter(
            AnswerDeliveryOutcome.workspace_id == workspace_id,
            AnswerDeliveryOutcome.answer_id == answer_id,
        )
        .order_by(AnswerDeliveryOutcome.created_at.desc())
        .all()
    )
    return [_serialize(r) for r in rows]


def list_for_workspace(db: Session, workspace_id: int, limit: int = 100) -> list[dict]:
    rows = (
        db.query(AnswerDeliveryOutcome)
        .filter(AnswerDeliveryOutcome.workspace_id == workspace_id)
        .order_by(AnswerDeliveryOutcome.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_serialize(r) for r in rows]


def _serialize(r: AnswerDeliveryOutcome) -> dict:
    return {
        "id": r.id,
        "workspace_id": r.workspace_id,
        "answer_id": r.answer_id,
        "questionnaire_id": r.questionnaire_id,
        "deal_id": r.deal_id,
        "golden_answer_id": r.golden_answer_id,
        "accepted_without_edits": r.accepted_without_edits,
        "was_edited": r.was_edited,
        "edit_diff_json": r.edit_diff_json,
        "follow_up_requested": r.follow_up_requested,
        "buyer_pushback": r.buyer_pushback,
        "deal_closed": r.deal_closed,
        "review_cycle_hours": r.review_cycle_hours,
        "channel": r.channel,
        "notes": r.notes,
        "created_by_user_id": r.created_by_user_id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
