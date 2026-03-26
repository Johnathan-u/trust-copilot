"""Per-delivery outcome metadata for questionnaire answers (E6-31)."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text

from app.core.database import Base

OUTCOME_CHANNELS = ("manual", "buyer_portal", "export", "api")


class AnswerDeliveryOutcome(Base):
    __tablename__ = "answer_delivery_outcomes"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    answer_id = Column(Integer, ForeignKey("answers.id", ondelete="CASCADE"), nullable=False, index=True)
    questionnaire_id = Column(
        Integer, ForeignKey("questionnaires.id", ondelete="SET NULL"), nullable=True, index=True
    )
    deal_id = Column(Integer, ForeignKey("deals.id", ondelete="SET NULL"), nullable=True, index=True)
    golden_answer_id = Column(
        Integer, ForeignKey("golden_answers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    accepted_without_edits = Column(Boolean, nullable=True)
    was_edited = Column(Boolean, nullable=True)
    edit_diff_json = Column(Text, nullable=True)
    follow_up_requested = Column(Boolean, nullable=True)
    buyer_pushback = Column(Boolean, nullable=True)
    deal_closed = Column(Boolean, nullable=True)
    review_cycle_hours = Column(Float, nullable=True)
    channel = Column(String(32), nullable=False, default="manual")
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
