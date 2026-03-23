"""API key model for machine auth (workspace-scoped bearer tokens)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.core.database import Base


class ApiKey(Base):
    """Workspace-scoped API key for scripts and integrations."""

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    key_hash = Column(String(64), nullable=False, unique=True, index=True)  # SHA-256 hex of the raw key
    label = Column(String(255), nullable=True)
    role = Column(String(32), nullable=False, default="editor")  # editor, reviewer, admin
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
