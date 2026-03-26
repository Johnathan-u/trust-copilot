"""Operator queue model for internal managed-service workflows."""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)

from app.core.database import Base

OPERATOR_ITEM_STATUSES = ("received", "triaging", "in_progress", "blocked", "review", "delivered", "closed")
OPERATOR_ITEM_PRIORITIES = ("critical", "high", "normal", "low")


class OperatorQueueItem(Base):
    """An item in the internal operator queue representing work to be done."""

    __tablename__ = "operator_queue_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(
        Integer,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    questionnaire_id = Column(
        Integer,
        ForeignKey("questionnaires.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    item_type = Column(String(32), nullable=False, default="questionnaire", index=True)
    status = Column(String(32), nullable=False, default="received", index=True)
    priority = Column(String(16), nullable=False, default="normal")
    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    assignee = Column(String(255), nullable=True)
    customer_name = Column(String(255), nullable=True)
    customer_email = Column(String(255), nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)
    blocked_reason = Column(Text, nullable=True)
    internal_notes = Column(Text, nullable=True)
    questions_total = Column(Integer, nullable=True)
    questions_answered = Column(Integer, nullable=True)
    evidence_gaps = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
