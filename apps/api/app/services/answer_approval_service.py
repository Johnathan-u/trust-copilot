"""Answer approval workflow service (P1-72).

Multi-step governance: draft -> pending_review -> approved/rejected/changes_requested.
Owner and reviewer assignment, SLA tracking, bulk operations.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.answer_approval_event import AnswerApprovalEvent
from app.models.golden_answer import GoldenAnswer
from app.models.user import WorkspaceMember

logger = logging.getLogger(__name__)

VALID_STATUSES = ("draft", "pending_review", "approved", "rejected", "changes_requested", "expired")


def _get_answer(db: Session, ga_id: int, workspace_id: int) -> GoldenAnswer | None:
    return (
        db.query(GoldenAnswer)
        .filter(GoldenAnswer.id == ga_id, GoldenAnswer.workspace_id == workspace_id)
        .first()
    )


def _active_assignee(db: Session, user_id: int, workspace_id: int) -> bool:
    return (
        db.query(WorkspaceMember.id)
        .filter(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.suspended.is_(False),
        )
        .first()
        is not None
    )


def assign_owner(
    db: Session,
    ga_id: int,
    owner_user_id: int,
    actor_user_id: int | None = None,
    *,
    workspace_id: int,
) -> dict | None:
    ga = _get_answer(db, ga_id, workspace_id)
    if not ga or not _active_assignee(db, owner_user_id, workspace_id):
        return None
    ga.owner_user_id = owner_user_id
    _log_event(db, ga_id, "owner_assigned", actor_user_id)
    db.flush()
    return _serialize(ga)


def assign_reviewer(
    db: Session,
    ga_id: int,
    reviewer_user_id: int,
    actor_user_id: int | None = None,
    *,
    workspace_id: int,
) -> dict | None:
    ga = _get_answer(db, ga_id, workspace_id)
    if not ga or not _active_assignee(db, reviewer_user_id, workspace_id):
        return None
    ga.reviewer_user_id = reviewer_user_id
    _log_event(db, ga_id, "reviewer_assigned", actor_user_id)
    db.flush()
    return _serialize(ga)


def submit_for_review(
    db: Session, ga_id: int, actor_user_id: int | None = None, *, workspace_id: int
) -> dict | None:
    ga = _get_answer(db, ga_id, workspace_id)
    if not ga:
        return None
    if ga.status not in ("draft", "changes_requested"):
        return {
            "error": f"Cannot submit from status '{ga.status}'; must be draft or changes_requested"
        }
    ga.status = "pending_review"
    ga.submitted_at = datetime.now(timezone.utc)
    _log_event(db, ga_id, "submitted", actor_user_id)
    db.flush()
    return _serialize(ga)


def approve_answer(
    db: Session, ga_id: int, reviewer_id: int, comment: str | None = None, *, workspace_id: int
) -> dict | None:
    ga = _get_answer(db, ga_id, workspace_id)
    if not ga:
        return None
    if ga.status != "pending_review":
        return {"error": f"Cannot approve from status '{ga.status}'; must be pending_review"}
    ga.status = "approved"
    ga.last_reviewed_at = datetime.now(timezone.utc)
    cycle = ga.review_cycle_days or 90
    ga.expires_at = datetime.now(timezone.utc) + timedelta(days=cycle)
    _log_event(db, ga_id, "approved", reviewer_id, comment)
    db.flush()
    return _serialize(ga)


def reject_answer(
    db: Session, ga_id: int, reviewer_id: int, reason: str | None = None, *, workspace_id: int
) -> dict | None:
    ga = _get_answer(db, ga_id, workspace_id)
    if not ga:
        return None
    if ga.status != "pending_review":
        return {"error": f"Cannot reject from status '{ga.status}'; must be pending_review"}
    ga.status = "rejected"
    _log_event(db, ga_id, "rejected", reviewer_id, reason)
    db.flush()
    return _serialize(ga)


def request_changes(
    db: Session, ga_id: int, reviewer_id: int, comments: str | None = None, *, workspace_id: int
) -> dict | None:
    ga = _get_answer(db, ga_id, workspace_id)
    if not ga:
        return None
    if ga.status != "pending_review":
        return {
            "error": f"Cannot request changes from status '{ga.status}'; must be pending_review"
        }
    ga.status = "changes_requested"
    _log_event(db, ga_id, "changes_requested", reviewer_id, comments)
    db.flush()
    return _serialize(ga)


def get_review_queue(db: Session, workspace_id: int) -> list[dict]:
    answers = (
        db.query(GoldenAnswer)
        .filter(
            GoldenAnswer.workspace_id == workspace_id,
            GoldenAnswer.status == "pending_review",
        )
        .order_by(GoldenAnswer.submitted_at.asc())
        .all()
    )
    return [_serialize(ga) for ga in answers]


def get_overdue_reviews(db: Session, workspace_id: int) -> list[dict]:
    now = datetime.now(timezone.utc)
    answers = (
        db.query(GoldenAnswer)
        .filter(
            GoldenAnswer.workspace_id == workspace_id,
            GoldenAnswer.status == "pending_review",
            GoldenAnswer.submitted_at.isnot(None),
        )
        .all()
    )
    overdue = []
    for ga in answers:
        sla_hours = ga.review_sla_hours or 48
        submitted = (
            ga.submitted_at.replace(tzinfo=timezone.utc)
            if ga.submitted_at.tzinfo is None
            else ga.submitted_at
        )
        deadline = submitted + timedelta(hours=sla_hours)
        if now > deadline:
            d = _serialize(ga)
            d["sla_breached_hours"] = round((now - deadline).total_seconds() / 3600, 1)
            overdue.append(d)
    return overdue


def bulk_approve(
    db: Session, ga_ids: list[int], reviewer_id: int, *, workspace_id: int
) -> dict | None:
    authorized_ids = {
        row.id
        for row in db.query(GoldenAnswer.id)
        .filter(GoldenAnswer.id.in_(ga_ids), GoldenAnswer.workspace_id == workspace_id)
        .all()
    }
    if authorized_ids != set(ga_ids):
        return None
    approved = []
    skipped = []
    for ga_id in ga_ids:
        result = approve_answer(db, ga_id, reviewer_id, workspace_id=workspace_id)
        if result and "error" not in result:
            approved.append(ga_id)
        else:
            skipped.append(ga_id)
    db.flush()
    return {"approved": approved, "skipped": skipped}


def get_approval_history(db: Session, ga_id: int, *, workspace_id: int) -> list[dict] | None:
    if _get_answer(db, ga_id, workspace_id) is None:
        return None
    events = (
        db.query(AnswerApprovalEvent)
        .filter(
            AnswerApprovalEvent.golden_answer_id == ga_id,
        )
        .order_by(AnswerApprovalEvent.created_at.asc())
        .all()
    )
    return [
        {
            "id": e.id,
            "action": e.action,
            "actor_user_id": e.actor_user_id,
            "comment": e.comment,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]


def _log_event(
    db: Session, ga_id: int, action: str, actor_id: int | None, comment: str | None = None
) -> None:
    db.add(
        AnswerApprovalEvent(
            golden_answer_id=ga_id,
            action=action,
            actor_user_id=actor_id,
            comment=comment,
        )
    )


def _serialize(ga: GoldenAnswer) -> dict:
    return {
        "id": ga.id,
        "workspace_id": ga.workspace_id,
        "question_text": ga.question_text,
        "answer_text": ga.answer_text,
        "status": ga.status,
        "owner_user_id": ga.owner_user_id,
        "reviewer_user_id": ga.reviewer_user_id,
        "review_sla_hours": ga.review_sla_hours,
        "submitted_at": ga.submitted_at.isoformat() if ga.submitted_at else None,
        "last_reviewed_at": ga.last_reviewed_at.isoformat() if ga.last_reviewed_at else None,
        "expires_at": ga.expires_at.isoformat() if ga.expires_at else None,
        "created_at": ga.created_at.isoformat() if ga.created_at else None,
    }
