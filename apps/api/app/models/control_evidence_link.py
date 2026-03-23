"""Link between workspace control and evidence with confidence and verification."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer

from app.core.database import Base


class ControlEvidenceLink(Base):
    __tablename__ = "control_evidence_links"

    id = Column(Integer, primary_key=True, index=True)
    control_id = Column(Integer, ForeignKey("workspace_controls.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_id = Column(Integer, ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=False, index=True)
    confidence_score = Column(Float, nullable=True)
    verified = Column(Boolean, nullable=False, default=False)
    last_verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
