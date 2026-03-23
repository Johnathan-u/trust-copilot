"""In-app notification center API: list, unread count, mark read."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.core.auth_deps import require_session
from app.core.database import get_db
from app.core.roles import can_admin
from app.models import InAppNotification

router = APIRouter(prefix="/in-app-notifications", tags=["in-app-notifications"])


def _user_filter(ws: int, uid: int, is_admin: bool):
    """Filter: notifications for this user in this workspace, respecting admin_only."""
    base = and_(
        InAppNotification.workspace_id == ws,
        or_(InAppNotification.user_id == uid, InAppNotification.user_id.is_(None)),
    )
    if not is_admin:
        return and_(base, InAppNotification.admin_only == False)
    return base


@router.get("")
async def list_notifications(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    session: dict = Depends(require_session),
):
    """List recent in-app notifications for the current user."""
    ws = session["workspace_id"]
    uid = session.get("user_id")
    if not uid:
        return {"notifications": [], "total": 0}
    is_admin = can_admin(session.get("role"))
    filt = _user_filter(ws, uid, is_admin)
    total = db.query(InAppNotification).filter(filt).count()
    rows = (
        db.query(InAppNotification)
        .filter(filt)
        .order_by(InAppNotification.created_at.desc())
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
                "is_read": bool(n.is_read),
                "admin_only": bool(n.admin_only),
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in rows
        ],
    }


@router.get("/unread-count")
async def unread_count(
    db: Session = Depends(get_db),
    session: dict = Depends(require_session),
):
    """Return the number of unread notifications."""
    ws = session["workspace_id"]
    uid = session.get("user_id")
    if not uid:
        return {"count": 0}
    is_admin = can_admin(session.get("role"))
    filt = and_(_user_filter(ws, uid, is_admin), InAppNotification.is_read == False)
    count = db.query(InAppNotification).filter(filt).count()
    return {"count": count}


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    session: dict = Depends(require_session),
):
    """Mark a single notification as read."""
    ws = session["workspace_id"]
    uid = session.get("user_id")
    n = db.query(InAppNotification).filter(
        InAppNotification.id == notification_id,
        InAppNotification.workspace_id == ws,
        or_(InAppNotification.user_id == uid, InAppNotification.user_id.is_(None)),
    ).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    n.is_read = True
    db.commit()
    return {"ok": True}


@router.post("/read-all")
async def mark_all_read(
    db: Session = Depends(get_db),
    session: dict = Depends(require_session),
):
    """Mark all notifications as read for the current user."""
    ws = session["workspace_id"]
    uid = session.get("user_id")
    if not uid:
        return {"updated": 0}
    is_admin = can_admin(session.get("role"))
    filt = and_(_user_filter(ws, uid, is_admin), InAppNotification.is_read == False)
    updated = db.query(InAppNotification).filter(filt).update({"is_read": True}, synchronize_session=False)
    db.commit()
    return {"updated": updated}
