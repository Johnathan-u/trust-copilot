"""Evidence gap model: stores AI-generated gap analysis for insufficient-evidence answers."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text

from app.core.database import Base


class EvidenceGap(Base):
    __tablename__ = "evidence_gaps"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    questionnaire_id = Column(Integer, ForeignKey("questionnaires.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True)
    answer_id = Column(Integer, ForeignKey("answers.id", ondelete="SET NULL"), nullable=True)
    gap_type = Column(String(64), nullable=False)
    reason = Column(Text, nullable=False)
    proposed_policy_addition = Column(Text, nullable=False)
    suggested_evidence_doc_title = Column(String(255), nullable=True)
    confidence = Column(Float, nullable=True)
    status = Column(String(32), default="open", nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


GAP_TYPES = (
    "missing_procedure_detail",
    "missing_control_statement",
    "missing_metric",
    "missing_scope_detail",
    "missing_retention_rule",
    "missing_access_review_detail",
    "other",
)

GAP_STATUSES = ("open", "accepted", "dismissed")
