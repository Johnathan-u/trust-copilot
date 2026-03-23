"""Answer model (AI-05)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base

ANSWER_STATUSES = ("draft", "approved", "rejected", "flagged", "insufficient_evidence")
GATING_REASONS = (
    "no_evidence",
    "retrieval_noise_floor",
    "weak_control_path",
    "weak_control_path_low_tier",
    "weak_retrieval_no_control",
    "weak_retrieval_low_tier_docs",
)


class Answer(Base):
    """AI-generated or human-edited answer for a question."""

    __tablename__ = "answers"

    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True)
    text = Column(Text, nullable=True)
    status = Column(String(32), default="draft")  # draft, approved, rejected, flagged, insufficient_evidence
    citations = Column(Text, nullable=True)  # JSON: [{chunk_id, snippet}, ...]
    confidence = Column(Integer, nullable=True)
    insufficient_reason = Column(String(64), nullable=True)
    gating_reason = Column(String(64), nullable=True)
    primary_categories_json = Column(Text, nullable=True)  # JSON: {"frameworks": [...], "subjects": [...]}
    evidence_fingerprint = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
