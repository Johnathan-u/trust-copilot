"""In-app notification center: per-user, workspace-scoped notifications with read state."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from app.core.database import Base, utc_now


class InAppNotification(Base):
    __tablename__ = "in_app_notifications"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_in_app_notifications_workspace_id_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=True)
    category = Column(String(32), nullable=False, default="info")
    link = Column(String(512), nullable=True)
    is_read = Column(Boolean, nullable=False, default=False)
    admin_only = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class InAppNotificationReceipt(Base):
    """A member's read timestamp for a legacy workspace broadcast."""

    __tablename__ = "in_app_notification_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "notification_id"],
            ["in_app_notifications.workspace_id", "in_app_notifications.id"],
            name="fk_in_app_receipt_notification_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "user_id"],
            ["workspace_members.workspace_id", "workspace_members.user_id"],
            name="fk_in_app_receipt_member_workspace",
            ondelete="CASCADE",
        ),
    )

    workspace_id = Column(Integer, primary_key=True)
    notification_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, primary_key=True)
    read_at = Column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
