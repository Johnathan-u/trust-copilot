"""Trust request internal note or reply (TC-H-B2)."""

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base

NOTE_TYPE_INTERNAL = "internal_note"
NOTE_TYPE_REPLY = "reply"
TRUST_REQUEST_NOTE_TYPES = (NOTE_TYPE_INTERNAL, NOTE_TYPE_REPLY)


class TrustRequestNote(Base):
    """Internal note or reply on a trust request."""

    __tablename__ = "trust_request_notes"

    __table_args__ = (
        CheckConstraint(
            "body_revision IS NULL OR (body_revision >= 1 AND body_revision <= 1000000 AND char_length(body) <= 10000)",
            name="ck_trust_reply_body_revision",
        ),
        CheckConstraint(
            "approved_revision IS NULL OR (body_revision IS NOT NULL AND approved_revision >= 1 AND approved_revision = body_revision)",
            name="ck_trust_reply_approved_revision",
        ),
        CheckConstraint(
            "delivery_status IS NULL OR delivery_status IN ('draft','approved','sending','accepted','uncertain','unavailable')",
            name="ck_trust_reply_delivery_status",
        ),
        CheckConstraint(
            "delivery_attempts IS NULL OR (delivery_attempts >= 0 AND delivery_attempts <= 10)",
            name="ck_trust_reply_delivery_attempts",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    trust_request_id = Column(
        Integer, ForeignKey("trust_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note_type = Column(String(32), nullable=False, default=NOTE_TYPE_INTERNAL)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    body_revision = Column(Integer, nullable=True)
    approved_revision = Column(Integer, nullable=True)
    approved_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL", name="fk_trust_reply_approved_by"),
        nullable=True,
        index=True,
    )
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approved_body_hash = Column(String(64), nullable=True)
    delivery_status = Column(String(24), nullable=True)
    delivery_attempts = Column(Integer, nullable=True)
    delivery_started_at = Column(DateTime(timezone=True), nullable=True)
    delivery_accepted_at = Column(DateTime(timezone=True), nullable=True)
    delivery_error = Column(String(128), nullable=True)
