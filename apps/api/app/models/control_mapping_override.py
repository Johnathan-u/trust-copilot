"""Phase 2: Manual override of question -> control mapping."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy import JSON

from app.core.database import Base


class ControlMappingOverride(Base):
    __tablename__ = "control_mapping_override"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    question_hash = Column(String(64), nullable=False, index=True)
    override_control_ids = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
