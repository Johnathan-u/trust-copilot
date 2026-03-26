"""Deal object model (E1-01). Anchors trust activity to revenue."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text

from app.core.database import Base

DEAL_STAGES = ("prospect", "discovery", "evaluation", "negotiation", "closed_won", "closed_lost")


class Deal(Base):
    __tablename__ = "deals"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    company_name = Column(String(255), nullable=False)
    buyer_contact_name = Column(String(255), nullable=True)
    buyer_contact_email = Column(String(255), nullable=True)
    deal_value_arr = Column(Float, nullable=True)
    stage = Column(String(32), nullable=False, default="prospect")
    close_date = Column(DateTime, nullable=True)
    requested_frameworks = Column(Text, nullable=True)  # JSON array
    linked_questionnaire_ids = Column(Text, nullable=True)  # JSON array
    crm_source = Column(String(32), nullable=True)  # salesforce, hubspot, manual
    crm_external_id = Column(String(255), nullable=True)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
