"""Subscription model for Stripe billing."""

from sqlalchemy import BigInteger, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base


class Subscription(Base):
    """Tracks Stripe subscription state per workspace."""

    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False)
    stripe_customer_id = Column(String(255), nullable=False, index=True)
    stripe_subscription_id = Column(String(255), nullable=True, unique=True, index=True)
    status = Column(String(50), nullable=False, default="incomplete")
    plan = Column(String(50), nullable=False, default="pro")
    current_period_start = Column(DateTime(timezone=True), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end = Column(Integer, nullable=False, default=0)
    # Newest applied Stripe event. Ordering rule: app.services.billing_provider.
    stripe_event_created = Column(BigInteger, nullable=True)
    stripe_event_type = Column(String(128), nullable=True)
    # Set when customer.subscription.deleted has been applied for this id.
    stripe_terminal_event_created = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
