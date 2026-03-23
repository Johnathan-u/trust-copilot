"""Workspace-scoped control instances (links to framework control or custom)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.core.database import Base

WORKSPACE_CONTROL_STATUSES = ("not_implemented", "in_progress", "implemented", "verified")


class WorkspaceControl(Base):
    __tablename__ = "workspace_controls"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    framework_control_id = Column(Integer, ForeignKey("framework_controls.id", ondelete="SET NULL"), nullable=True, index=True)
    custom_name = Column(String(255), nullable=True)
    status = Column(String(32), nullable=False, default="not_implemented")
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    owner_team = Column(String(128), nullable=True)
    last_reviewed_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    verified_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
