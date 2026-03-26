"""Shareable space model (P1-66)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, Boolean

from app.core.database import Base


class ShareableSpace(Base):
    __tablename__ = "shareable_spaces"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    buyer_company = Column(String(255), nullable=True)
    buyer_email = Column(String(255), nullable=True)
    opportunity_id = Column(String(128), nullable=True)
    access_token = Column(String(255), nullable=True, unique=True, index=True)
    description = Column(Text, nullable=True)
    article_ids_json = Column(Text, nullable=True)
    answer_ids_json = Column(Text, nullable=True)
    document_ids_json = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
