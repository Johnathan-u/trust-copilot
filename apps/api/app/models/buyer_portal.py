"""Buyer-facing portal (E4-20..E4-24)."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text

from app.core.database import Base


class BuyerPortal(Base):
    __tablename__ = "buyer_portals"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    portal_token = Column(String(96), nullable=False, unique=True)
    display_name = Column(String(255), nullable=False)
    frameworks_filter_json = Column(Text, nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class BuyerPortalSnapshot(Base):
    __tablename__ = "buyer_portal_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    portal_id = Column(Integer, ForeignKey("buyer_portals.id", ondelete="CASCADE"), nullable=False, index=True)
    snapshot_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class BuyerEscalation(Base):
    __tablename__ = "buyer_escalations"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    portal_id = Column(Integer, ForeignKey("buyer_portals.id", ondelete="SET NULL"), nullable=True)
    buyer_email = Column(String(255), nullable=False)
    escalation_type = Column(String(64), nullable=False)
    question_snippet = Column(Text, nullable=True)
    message = Column(Text, nullable=False)
    answer_id = Column(Integer, nullable=True)
    status = Column(String(32), nullable=False, default="open")
    seller_notes = Column(Text, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class BuyerSatisfactionSignal(Base):
    __tablename__ = "buyer_satisfaction_signals"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    portal_id = Column(Integer, ForeignKey("buyer_portals.id", ondelete="SET NULL"), nullable=True)
    questionnaire_id = Column(Integer, nullable=True)
    accepted_without_edits = Column(Boolean, nullable=True)
    follow_up_count = Column(Integer, nullable=True, default=0)
    cycle_hours = Column(Float, nullable=True)
    deal_closed = Column(Boolean, nullable=True, default=False)
    extra_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class BuyerChangeSubscription(Base):
    __tablename__ = "buyer_change_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    portal_id = Column(Integer, ForeignKey("buyer_portals.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), nullable=False)
    frameworks_json = Column(Text, nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
