"""EvidenceGap — tracks identified gaps in evidence coverage."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text

from app.core.database import Base

GAP_STATUSES = ("open", "accepted", "dismissed")


class EvidenceGap(Base):
    __tablename__ = "evidence_gaps"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    questionnaire_id = Column(
        Integer,
        ForeignKey("questionnaires.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    question_id = Column(
        Integer,
        ForeignKey("questions.id", ondelete="SET NULL"),
        nullable=True,
    )
    answer_id = Column(
        Integer,
        ForeignKey("answers.id", ondelete="SET NULL"),
        nullable=True,
    )
    gap_type = Column(String(64), nullable=False, default="missing_evidence")
    reason = Column(Text, nullable=True)
    proposed_policy_addition = Column(Text, nullable=True)
    suggested_evidence_doc_title = Column(String(512), nullable=True)
    confidence = Column(Float, nullable=True)
    status = Column(String(20), nullable=False, default="open", index=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
