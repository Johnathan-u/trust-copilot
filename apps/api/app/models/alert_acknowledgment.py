"""Alert acknowledgement and snooze model (P1-38)."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.core.database import Base


class AlertAcknowledgment(Base):
    """Records acknowledgement, snooze, or accepted risk for an alert/control."""

    __tablename__ = "alert_acknowledgments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    control_id = Column(Integer, nullable=True, index=True)
    alert_type = Column(String(64), nullable=False)
    action = Column(String(32), nullable=False)
    reason = Column(Text, nullable=True)
    snoozed_until = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
