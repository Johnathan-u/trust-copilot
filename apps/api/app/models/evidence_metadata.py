"""Evidence metadata (freshness, expiry, verification)."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer

from app.core.database import Base


class EvidenceMetadata(Base):
    __tablename__ = "evidence_metadata"

    id = Column(Integer, primary_key=True, index=True)
    evidence_id = Column(Integer, ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=False, index=True)
    freshness_date = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    last_verified_at = Column(DateTime, nullable=True)
