"""Chunk model for document embeddings."""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSON

from app.core.database import Base


class Chunk(Base):
    """Document chunk with optional embedding for semantic search."""

    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=True)
    text = Column(Text, nullable=False)
    metadata_ = Column("metadata_", JSON, nullable=True)
    embedding = Column(Vector(1536), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
