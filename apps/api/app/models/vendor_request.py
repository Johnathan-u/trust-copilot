"""Vendor risk: send questionnaire to vendor (TC-R-B6)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.core.database import Base

VENDOR_REQUEST_STATUSES = ("sent", "responded", "expired")


class VendorRequest(Base):
    """Request sent to a vendor (email + optional questionnaire link)."""

    __tablename__ = "vendor_requests"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    vendor_email = Column(String(255), nullable=False)
    questionnaire_id = Column(Integer, ForeignKey("questionnaires.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(32), nullable=False, default="sent")
    link_token = Column(String(64), nullable=True, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
