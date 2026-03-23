"""MFA models (AUTH-211, AUTH-212): TOTP and recovery codes."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String

from app.core.database import Base


class UserMfa(Base):
    """User TOTP MFA state. Secret stored encrypted."""

    __tablename__ = "user_mfa"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    totp_secret_encrypted = Column(String(512), nullable=False)
    enabled = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MfaRecoveryCode(Base):
    """Hashed recovery codes; one-time use (AUTH-212)."""

    __tablename__ = "mfa_recovery_codes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    code_hash = Column(String(64), nullable=False, index=True)
    used_at = Column(DateTime, nullable=True)


class MfaLoginToken(Base):
    """Short-lived token after password success when MFA required; exchanged for session."""

    __tablename__ = "mfa_login_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token_hash = Column(String(64), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(32), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
