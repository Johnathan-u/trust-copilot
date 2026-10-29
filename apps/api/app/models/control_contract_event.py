"""Audit row for a canonical control pairing. Not a framework catalog."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.core.database import Base


class ControlContractEvent(Base):
    __tablename__ = "control_contract_events"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    legacy_control_id = Column(
        Integer, ForeignKey("controls.id", ondelete="SET NULL"), nullable=True, index=True
    )
    workspace_control_id = Column(
        Integer,
        ForeignKey("workspace_controls.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    canonical_key = Column(String(160), nullable=False)
    lifecycle = Column(String(32), nullable=False)
    request_id = Column(String(64), nullable=True)
    outcome = Column(String(32), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
