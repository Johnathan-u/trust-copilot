"""Persistent audit log for auth and access (AUD-201)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.core.database import Base


class AuditEvent(Base):
    """Database-backed audit events for login, logout, workspace switch, etc."""

    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, index=True)
    occurred_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    action = Column(String(64), nullable=False, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    email = Column(String(255), nullable=True, index=True)
    workspace_id = Column(Integer, nullable=True, index=True)
    resource_type = Column(String(64), nullable=True)
    resource_id = Column(String(128), nullable=True)
    details = Column(Text, nullable=True)  # JSON or free text
