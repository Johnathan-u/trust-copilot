"""NDA-gated access request model (P1-65)."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base

NDA_REQUEST_STATUSES = ("pending", "approved", "rejected", "revoked", "expired")


class NdaAccessRequest(Base):
    __tablename__ = "nda_access_requests"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    requester_name = Column(String(255), nullable=False)
    requester_email = Column(String(255), nullable=False)
    requester_company = Column(String(255), nullable=True)
    purpose = Column(Text, nullable=True)
    nda_accepted = Column(Boolean, default=False, nullable=False)
    nda_accepted_at = Column(DateTime, nullable=True)
    status = Column(String(32), default="pending", nullable=False)
    approved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    access_token = Column(String(255), nullable=True, unique=True, index=True)
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
