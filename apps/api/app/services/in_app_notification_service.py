"""In-app notification dispatch: creates notifications for users in a workspace."""

import logging

from sqlalchemy.orm import Session

from app.models.in_app_notification import InAppNotification
from app.models.user import WorkspaceMember

logger = logging.getLogger(__name__)


def notify_user(
    db: Session,
    workspace_id: int,
    user_id: int,
    title: str,
    body: str = "",
    category: str = "info",
    link: str | None = None,
    admin_only: bool = False,
) -> InAppNotification | None:
    """Create a single in-app notification for a specific user."""
    try:
        n = InAppNotification(
            workspace_id=workspace_id,
            user_id=user_id,
            title=title,
            body=body,
            category=category,
            link=link,
            admin_only=admin_only,
        )
        db.add(n)
        db.commit()
        db.refresh(n)
        return n
    except Exception:
        db.rollback()
        return None


def notify_admins(
    db: Session,
    workspace_id: int,
    title: str,
    body: str = "",
    category: str = "info",
    link: str | None = None,
) -> int:
    """Create in-app notifications for all active admins in a workspace."""
    try:
        admins = db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == "admin",
            WorkspaceMember.suspended == False,
        ).all()
        count = 0
        for mem in admins:
            db.add(InAppNotification(
                workspace_id=workspace_id,
                user_id=mem.user_id,
                title=title,
                body=body,
                category=category,
                link=link,
                admin_only=True,
            ))
            count += 1
        if count:
            db.commit()
        return count
    except Exception:
        db.rollback()
        return 0


def notify_workspace(
    db: Session,
    workspace_id: int,
    title: str,
    body: str = "",
    category: str = "info",
    link: str | None = None,
) -> int:
    """Create in-app notification for all active members in a workspace."""
    try:
        members = db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.suspended == False,
        ).all()
        count = 0
        for mem in members:
            db.add(InAppNotification(
                workspace_id=workspace_id,
                user_id=mem.user_id,
                title=title,
                body=body,
                category=category,
                link=link,
                admin_only=False,
            ))
            count += 1
        if count:
            db.commit()
        return count
    except Exception:
        db.rollback()
        return 0
