"""Audit events API (C1). Admin-only export and browsing for SIEM/compliance."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin
from app.core.database import get_db
from app.models import AuditEvent

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/events")
def list_audit_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    action: str | None = Query(None, description="Filter by action prefix"),
    since_hours: int = Query(168, ge=1, le=720, description="Events from last N hours"),
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Paginated audit event viewer for admin dashboard."""
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(status_code=403, detail="Workspace required")
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    q = db.query(AuditEvent).filter(
        AuditEvent.workspace_id == ws,
        AuditEvent.occurred_at >= since,
    )
    if action:
        q = q.filter(AuditEvent.action.ilike(f"{action}%"))
    total = q.count()
    rows = (
        q.order_by(AuditEvent.occurred_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "events": [
            {
                "id": r.id,
                "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
                "action": r.action,
                "user_id": r.user_id,
                "email": r.email,
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "details": r.details,
            }
            for r in rows
        ],
    }


@router.get("/export")
def export_audit_events(
    since_hours: int = Query(24, ge=1, le=720, description="Export events from last N hours (max 30 days)"),
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Export audit events for SIEM or compliance. Admin only. Returns JSON array."""
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(status_code=403, detail="Workspace required")
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    rows = (
        db.query(AuditEvent)
        .filter(AuditEvent.workspace_id == ws, AuditEvent.occurred_at >= since)
        .order_by(AuditEvent.occurred_at.asc())
        .limit(10000)
        .all()
    )
    return [
        {
            "id": r.id,
            "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
            "action": r.action,
            "user_id": r.user_id,
            "email": r.email,
            "workspace_id": r.workspace_id,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "details": r.details,
        }
        for r in rows
    ]
