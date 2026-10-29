"""EvidenceGap — tracks identified gaps in evidence coverage."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, text

from app.core.database import Base

# Statuses a user can set (API / bulk update). Unchanged by TC-02-BUG-018.
GAP_STATUS_OPEN = "open"
GAP_STATUSES = (GAP_STATUS_OPEN, "accepted", "dismissed")
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
# TC-21-006 scan rows. Several may be open at once, one per control, and the
# writer leaves question_id null. They are not "one open gap per question".
GAP_TYPE_CONTROL_CHECK = "control_check"
# TC-02-BUG-018c. One open gap for a question inside a workspace and questionnaire.
# bug018c_one_open_gap duplicates these literals and does not import this package.
# question_id IS NOT NULL and the control-check type is excluded so scan rows,
# which have no question, are not in the index. questionnaire_id is nullable;
# PostgreSQL does not treat NULL as equal.
UQ_EVIDENCE_GAPS_ONE_OPEN_PER_QUESTION = "uq_evidence_gaps_one_open_per_question"
ONE_OPEN_GAP_INDEX_COLUMNS = ("workspace_id", "questionnaire_id", "question_id")
ONE_OPEN_GAP_INDEX_WHERE = (
    f"status = '{GAP_STATUS_OPEN}' AND question_id IS NOT NULL "
    f"AND gap_type <> '{GAP_TYPE_CONTROL_CHECK}'"
)


class EvidenceGap(Base):
    __tablename__ = "evidence_gaps"
    __table_args__ = (
        Index(
            UQ_EVIDENCE_GAPS_ONE_OPEN_PER_QUESTION,
            *ONE_OPEN_GAP_INDEX_COLUMNS,
            unique=True,
            postgresql_where=text(ONE_OPEN_GAP_INDEX_WHERE),
        ),
    )

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
    status = Column(String(20), nullable=False, default=GAP_STATUS_OPEN, index=True)
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
