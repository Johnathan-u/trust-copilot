"""EvidenceGap — tracks identified gaps in evidence coverage."""

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, Float, ForeignKey, Integer, String, Text

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
# A control-check row closes because qualifying evidence now exists.
# This is not answer_sufficient, which means a questionnaire answer became sufficient.
CONTROL_CHECK_CLOSE_REASON = "evidence_sufficient"
# Codes stored on close_reason. NULL is also stored: a new gap has no closure,
# and the 018a backfill leaves NULL when a resolved row has no parseable note.
GAP_CLOSE_REASON_QUESTION_REMOVED = "question_removed"
GAP_CLOSE_REASON_ANSWER_SUFFICIENT = "answer_sufficient"
GAP_CLOSE_REASON_EVIDENCE_SUFFICIENT = CONTROL_CHECK_CLOSE_REASON
GAP_CLOSE_REASONS = (
    GAP_CLOSE_REASON_QUESTION_REMOVED,
    GAP_CLOSE_REASON_ANSWER_SUFFICIENT,
    GAP_CLOSE_REASON_EVIDENCE_SUFFICIENT,
)

CK_EVIDENCE_GAPS_STATUS = "ck_evidence_gaps_status"
CK_EVIDENCE_GAPS_CLOSE_REASON = "ck_evidence_gaps_close_reason"


def _sql_in(column: str, values: tuple[str, ...]) -> str:
    literals = ", ".join("'" + value + "'" for value in values)
    return f"{column} IN ({literals})"


# Same text as bug018b_gap_status_checks. A check that close_reason is set only when
# status is resolved is intentionally absent: manual status changes leave close_reason
# in place, and some resolved rows have a NULL close_reason.
STATUS_CHECK_SQL = _sql_in("status", ALL_GAP_STATUSES)
CLOSE_REASON_CHECK_SQL = "close_reason IS NULL OR " + _sql_in("close_reason", GAP_CLOSE_REASONS)


class EvidenceGap(Base):
    __tablename__ = "evidence_gaps"
    __table_args__ = (
        CheckConstraint(STATUS_CHECK_SQL, name=CK_EVIDENCE_GAPS_STATUS),
        CheckConstraint(CLOSE_REASON_CHECK_SQL, name=CK_EVIDENCE_GAPS_CLOSE_REASON),
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
