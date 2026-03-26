"""Answer delivery outcome records (E6-31)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.auth_deps import require_can_edit, require_session
from app.core.database import get_db
from app.services import answer_outcome_service as aos
from sqlalchemy.orm import Session

router = APIRouter(prefix="/answer-outcomes", tags=["answer-outcomes"])


class RecordOutcomeBody(BaseModel):
    answer_id: int
    questionnaire_id: int | None = None
    deal_id: int | None = None
    golden_answer_id: int | None = None
    accepted_without_edits: bool | None = None
    was_edited: bool | None = None
    edit_diff_json: str | None = None
    follow_up_requested: bool | None = None
    buyer_pushback: bool | None = None
    deal_closed: bool | None = None
    review_cycle_hours: float | None = None
    channel: str = Field(default="manual", max_length=32)
    notes: str | None = None


@router.post("")
def record_outcome(
    body: RecordOutcomeBody,
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    out = aos.record_outcome(
        db,
        session["workspace_id"],
        body.answer_id,
        questionnaire_id=body.questionnaire_id,
        deal_id=body.deal_id,
        golden_answer_id=body.golden_answer_id,
        accepted_without_edits=body.accepted_without_edits,
        was_edited=body.was_edited,
        edit_diff_json=body.edit_diff_json,
        follow_up_requested=body.follow_up_requested,
        buyer_pushback=body.buyer_pushback,
        deal_closed=body.deal_closed,
        review_cycle_hours=body.review_cycle_hours,
        channel=body.channel,
        notes=body.notes,
        created_by_user_id=session.get("user_id"),
    )
    if not out:
        raise HTTPException(
            status_code=400,
            detail="Invalid channel, unknown answer, or answer not in this workspace",
        )
    db.commit()
    return out


@router.get("/answer/{answer_id}")
def list_for_answer(
    answer_id: int,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return {"outcomes": aos.list_for_answer(db, session["workspace_id"], answer_id)}


@router.get("/recent")
def list_recent(
    limit: int = Query(100, ge=1, le=500),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return {"outcomes": aos.list_for_workspace(db, session["workspace_id"], limit=limit)}
