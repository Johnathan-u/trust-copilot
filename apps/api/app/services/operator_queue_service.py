"""Operator queue service — CRUD and dashboard stats for managed-service workflows."""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.operator_queue import (
    OPERATOR_ITEM_PRIORITIES,
    OPERATOR_ITEM_STATUSES,
    OperatorQueueItem,
)

logger = logging.getLogger(__name__)


def _serialize(item: OperatorQueueItem) -> dict:
    return {
        "id": item.id,
        "workspace_id": item.workspace_id,
        "questionnaire_id": item.questionnaire_id,
        "item_type": item.item_type,
        "status": item.status,
        "priority": item.priority,
        "title": item.title,
        "description": item.description,
        "assignee": item.assignee,
        "customer_name": item.customer_name,
        "customer_email": item.customer_email,
        "due_date": item.due_date.isoformat() if item.due_date else None,
        "blocked_reason": item.blocked_reason,
        "internal_notes": item.internal_notes,
        "questions_total": item.questions_total,
        "questions_answered": item.questions_answered,
        "evidence_gaps": item.evidence_gaps,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def create_item(
    db: Session,
    workspace_id: int,
    title: str,
    *,
    questionnaire_id: int | None = None,
    item_type: str = "questionnaire",
    priority: str = "normal",
    description: str | None = None,
    customer_name: str | None = None,
    customer_email: str | None = None,
    due_date: datetime | None = None,
) -> dict:
    """Create a new operator queue item."""
    if priority not in OPERATOR_ITEM_PRIORITIES:
        priority = "normal"
    item = OperatorQueueItem(
        workspace_id=workspace_id,
        questionnaire_id=questionnaire_id,
        item_type=item_type,
        status="received",
        priority=priority,
        title=title,
        description=description,
        customer_name=customer_name,
        customer_email=customer_email,
        due_date=due_date,
    )
    db.add(item)
    db.flush()
    return _serialize(item)


def list_items(
    db: Session,
    workspace_id: int | None = None,
    status: str | None = None,
    priority: str | None = None,
    assignee: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List operator queue items with optional filters. If workspace_id is None, lists across all workspaces (operator view)."""
    q = db.query(OperatorQueueItem)
    if workspace_id is not None:
        q = q.filter(OperatorQueueItem.workspace_id == workspace_id)
    if status:
        q = q.filter(OperatorQueueItem.status == status)
    if priority:
        q = q.filter(OperatorQueueItem.priority == priority)
    if assignee:
        q = q.filter(OperatorQueueItem.assignee == assignee)
    q = q.order_by(
        OperatorQueueItem.due_date.asc().nullslast(),
        OperatorQueueItem.created_at.desc(),
    )
    items = q.offset(offset).limit(limit).all()
    return [_serialize(i) for i in items]


def get_item(db: Session, item_id: int) -> dict | None:
    """Get a single queue item by ID."""
    item = db.query(OperatorQueueItem).filter(OperatorQueueItem.id == item_id).first()
    return _serialize(item) if item else None


def update_item(db: Session, item_id: int, **updates) -> dict | None:
    """Update fields on a queue item. Returns None if not found."""
    item = db.query(OperatorQueueItem).filter(OperatorQueueItem.id == item_id).first()
    if not item:
        return None
    allowed_fields = {
        "status", "priority", "title", "description", "assignee",
        "customer_name", "customer_email", "due_date", "blocked_reason",
        "internal_notes", "questions_total", "questions_answered", "evidence_gaps",
    }
    for key, value in updates.items():
        if key in allowed_fields:
            if key == "status" and value not in OPERATOR_ITEM_STATUSES:
                continue
            if key == "priority" and value not in OPERATOR_ITEM_PRIORITIES:
                continue
            setattr(item, key, value)
    db.flush()
    return _serialize(item)


def delete_item(db: Session, item_id: int) -> bool:
    """Delete a queue item. Returns True if deleted."""
    item = db.query(OperatorQueueItem).filter(OperatorQueueItem.id == item_id).first()
    if not item:
        return False
    db.delete(item)
    db.flush()
    return True


def dashboard_stats(db: Session, workspace_id: int | None = None) -> dict:
    """Return aggregate stats for the operator dashboard."""
    q = db.query(OperatorQueueItem)
    if workspace_id is not None:
        q = q.filter(OperatorQueueItem.workspace_id == workspace_id)

    all_items = q.all()
    total = len(all_items)

    by_status: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    overdue = 0
    now = datetime.now(timezone.utc)

    for item in all_items:
        by_status[item.status] = by_status.get(item.status, 0) + 1
        by_priority[item.priority] = by_priority.get(item.priority, 0) + 1
        if item.due_date and item.due_date < now and item.status not in ("delivered", "closed"):
            overdue += 1

    return {
        "total": total,
        "by_status": by_status,
        "by_priority": by_priority,
        "overdue": overdue,
    }
