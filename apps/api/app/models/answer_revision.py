"""Draft and superseded revisions of an answer (TC-12-004a).

The approved text stays on ``answers``. A regenerate inserts a row here and
does not update that answer. Approving the draft copies it onto the answer
and keeps the previous text as a superseded revision.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from app.core.database import Base

REVISION_DRAFT = "draft"
REVISION_SUPERSEDED = "superseded"
REVISION_APPLIED = "applied"


class AnswerRevision(Base):
    """One generated or superseded copy of an answer. Not the current approved row."""

    __tablename__ = "answer_revisions"
    __table_args__ = (
        UniqueConstraint("answer_id", "revision_number", name="uq_answer_revisions_answer_number"),
    )

    id = Column(Integer, primary_key=True, index=True)
    answer_id = Column(
        Integer, ForeignKey("answers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id = Column(
        Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_number = Column(Integer, nullable=False)
    text = Column(Text, nullable=True)
    citations = Column(Text, nullable=True)
    confidence = Column(Integer, nullable=True)
    insufficient_reason = Column(String(64), nullable=True)
    gating_reason = Column(String(64), nullable=True)
    primary_categories_json = Column(Text, nullable=True)
    evidence_fingerprint = Column(String(64), nullable=True)
    outcome_code = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False, default=REVISION_DRAFT)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
