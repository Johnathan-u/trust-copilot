"""Processed Stripe webhook events, one row per Stripe event id."""

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database import Base


class StripeWebhookEvent(Base):
    """Idempotency row for a verified Stripe event.

    stripe_event_id is unique so a replay, including a concurrent duplicate,
    cannot insert a second row. Retention deletes old rows; the subscription
    watermark that prevents state regression lives on subscriptions and is
    not pruned with this table.
    """

    __tablename__ = "stripe_webhook_events"
    __table_args__ = (
        UniqueConstraint("stripe_event_id", name="uq_stripe_webhook_events_event_id"),
    )

    id = Column(Integer, primary_key=True)
    stripe_event_id = Column(String(255), nullable=False)
    event_type = Column(String(128), nullable=False)
    livemode = Column(Boolean, nullable=False)
    stripe_created = Column(BigInteger, nullable=False)
    stripe_object_id = Column(String(255), nullable=True, index=True)
    outcome = Column(String(32), nullable=False)
    processed_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
