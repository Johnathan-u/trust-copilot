"""EvidenceGap — tracks identified gaps in evidence coverage."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text

from app.core.database import Base

# Statuses a user can set (API / bulk update). Unchanged by TC-02-BUG-018.
GAP_STATUSES = ("open", "accepted", "dismissed")
# System-only status (TC-02-BUG-018): regeneration closed the gap because its question was removed
# or now has a sufficient answer (not insufficient, rejected or flagged). Never set by a user, never
# deleted. A later insufficient answer opens a new gap instead of reopening this row, so the history
# stays readable. No API route sets a resolved row back to open. Closing (TC-02-BUG-018a) writes
# ``closed_at`` and ``close_reason`` (``question_removed`` or ``answer_sufficient``) and leaves
# ``reason`` unchanged. Rows closed before that migration may still carry a final line
# ``[resolved on regeneration: <code> at <UTC ISO-8601>Z]``; the migration copies it onto the
# columns and does not strip it. Manual status changes do not write these columns.
# User- and buyer-facing gap totals must exclude this status and, where all statuses are shown,
# report it separately.
GAP_STATUS_RESOLVED = "resolved"
ALL_GAP_STATUSES = GAP_STATUSES + (GAP_STATUS_RESOLVED,)


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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    # TC-02-BUG-018a. Null until regeneration closes the row. Nullable on purpose: open,
    # accepted and dismissed rows have no closure, and manual status changes do not fill these.
    closed_at = Column(DateTime(timezone=True), nullable=True)
    close_reason = Column(String(32), nullable=True)
    # TC-21-006 control-scan rows (gap_type control_check). Null on questionnaire gaps.
    control_id = Column(Integer, nullable=True, index=True)
    evaluation_state = Column(String(16), nullable=True)
    rule_code = Column(String(64), nullable=True)
    evidence_refs = Column(Text, nullable=True)
    next_action = Column(String(64), nullable=True)
    owner_user_id = Column(Integer, nullable=True)
