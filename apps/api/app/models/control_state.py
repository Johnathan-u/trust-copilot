"""Control state snapshot model (P1-34)."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.core.database import Base


class ControlStateSnapshot(Base):
    """Point-in-time snapshot of a control's evaluation status."""

    __tablename__ = "control_state_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    control_id = Column(Integer, ForeignKey("workspace_controls.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(32), nullable=False)
    previous_status = Column(String(32), nullable=True)
    evaluated_by = Column(String(64), nullable=False, default="system")
    evidence_count = Column(Integer, nullable=False, default=0)
    confidence_score = Column(Integer, nullable=True)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
