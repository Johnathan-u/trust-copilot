"""Current membership and recipient validation for notification rules."""

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth_deps import _resolve_permission, require_session
from app.core.database import get_db
from app.core.roles import BUILTIN_ROLES
from app.models import CustomRole, WorkspaceMember


def require_notification_session(
    session: dict = Depends(require_session), db: Session = Depends(get_db)
) -> dict:
    """Use current membership, including after a session's role changes."""
    uid = session.get("user_id")
    if uid is None:
        # API keys already resolve their current role through require_session.
        return session
    member = (
        db.query(WorkspaceMember)
        .filter_by(workspace_id=session["workspace_id"], user_id=uid)
        .first()
    )
    if member is None or member.suspended:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return {**session, "role": member.role}


def require_notification_admin(
    session: dict = Depends(require_notification_session), db: Session = Depends(get_db)
) -> dict:
    if not _resolve_permission(session.get("role"), "can_admin", session["workspace_id"], db):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return session


def validate_recipient(
    db: Session, workspace_id: int, recipient_type: str, recipient_value: str | None
) -> tuple[str, str | None]:
    """Return a canonical recipient or a workspace-independent error."""
    kind = recipient_type.strip().lower()
    if kind not in ("all", "admins", "role", "user"):
        raise HTTPException(
            status_code=400, detail="recipient_type must be all, admins, role, or user"
        )
    if kind in ("all", "admins"):
        return kind, None
    value = (recipient_value or "").strip()
    if not value:
        raise HTTPException(
            status_code=400, detail=f"recipient_value required for recipient_type='{kind}'"
        )
    if kind == "user":
        try:
            uid = int(value)
        except ValueError:
            uid = 0
        # The persisted user id is a PostgreSQL INTEGER. Reject before binding.
        member = None
        if 0 < uid <= 2_147_483_647:
            member = (
                db.query(WorkspaceMember)
                .filter_by(workspace_id=workspace_id, user_id=uid, suspended=False)
                .first()
            )
        if member is None:
            raise HTTPException(status_code=404, detail="Recipient not found")
        return kind, str(uid)
    value = value.lower()
    if value not in BUILTIN_ROLES:
        role = db.query(CustomRole).filter_by(workspace_id=workspace_id, name=value).first()
        if role is None:
            raise HTTPException(status_code=404, detail="Recipient not found")
    return kind, value
