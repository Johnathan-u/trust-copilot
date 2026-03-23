"""Trust articles schema (TC-01)."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base


class TrustArticle(Base):
    """Security/compliance content for Trust Center."""

    __tablename__ = "trust_articles"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True)
    slug = Column(String(128), nullable=False, unique=True, index=True)
    category = Column(String(64), nullable=True)  # TC-R-B1: section for dashboard/public layout
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=True)
    published = Column(Integer, default=1)
    is_policy = Column(Boolean, default=False, nullable=False)  # TC-R-B5
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
