"""Outbound questionnaire requests and durable grant/delivery state."""

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base

VENDOR_REQUEST_STATUSES = ("pending", "in_progress", "completed")


class VendorRequest(Base):
    __tablename__ = "vendor_requests"
    __table_args__ = (
        CheckConstraint(
            "delivery_status IS NULL OR delivery_status IN ('not_sent','sending','accepted','uncertain','unavailable')",
            name="ck_vendor_delivery_status",
        ),
        CheckConstraint(
            "(submitted_at IS NULL AND response_payload IS NULL AND response_digest IS NULL) OR (submitted_at IS NOT NULL AND response_payload IS NOT NULL AND response_digest IS NOT NULL)",
            name="ck_vendor_submission_fields",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vendor_email = Column(String(255), nullable=False)
    questionnaire_id = Column(
        Integer, ForeignKey("questionnaires.id", ondelete="SET NULL"), nullable=True, index=True
    )
    message = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="pending")
    # Legacy grants only. New grants keep the raw bearer token solely in the first response.
    link_token = Column(String(64), nullable=True, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    link_token_hash = Column(String(64), nullable=True, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    delivery_status = Column(String(16), nullable=True)
    last_delivery_at = Column(DateTime(timezone=True), nullable=True)
    last_delivery_error = Column(String(128), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    response_payload = Column(String(20000), nullable=True)
    response_digest = Column(String(64), nullable=True)


class VendorRequestLifecycleHold(Base):
    """Lossless downgrade parking, matching the migration's bounded hold table."""

    __tablename__ = "tc18002_vendor_hold"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=True)
    legacy_fingerprint = Column(String(32), nullable=False)
    legacy_link_token = Column(String(64), nullable=True)
    link_token_hash = Column(String(64), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    delivery_status = Column(String(16), nullable=True)
    last_delivery_at = Column(DateTime(timezone=True), nullable=True)
    last_delivery_error = Column(String(128), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    response_payload = Column(String(20000), nullable=True)
    response_digest = Column(String(64), nullable=True)
