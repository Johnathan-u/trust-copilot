"""In-app notification center API: list, unread count, mark read."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, exists, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.core.auth_deps import _resolve_permission, require_session
from app.core.database import get_db
from app.models import InAppNotification, WorkspaceMember
from app.models.in_app_notification import InAppNotificationReceipt

router = APIRouter(prefix="/in-app-notifications", tags=["in-app-notifications"])


async def _inbox_session(
    db: Session = Depends(get_db),
    session: dict = Depends(require_session),
) -> dict:
    """Resolve current membership and permissions without trusting stale token roles."""
    uid = session.get("user_id")
    if not uid:
        return session
    member = (
        db.query(WorkspaceMember)
        .filter_by(workspace_id=session["workspace_id"], user_id=uid)
        .first()
    )
    if member is None or member.suspended:
        raise HTTPException(status_code=403, detail="Active workspace membership required")
    return {
        **session,
        "inbox_admin": _resolve_permission(member.role, "can_admin", member.workspace_id, db),
    }


def _personal_user(session: dict) -> int:
    uid = session.get("user_id")
    if not uid:
        raise HTTPException(status_code=400, detail="User context required")
    return uid


def _user_filter(ws: int, uid: int, is_admin: bool):
    """Filter: notifications for this user in this workspace, respecting admin_only."""
    base = and_(
        InAppNotification.workspace_id == ws,
        or_(InAppNotification.user_id == uid, InAppNotification.user_id.is_(None)),
    )
    if not is_admin:
        return and_(base, InAppNotification.admin_only == False)  # noqa: E712
    return base


def _effective_read(ws: int, uid: int):
    """Preserve legacy read history; only broadcasts use per-member receipts."""
    receipt_exists = exists().where(
        InAppNotificationReceipt.workspace_id == ws,
        InAppNotificationReceipt.notification_id == InAppNotification.id,
        InAppNotificationReceipt.user_id == uid,
    )
    return or_(
        InAppNotification.is_read.is_(True),
        and_(InAppNotification.user_id.is_(None), receipt_exists),
    )


@router.get("")
async def list_notifications(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    session: dict = Depends(_inbox_session),
):
    """List recent in-app notifications for the current user."""
    ws = session["workspace_id"]
    uid = session.get("user_id")
    if not uid:
        return {"notifications": [], "total": 0}
    is_admin = session["inbox_admin"]
    filt = _user_filter(ws, uid, is_admin)
    total = db.query(InAppNotification).filter(filt).count()
    rows = (
        db.query(InAppNotification, _effective_read(ws, uid).label("effective_read"))
        .filter(filt)
        .order_by(InAppNotification.created_at.desc(), InAppNotification.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "notifications": [
            {
                "id": n.id,
                "title": n.title,
                "body": n.body,
                "category": n.category,
                "link": n.link,
                "is_read": bool(is_read),
                "admin_only": bool(n.admin_only),
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n, is_read in rows
        ],
    }


@router.get("/unread-count")
async def unread_count(
    db: Session = Depends(get_db),
    session: dict = Depends(_inbox_session),
):
    """Return the number of unread notifications."""
    ws = session["workspace_id"]
    uid = session.get("user_id")
    if not uid:
        return {"count": 0}
    is_admin = session["inbox_admin"]
    filt = and_(_user_filter(ws, uid, is_admin), ~_effective_read(ws, uid))
    count = db.query(InAppNotification).filter(filt).count()
    return {"count": count}


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    session: dict = Depends(_inbox_session),
):
    """Mark a single notification as read."""
    ws = session["workspace_id"]
    uid = _personal_user(session)
    n = (
        db.query(InAppNotification)
        .filter(
            InAppNotification.id == notification_id,
            _user_filter(ws, uid, session["inbox_admin"]),
        )
        .first()
    )
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    if n.user_id is None:
        # Historical read broadcasts remain read without inventing a receipt.
        if not n.is_read:
            db.execute(
                insert(InAppNotificationReceipt)
                .values(workspace_id=ws, notification_id=n.id, user_id=uid)
                .on_conflict_do_nothing()
            )
    else:
        n.is_read = True
    db.commit()
    return {"ok": True}


@router.post("/read-all")
async def mark_all_read(
    db: Session = Depends(get_db),
    session: dict = Depends(_inbox_session),
):
    """Mark all notifications as read for the current user."""
    ws = session["workspace_id"]
    uid = _personal_user(session)
    is_admin = session["inbox_admin"]
    filt = and_(_user_filter(ws, uid, is_admin), ~_effective_read(ws, uid))
    updated = (
        db.query(InAppNotification)
        .filter(filt, InAppNotification.user_id == uid)
        .update({"is_read": True}, synchronize_session=False)
    )
    # INSERT ... SELECT and the unique key make repeated/concurrent calls safe.
    # RETURNING counts actual new receipts, including conflict races correctly.
    shared = (
        select(InAppNotification.workspace_id, InAppNotification.id, literal(uid), func.now())
        .where(filt, InAppNotification.user_id.is_(None))
        .order_by(InAppNotification.id)
    )
    inserted = db.execute(
        insert(InAppNotificationReceipt)
        .from_select(["workspace_id", "notification_id", "user_id", "read_at"], shared)
        .on_conflict_do_nothing()
        .returning(InAppNotificationReceipt.notification_id)
    )
    updated += len(inserted.all())
    db.commit()
    return {"updated": updated}
