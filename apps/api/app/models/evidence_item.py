"""Evidence items (manual, document, AI, integration, slack)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base

EVIDENCE_SOURCE_TYPES = ("manual", "document", "ai", "integration", "slack", "gmail")
EVIDENCE_APPROVAL_STATUSES = ("pending", "approved", "rejected")


class EvidenceItem(Base):
    __tablename__ = "evidence_items"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True)
    source_type = Column(String(32), nullable=False, default="manual")
    title = Column(String(512), nullable=False)
    source_metadata = Column(Text, nullable=True)
    approval_status = Column(String(32), nullable=True, default="pending")
    approved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
