"""Phase C: Notification policies, delivery log, and unsubscribe API."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import persist_audit
from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.models import (
    NOTIFICATION_EVENT_TYPES,
    NotificationLog,
    NotificationPolicy,
    NotificationUnsubscribe,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


# ---- Schemas ----

class PolicyCreateRequest(BaseModel):
    event_type: str
    enabled: bool = True
    recipient_type: str = "admins"
    recipient_value: str | None = None


class PolicyUpdateRequest(BaseModel):
    enabled: bool | None = None
    recipient_type: str | None = None
    recipient_value: str | None = None


class UnsubscribeRequest(BaseModel):
    event_type: str


# ---- Policy CRUD (admin only) ----

@router.get("/event-types")
async def list_event_types(session: dict = Depends(require_session)):
    """Return supported notification event types."""
    return {"event_types": NOTIFICATION_EVENT_TYPES}


@router.get("/policies")
async def list_policies(
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """List all notification policies for this workspace."""
    ws = session["workspace_id"]
    rows = db.query(NotificationPolicy).filter(NotificationPolicy.workspace_id == ws).order_by(NotificationPolicy.event_type).all()
    return {
        "policies": [
            {
                "id": p.id,
                "event_type": p.event_type,
                "enabled": bool(p.enabled),
                "recipient_type": p.recipient_type,
                "recipient_value": p.recipient_value,
                "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            }
            for p in rows
        ],
    }


@router.post("/policies")
async def create_policy(
    req: PolicyCreateRequest,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Create a notification policy for an event type."""
    ws = session["workspace_id"]
    et = (req.event_type or "").strip()
    if et not in NOTIFICATION_EVENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown event type: {et}")
    rt = (req.recipient_type or "").strip().lower()
    if rt not in ("all", "admins", "role", "user"):
        raise HTTPException(status_code=400, detail="recipient_type must be all, admins, role, or user")
    if rt in ("role", "user") and not (req.recipient_value or "").strip():
        raise HTTPException(status_code=400, detail=f"recipient_value required for recipient_type='{rt}'")
    existing = db.query(NotificationPolicy).filter(
        NotificationPolicy.workspace_id == ws, NotificationPolicy.event_type == et
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Policy already exists for this event type. Use PATCH to update.")
    p = NotificationPolicy(
        workspace_id=ws,
        event_type=et,
        enabled=req.enabled,
        recipient_type=rt,
        recipient_value=(req.recipient_value or "").strip() or None,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    persist_audit(db, "notification.policy_created", user_id=session.get("user_id"), workspace_id=ws,
                  resource_type="notification_policy", resource_id=p.id,
                  details={"event_type": et, "recipient_type": rt, "enabled": req.enabled})
    return {"id": p.id, "event_type": p.event_type, "enabled": bool(p.enabled), "recipient_type": p.recipient_type, "recipient_value": p.recipient_value}


@router.patch("/policies/{policy_id}")
async def update_policy(
    policy_id: int,
    req: PolicyUpdateRequest,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Update an existing notification policy."""
    ws = session["workspace_id"]
    p = db.query(NotificationPolicy).filter(NotificationPolicy.id == policy_id, NotificationPolicy.workspace_id == ws).first()
    if not p:
        raise HTTPException(status_code=404, detail="Policy not found")
    changes = {}
    if req.enabled is not None and p.enabled != req.enabled:
        changes["enabled"] = {"from": p.enabled, "to": req.enabled}
        p.enabled = req.enabled
    if req.recipient_type is not None:
        rt = req.recipient_type.strip().lower()
        if rt not in ("all", "admins", "role", "user"):
            raise HTTPException(status_code=400, detail="Invalid recipient_type")
        if p.recipient_type != rt:
            changes["recipient_type"] = {"from": p.recipient_type, "to": rt}
            p.recipient_type = rt
    if req.recipient_value is not None and p.recipient_value != req.recipient_value:
        changes["recipient_value"] = {"from": p.recipient_value, "to": req.recipient_value}
        p.recipient_value = req.recipient_value.strip() or None
    db.commit()
    db.refresh(p)
    if changes:
        persist_audit(db, "notification.policy_updated", user_id=session.get("user_id"), workspace_id=ws,
                      resource_type="notification_policy", resource_id=p.id,
                      details={"event_type": p.event_type, "changes": changes})
    return {"id": p.id, "event_type": p.event_type, "enabled": bool(p.enabled), "recipient_type": p.recipient_type, "recipient_value": p.recipient_value}


@router.delete("/policies/{policy_id}")
async def delete_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Delete a notification policy."""
    ws = session["workspace_id"]
    p = db.query(NotificationPolicy).filter(NotificationPolicy.id == policy_id, NotificationPolicy.workspace_id == ws).first()
    if not p:
        raise HTTPException(status_code=404, detail="Policy not found")
    et = p.event_type
    db.delete(p)
    db.commit()
    persist_audit(db, "notification.policy_deleted", user_id=session.get("user_id"), workspace_id=ws,
                  resource_type="notification_policy", details={"event_type": et})
    return {"ok": True}


# ---- Delivery log (admin) ----

@router.get("/log")
async def list_delivery_log(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Paginated delivery log for this workspace."""
    ws = session["workspace_id"]
    q = db.query(NotificationLog).filter(NotificationLog.workspace_id == ws)
    if status_filter:
        q = q.filter(NotificationLog.status == status_filter)
    total = q.count()
    rows = q.order_by(NotificationLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "entries": [
            {
                "id": r.id,
                "event_type": r.event_type,
                "channel": getattr(r, "channel", "email") or "email",
                "recipient_email": r.recipient_email,
                "subject": r.subject,
                "status": r.status,
                "error": r.error,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


# ---- Unsubscribe (self-service for any authenticated user) ----

@router.get("/unsubscribes")
async def list_my_unsubscribes(
    db: Session = Depends(get_db),
    session: dict = Depends(require_session),
):
    """List event types the current user has unsubscribed from."""
    uid = session.get("user_id")
    ws = session["workspace_id"]
    if not uid:
        return {"unsubscribes": []}
    rows = db.query(NotificationUnsubscribe).filter(
        NotificationUnsubscribe.workspace_id == ws, NotificationUnsubscribe.user_id == uid
    ).all()
    return {"unsubscribes": [{"id": r.id, "event_type": r.event_type} for r in rows]}


@router.post("/unsubscribes")
async def add_unsubscribe(
    req: UnsubscribeRequest,
    db: Session = Depends(get_db),
    session: dict = Depends(require_session),
):
    """Opt out of a specific notification event type."""
    uid = session.get("user_id")
    ws = session["workspace_id"]
    if not uid:
        raise HTTPException(status_code=400, detail="User context required")
    et = (req.event_type or "").strip()
    if et not in NOTIFICATION_EVENT_TYPES:
        raise HTTPException(status_code=400, detail="Unknown event type")
    existing = db.query(NotificationUnsubscribe).filter(
        NotificationUnsubscribe.workspace_id == ws, NotificationUnsubscribe.user_id == uid, NotificationUnsubscribe.event_type == et
    ).first()
    if existing:
        return {"id": existing.id, "event_type": et}
    unsub = NotificationUnsubscribe(workspace_id=ws, user_id=uid, event_type=et)
    db.add(unsub)
    db.commit()
    db.refresh(unsub)
    return {"id": unsub.id, "event_type": et}


@router.delete("/unsubscribes/{unsub_id}")
async def remove_unsubscribe(
    unsub_id: int,
    db: Session = Depends(get_db),
    session: dict = Depends(require_session),
):
    """Re-subscribe to a notification event type."""
    uid = session.get("user_id")
    ws = session["workspace_id"]
    row = db.query(NotificationUnsubscribe).filter(
        NotificationUnsubscribe.id == unsub_id, NotificationUnsubscribe.workspace_id == ws, NotificationUnsubscribe.user_id == uid
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(row)
    db.commit()
    return {"ok": True}
