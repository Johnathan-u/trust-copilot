"""Phase 2: Log of question -> control_ids for reuse."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy import JSON

from app.core.database import Base


class QuestionControlLog(Base):
    __tablename__ = "question_control_log"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    question_text = Column(Text, nullable=True)
    question_hash = Column(String(64), nullable=False, index=True)
    control_ids = Column(JSON, nullable=False)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
