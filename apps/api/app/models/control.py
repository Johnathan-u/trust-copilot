"""Controls and frameworks (TC-R-B2)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.core.database import Base

CONTROL_STATUSES = ("implemented", "in_review", "na")


class Control(Base):
    """Compliance control (e.g. SOC 2 CC6.1) with framework and status."""

    __tablename__ = "controls"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    framework = Column(String(64), nullable=False)
    control_id = Column(String(64), nullable=False)
    name = Column(String(255), nullable=True)
    status = Column(String(32), nullable=False, default="in_review")
    # TC-21-002 canonical pair. Null on rows written before this contract.
    # content_version stays null while TC-01-007 is open.
    canonical_key = Column(String(160), nullable=True)
    content_version = Column(String(32), nullable=True)
    owner_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    owner_team = Column(String(128), nullable=True)
    lifecycle = Column(String(32), nullable=True)
    workspace_control_id = Column(
        Integer, ForeignKey("workspace_controls.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
