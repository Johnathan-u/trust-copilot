"""Phase C: Notification policies, delivery log, and unsubscribe API."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.audit import persist_audit
from app.core.database import get_db
from app.models import (
    NOTIFICATION_CHANNELS,
    NOTIFICATION_EVENT_TYPES,
    NotificationChannelPreference,
    NotificationDeliveryAttempt,
    NotificationLog,
    NotificationPolicy,
    NotificationUnsubscribe,
)
from app.models.in_app_notification import InAppNotification
from app.services.notification_policy_service import (
    require_notification_admin,
    require_notification_session,
    validate_recipient,
)
from app.services.notification_preferences import (
    effective_channels,
    list_preferences,
    set_channel_preference,
)
from app.services.notification_redaction import redact_notification_text

router = APIRouter(prefix="/notifications", tags=["notifications"])


# ---- Schemas ----


class PolicyRecipientFields(BaseModel):
    recipient_value: str | None = Field(None, max_length=255)

    @field_validator("recipient_value")
    @classmethod
    def safe_recipient(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
                raise ValueError("recipient_value cannot contain control characters")
            if len(value.lower()) > 255:
                raise ValueError("Normalized recipient_value cannot exceed 255 characters")
        return value


class PolicyCreateRequest(PolicyRecipientFields):
    event_type: str = Field(max_length=64)
    enabled: bool = True
    recipient_type: str = Field("admins", max_length=32)


class PolicyUpdateRequest(PolicyRecipientFields):
    enabled: bool | None = None
    recipient_type: str | None = Field(None, max_length=32)


class UnsubscribeRequest(BaseModel):
    event_type: str


class ChannelPreferencePut(BaseModel):
    channel: str
    enabled: bool
    event_type: str | None = None


# ---- Policy CRUD (admin only) ----


@router.get("/event-types")
async def list_event_types(session: dict = Depends(require_notification_session)):
    """Return supported notification event types."""
    return {"event_types": NOTIFICATION_EVENT_TYPES}


@router.get("/policies")
async def list_policies(
    db: Session = Depends(get_db),
    session: dict = Depends(require_notification_admin),
):
    """List all notification policies for this workspace."""
    ws = session["workspace_id"]
    rows = (
        db.query(NotificationPolicy)
        .filter(NotificationPolicy.workspace_id == ws)
        .order_by(NotificationPolicy.event_type)
        .all()
    )
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
    session: dict = Depends(require_notification_admin),
):
    """Create a notification policy for an event type."""
    ws = session["workspace_id"]
    et = (req.event_type or "").strip()
    if et not in NOTIFICATION_EVENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown event type: {et}")
    rt, value = validate_recipient(db, ws, req.recipient_type, req.recipient_value)
    existing = (
        db.query(NotificationPolicy)
        .filter(NotificationPolicy.workspace_id == ws, NotificationPolicy.event_type == et)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Policy already exists for this event type. Use PATCH to update.",
        )
    p = NotificationPolicy(
        workspace_id=ws,
        event_type=et,
        enabled=req.enabled,
        recipient_type=rt,
        recipient_value=value,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    persist_audit(
        db,
        "notification.policy_created",
        user_id=session.get("user_id"),
        workspace_id=ws,
        resource_type="notification_policy",
        resource_id=p.id,
        details={"event_type": et, "recipient_type": rt, "enabled": req.enabled},
    )
    return {
        "id": p.id,
        "event_type": p.event_type,
        "enabled": bool(p.enabled),
        "recipient_type": p.recipient_type,
        "recipient_value": p.recipient_value,
    }


@router.patch("/policies/{policy_id}")
async def update_policy(
    policy_id: int,
    req: PolicyUpdateRequest,
    db: Session = Depends(get_db),
    session: dict = Depends(require_notification_admin),
):
    """Update an existing notification policy."""
    ws = session["workspace_id"]
    p = (
        db.query(NotificationPolicy)
        .filter(NotificationPolicy.id == policy_id, NotificationPolicy.workspace_id == ws)
        .first()
    )
    if not p:
        raise HTTPException(status_code=404, detail="Policy not found")
    # Validate the complete prospective pair before changing any persisted field.
    rt, value = validate_recipient(
        db,
        ws,
        req.recipient_type if req.recipient_type is not None else p.recipient_type,
        req.recipient_value if "recipient_value" in req.model_fields_set else p.recipient_value,
    )
    prospective = {"recipient_type": rt, "recipient_value": value}
    if req.enabled is not None:
        prospective["enabled"] = req.enabled
    changes = {}
    for field, value in prospective.items():
        old = getattr(p, field)
        if old != value:
            changes[field] = {"from": old, "to": value}
            setattr(p, field, value)
    db.commit()
    db.refresh(p)
    if changes:
        persist_audit(
            db,
            "notification.policy_updated",
            user_id=session.get("user_id"),
            workspace_id=ws,
            resource_type="notification_policy",
            resource_id=p.id,
            details={"event_type": p.event_type, "changes": changes},
        )
    return {
        "id": p.id,
        "event_type": p.event_type,
        "enabled": bool(p.enabled),
        "recipient_type": p.recipient_type,
        "recipient_value": p.recipient_value,
    }


@router.delete("/policies/{policy_id}")
async def delete_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    session: dict = Depends(require_notification_admin),
):
    """Delete a notification policy."""
    ws = session["workspace_id"]
    p = (
        db.query(NotificationPolicy)
        .filter(NotificationPolicy.id == policy_id, NotificationPolicy.workspace_id == ws)
        .first()
    )
    if not p:
        raise HTTPException(status_code=404, detail="Policy not found")
    et = p.event_type
    db.delete(p)
    db.commit()
    persist_audit(
        db,
        "notification.policy_deleted",
        user_id=session.get("user_id"),
        workspace_id=ws,
        resource_type="notification_policy",
        details={"event_type": et},
    )
    return {"ok": True}


# ---- Delivery log (admin) ----


@router.get("/log")
async def list_delivery_log(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    session: dict = Depends(require_notification_admin),
):
    """Paginated delivery log for this workspace."""
    ws = session["workspace_id"]
    q = db.query(NotificationLog).filter(NotificationLog.workspace_id == ws)
    if status_filter:
        q = q.filter(NotificationLog.status == status_filter)
    total = q.count()
    rows = (
        q.order_by(NotificationLog.created_at.desc(), NotificationLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
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
                "error": redact_notification_text(r.error) or None,
                "delivery_state": r.delivery_state,
                "delivered_to_provider": bool(r.delivered_to_provider),
                "provider_mode": r.provider_mode,
                "dedupe_key": r.dedupe_key,
                "attempt_count": r.attempt_count,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


# ---- Unsubscribe (self-service for any authenticated user) ----


@router.get("/unsubscribes")
async def list_my_unsubscribes(
    db: Session = Depends(get_db),
    session: dict = Depends(require_notification_session),
):
    """List event types the current user has unsubscribed from."""
    uid = session.get("user_id")
    ws = session["workspace_id"]
    if not uid:
        return {"unsubscribes": []}
    rows = (
        db.query(NotificationUnsubscribe)
        .filter(NotificationUnsubscribe.workspace_id == ws, NotificationUnsubscribe.user_id == uid)
        .all()
    )
    return {"unsubscribes": [{"id": r.id, "event_type": r.event_type} for r in rows]}


@router.post("/unsubscribes")
async def add_unsubscribe(
    req: UnsubscribeRequest,
    db: Session = Depends(get_db),
    session: dict = Depends(require_notification_session),
):
    """Opt out of a specific notification event type."""
    uid = session.get("user_id")
    ws = session["workspace_id"]
    if not uid:
        raise HTTPException(status_code=400, detail="User context required")
    et = (req.event_type or "").strip()
    if et not in NOTIFICATION_EVENT_TYPES:
        raise HTTPException(status_code=400, detail="Unknown event type")
    existing = (
        db.query(NotificationUnsubscribe)
        .filter(
            NotificationUnsubscribe.workspace_id == ws,
            NotificationUnsubscribe.user_id == uid,
            NotificationUnsubscribe.event_type == et,
        )
        .first()
    )
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
    session: dict = Depends(require_notification_session),
):
    """Re-subscribe to a notification event type."""
    uid = session.get("user_id")
    ws = session["workspace_id"]
    row = (
        db.query(NotificationUnsubscribe)
        .filter(
            NotificationUnsubscribe.id == unsub_id,
            NotificationUnsubscribe.workspace_id == ws,
            NotificationUnsubscribe.user_id == uid,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


def _preference_body(row: NotificationChannelPreference) -> dict:
    return {
        "id": row.id,
        "channel": row.channel,
        "event_type": row.event_type or None,
        "enabled": bool(row.enabled),
    }


@router.get("/channel-preferences")
async def get_channel_preferences(
    db: Session = Depends(get_db),
    session: dict = Depends(require_notification_session),
):
    """Channel switches for the current user. Schema version 1.

    Existing policy and unsubscribe routes are unchanged. This is the
    per-user email, Slack, and in-app preference.
    """
    uid = session.get("user_id")
    ws = session["workspace_id"]
    if not uid:
        return {
            "schema_version": 1,
            "channels": list(NOTIFICATION_CHANNELS),
            "effective": {},
            "preferences": [],
        }
    rows = list_preferences(db, ws, uid)
    return {
        "schema_version": 1,
        "channels": list(NOTIFICATION_CHANNELS),
        "effective": effective_channels(db, ws, uid),
        "preferences": [_preference_body(row) for row in rows],
    }


@router.put("/channel-preferences")
async def put_channel_preference(
    req: ChannelPreferencePut,
    db: Session = Depends(get_db),
    session: dict = Depends(require_notification_session),
):
    """Set one channel-wide or event-specific preference for the current user."""
    uid = session.get("user_id")
    ws = session["workspace_id"]
    if not uid:
        raise HTTPException(status_code=400, detail="User context required")
    channel = (req.channel or "").strip().lower()
    if channel not in NOTIFICATION_CHANNELS:
        raise HTTPException(status_code=400, detail="channel must be email, slack, or in_app")
    event_type = (req.event_type or "").strip()
    if event_type and event_type not in NOTIFICATION_EVENT_TYPES:
        raise HTTPException(status_code=400, detail="Unknown event type")
    row = set_channel_preference(db, ws, uid, channel, bool(req.enabled), event_type or None)
    db.commit()
    db.refresh(row)
    persist_audit(
        db,
        "notification.channel_preference_updated",
        user_id=uid,
        workspace_id=ws,
        resource_type="notification_channel_preference",
        resource_id=row.id,
        details={
            "channel": channel,
            "event_type": event_type or None,
            "enabled": bool(req.enabled),
        },
    )
    return {"schema_version": 1, **_preference_body(row)}


@router.get("/delivery-attempts")
async def list_delivery_attempts(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    session: dict = Depends(require_notification_admin),
):
    """Each delivery try and its state. Errors are redacted. Schema version 1.

    The legacy ``/log`` list is unchanged aside from additive fields. This
    list is the attempt ledger. Notification copy uses the shared static renderer.
    """
    ws = session["workspace_id"]
    q = (
        db.query(NotificationDeliveryAttempt, InAppNotification)
        .outerjoin(
            InAppNotification,
            and_(
                InAppNotification.id == NotificationDeliveryAttempt.in_app_notification_id,
                InAppNotification.workspace_id == NotificationDeliveryAttempt.workspace_id,
            ),
        )
        .filter(NotificationDeliveryAttempt.workspace_id == ws)
    )
    total = q.count()
    rows = (
        q.order_by(NotificationDeliveryAttempt.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    attempts = []
    for attempt, note in rows:
        attempts.append(
            {
                "id": attempt.id,
                "event_type": attempt.event_type,
                "channel": attempt.channel,
                "recipient": attempt.recipient,
                "user_id": attempt.user_id,
                "state": attempt.state,
                "attempt_number": attempt.attempt_number,
                "max_attempts": attempt.max_attempts,
                "dedupe_key": attempt.dedupe_key,
                "delivered_to_provider": bool(attempt.delivered_to_provider),
                "provider_mode": attempt.provider_mode,
                "template_key": attempt.template_key,
                "destination": attempt.destination,
                "rendered_subject": redact_notification_text(attempt.rendered_subject) or None,
                "rendered_body": redact_notification_text(attempt.rendered_body, limit=2000)
                or None,
                "error_code": attempt.error_code,
                "error": redact_notification_text(attempt.error_message) or None,
                "in_app_notification_id": None if note is None else note.id,
                "is_read": None if note is None else bool(note.is_read),
                "created_at": attempt.created_at.isoformat() if attempt.created_at else None,
            }
        )
    return {"schema_version": 1, "total": total, "page": page, "attempts": attempts}
