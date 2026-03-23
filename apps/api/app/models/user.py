"""User model for auth."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String

from app.core.database import Base, utc_now


class User(Base):
    """User for session-based auth."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=True)
    email_verified = Column(Boolean, default=False, nullable=False)  # AUTH-207
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class WorkspaceMember(Base):
    """User membership in workspaces with role."""

    __tablename__ = "workspace_members"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(32), nullable=False)
    suspended = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utc_now)
