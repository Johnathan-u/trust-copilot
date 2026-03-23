"""Workspace invite model (AUTH-208)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.core.database import Base


class Invite(Base):
    """Pending workspace invite: email, role, one-time token. Accepted or revoked by delete."""

    __tablename__ = "invites"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    role = Column(String(32), nullable=False)
    token_hash = Column(String(64), nullable=False, index=True)
    # Human-entered code from email; hashed like token. NULL = legacy invite (token-only).
    invite_code_hash = Column(String(64), nullable=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
