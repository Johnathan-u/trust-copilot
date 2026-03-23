"""Trust request schema (TC-04)."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base


def _utc_now():
    return datetime.now(timezone.utc)


class TrustRequest(Base):
    """Inbound trust information request from prospects/customers."""

    __tablename__ = "trust_requests"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    assignee_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    requester_email = Column(String(255), nullable=False)
    requester_name = Column(String(255), nullable=True)
    subject = Column(String(255), nullable=True)
    message = Column(Text, nullable=False)
    display_id = Column(String(32), nullable=True, index=True)
    frameworks_json = Column(Text, nullable=True)
    subject_areas_json = Column(Text, nullable=True)
    status = Column(String(32), default="new")
    attachment_filename = Column(String(255), nullable=True)
    attachment_storage_key = Column(String(512), nullable=True)
    attachment_size = Column(Integer, nullable=True)
    submitted_host = Column(String(255), nullable=True)
    submitted_path = Column(String(255), nullable=True)
    resolution_method = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=_utc_now)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now)
    deleted_at = Column(DateTime, nullable=True, index=True)
    deleted_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
