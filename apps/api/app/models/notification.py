"""Phase C: Workspace notification policies, delivery log, and per-user unsubscribes."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base


NOTIFICATION_EVENT_TYPES = [
    "compliance.coverage_drop",
    "compliance.blind_spot",
    "compliance.high_insufficient",
    "compliance.weak_evidence",
    "questionnaire.uploaded",
    "questionnaire.generated",
    "export.completed",
    "document.indexed",
    "member.invited",
    "member.joined",
    "member.removed",
    "member.suspended",
    "member.role_changed",
    "role.created",
    "role.updated",
    "role.deleted",
]

RECIPIENT_TYPES = ["all", "admins", "role", "user"]


class NotificationPolicy(Base):
    """Per-workspace policy: which events trigger email notifications and to whom."""

    __tablename__ = "notification_policies"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(64), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    recipient_type = Column(String(32), nullable=False, default="admins")
    recipient_value = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class NotificationLog(Base):
    """Delivery log: every notification attempt with status and error detail."""

    __tablename__ = "notification_log"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    channel = Column(String(16), nullable=False, default="email")
    recipient_email = Column(String(255), nullable=False)
    subject = Column(String(512), nullable=True)
    status = Column(String(16), nullable=False, default="sent")
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class NotificationUnsubscribe(Base):
    """Per-user opt-out from specific event types in a workspace."""

    __tablename__ = "notification_unsubscribes"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
