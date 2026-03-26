"""Answer approval workflow events (P1-72)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base


class AnswerApprovalEvent(Base):
    __tablename__ = "answer_approval_events"

    id = Column(Integer, primary_key=True, index=True)
    golden_answer_id = Column(Integer, ForeignKey("golden_answers.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(32), nullable=False)  # submitted, approved, rejected, changes_requested, owner_assigned, reviewer_assigned
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
