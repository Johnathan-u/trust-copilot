"""Custom workspace roles with configurable permission matrix (Phase B)."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String

from app.core.database import Base


class CustomRole(Base):
    """Per-workspace custom role with granular permissions."""

    __tablename__ = "custom_roles"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    description = Column(String(255), nullable=True)
    can_edit = Column(Boolean, nullable=False, default=False)
    can_review = Column(Boolean, nullable=False, default=True)
    can_export = Column(Boolean, nullable=False, default=False)
    can_admin = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
