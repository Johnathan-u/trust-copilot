"""Tag and DocumentTag models for enterprise document/evidence tagging."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)

from app.core.database import Base

TAG_CATEGORIES = ("framework", "topic", "document_type", "custom")
TAG_SOURCES = ("ai", "manual")


class Tag(Base):
    """Global or workspace-scoped tag definition."""

    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(
        Integer,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    category = Column(String(32), nullable=False)
    key = Column(String(64), nullable=False)
    label = Column(String(128), nullable=False)
    is_system = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("workspace_id", "category", "key", name="uq_tags_ws_cat_key"),
    )


class DocumentTag(Base):
    """Association between a document and a tag, with provenance metadata."""

    __tablename__ = "document_tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(
        Integer,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag_id = Column(
        Integer,
        ForeignKey("tags.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source = Column(String(16), nullable=False, default="manual")
    confidence = Column(Float, nullable=True)
    approved = Column(Boolean, nullable=False, default=False, server_default="false")
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("document_id", "tag_id", name="uq_document_tags_doc_tag"),
    )
