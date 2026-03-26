"""Operator queue API — internal managed-service queue (admin only)."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin
from app.core.database import get_db
from app.services import operator_queue_service as oq

router = APIRouter(prefix="/operator-queue", tags=["operator-queue"])


class CreateItemRequest(BaseModel):
    title: str
    questionnaire_id: int | None = None
    item_type: str = "questionnaire"
    priority: str = "normal"
    description: str | None = None
    customer_name: str | None = None
    customer_email: str | None = None
    due_date: datetime | None = None


class UpdateItemRequest(BaseModel):
    status: str | None = None
    priority: str | None = None
    title: str | None = None
    description: str | None = None
    assignee: str | None = None
    customer_name: str | None = None
    customer_email: str | None = None
    due_date: datetime | None = None
    blocked_reason: str | None = None
    internal_notes: str | None = None
    questions_total: int | None = None
    questions_answered: int | None = None
    evidence_gaps: int | None = None


@router.get("")
async def list_items(
    status: str | None = Query(None),
    priority: str | None = Query(None),
    assignee: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """List operator queue items for the current workspace."""
    workspace_id = session["workspace_id"]
    items = oq.list_items(db, workspace_id, status=status, priority=priority, assignee=assignee, limit=limit, offset=offset)
    return {"items": items}


@router.get("/dashboard")
async def dashboard(
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Get operator dashboard stats."""
    workspace_id = session["workspace_id"]
    stats = oq.dashboard_stats(db, workspace_id)
    return stats


@router.get("/{item_id}")
async def get_item(
    item_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Get a single operator queue item."""
    item = oq.get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if item["workspace_id"] != session["workspace_id"]:
        raise HTTPException(status_code=403, detail="Not your workspace")
    return item


@router.post("")
async def create_item(
    req: CreateItemRequest,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Create a new operator queue item."""
    workspace_id = session["workspace_id"]
    if not req.title.strip():
        raise HTTPException(status_code=400, detail="Title is required")
    item = oq.create_item(
        db, workspace_id, req.title.strip(),
        questionnaire_id=req.questionnaire_id,
        item_type=req.item_type,
        priority=req.priority,
        description=req.description,
        customer_name=req.customer_name,
        customer_email=req.customer_email,
        due_date=req.due_date,
    )
    db.commit()
    return item


@router.patch("/{item_id}")
async def update_item(
    item_id: int,
    req: UpdateItemRequest,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Update an operator queue item."""
    existing = oq.get_item(db, item_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Item not found")
    if existing["workspace_id"] != session["workspace_id"]:
        raise HTTPException(status_code=403, detail="Not your workspace")
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    result = oq.update_item(db, item_id, **updates)
    db.commit()
    return result


@router.delete("/{item_id}")
async def delete_item(
    item_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Delete an operator queue item."""
    existing = oq.get_item(db, item_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Item not found")
    if existing["workspace_id"] != session["workspace_id"]:
        raise HTTPException(status_code=403, detail="Not your workspace")
    oq.delete_item(db, item_id)
    db.commit()
    return {"deleted": True}
