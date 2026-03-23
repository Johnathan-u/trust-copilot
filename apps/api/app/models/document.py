"""Document model (DOC-01)."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base


def _utc_now():
    return datetime.now(timezone.utc)


class Document(Base):
    """Uploaded file tracked as a domain record."""

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    storage_key = Column(String(512), nullable=False)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(128), nullable=True)
    display_id = Column(String(32), nullable=True, index=True)
    frameworks_json = Column(Text, nullable=True)
    subject_areas_json = Column(Text, nullable=True)
    status = Column(String(32), default="uploaded")
    index_error = Column(String(512), nullable=True)
    metadata_ = Column("metadata", Text, nullable=True)
    created_at = Column(DateTime, default=_utc_now)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now)
    deleted_at = Column(DateTime, nullable=True, index=True)
    deleted_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
