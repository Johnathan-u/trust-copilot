"""Evidence linking to controls (TC-R-B3)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer

from app.core.database import Base


class ControlEvidence(Base):
    """Link a document, trust article, or export record to a control."""

    __tablename__ = "control_evidence"

    id = Column(Integer, primary_key=True, index=True)
    control_id = Column(Integer, ForeignKey("controls.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True)
    trust_article_id = Column(Integer, ForeignKey("trust_articles.id", ondelete="CASCADE"), nullable=True, index=True)
    export_record_id = Column(Integer, ForeignKey("export_records.id", ondelete="CASCADE"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
