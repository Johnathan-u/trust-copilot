"""Audit row for a framework enablement attempt.

The catalog itself is global. The event records the caller's current workspace
and user so a refusal is attributable. It stores no control text.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base


class FrameworkCatalogEvent(Base):
    __tablename__ = "framework_catalog_events"

    id = Column(Integer, primary_key=True, index=True)
    framework_id = Column(
        Integer, ForeignKey("frameworks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_role = Column(String(32), nullable=True)
    catalog_key = Column(String(64), nullable=True)
    attempted_version = Column(String(32), nullable=True)
    outcome = Column(String(32), nullable=False)
    error_code = Column(String(64), nullable=False)
    contract_version = Column(String(64), nullable=False)
    request_id = Column(String(64), nullable=True)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
