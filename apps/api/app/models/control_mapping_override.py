"""Phase 2: Manual override of question -> control mapping.

TC-21-005 adds the current version (state, rationale, reviewer, timestamp)
and an append-only history of prior versions.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import JSON

from app.core.database import Base

MAPPING_STATES = ("proposed", "confirmed", "overridden")


class ControlMappingOverride(Base):
    __tablename__ = "control_mapping_override"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_hash = Column(String(64), nullable=False, index=True)
    override_control_ids = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    state = Column(String(32), nullable=False, default="overridden")
    rationale = Column(Text, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    reviewed_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewed_at = Column(DateTime, nullable=True)


class ControlMappingHistory(Base):
    """Append-only snapshot of a mapping version. Rollback reads the latest row."""

    __tablename__ = "tc21005_mapping_history"

    id = Column(Integer, primary_key=True, index=True)
    mapping_id = Column(
        Integer,
        ForeignKey("control_mapping_override.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = Column(Integer, nullable=False)
    workspace_id = Column(Integer, nullable=False)
    question_hash = Column(String(64), nullable=False)
    control_ids = Column(JSON, nullable=False)
    state = Column(String(32), nullable=False)
    rationale = Column(Text, nullable=True)
    reviewed_by_user_id = Column(Integer, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow, nullable=False)
