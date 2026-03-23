"""Trust request internal note or reply (TC-H-B2)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base

NOTE_TYPE_INTERNAL = "internal_note"
NOTE_TYPE_REPLY = "reply"
TRUST_REQUEST_NOTE_TYPES = (NOTE_TYPE_INTERNAL, NOTE_TYPE_REPLY)


class TrustRequestNote(Base):
    """Internal note or reply on a trust request."""

    __tablename__ = "trust_request_notes"

    id = Column(Integer, primary_key=True, index=True)
    trust_request_id = Column(Integer, ForeignKey("trust_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note_type = Column(String(32), nullable=False, default=NOTE_TYPE_INTERNAL)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
