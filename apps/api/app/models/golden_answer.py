"""Golden answer model (P1-71)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text

from app.core.database import Base


class GoldenAnswer(Base):
    __tablename__ = "golden_answers"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    question_text = Column(Text, nullable=False)
    answer_text = Column(Text, nullable=False)
    category = Column(String(128), nullable=True)
    control_ids_json = Column(Text, nullable=True)
    evidence_ids_json = Column(Text, nullable=True)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(32), default="approved", nullable=False)
    confidence = Column(Float, nullable=True)
    review_cycle_days = Column(Integer, nullable=True, default=90)
    last_reviewed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    reuse_count = Column(Integer, default=0, nullable=False)
    source_answer_id = Column(Integer, nullable=True)
    customer_override_for = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
