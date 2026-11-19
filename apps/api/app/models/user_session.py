"""Stored user sessions for list/revoke (AUTH-213)."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, false

from app.core.database import Base


class UserSession(Base):
    """Active session row; session_id is in signed cookie."""

    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(String(64), nullable=False, unique=True, index=True)
    signing_key_id = Column(String(64), nullable=True)
    user_agent = Column(String(512), nullable=True)
    ip_address = Column(String(64), nullable=True)
    # False for every session that has not completed an MFA challenge, including
    # rows created before the column existed. Switch treats that as not satisfied.
    mfa_satisfied = Column(Boolean, nullable=False, default=False, server_default=false())
    created_at = Column(DateTime, default=datetime.utcnow)
