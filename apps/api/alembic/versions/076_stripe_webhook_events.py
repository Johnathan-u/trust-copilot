"""Stripe webhook replay store and subscription event watermarks.

Revision ID: 076
Revises: 075

Parent revision is 075. Whoever merges a second migration that also revises
075 re-parents down_revision before landing.
"""

import sqlalchemy as sa

from alembic import op

revision = "076"
down_revision = "075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("stripe_event_created", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "subscriptions",
        sa.Column("stripe_event_type", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "subscriptions",
        sa.Column("stripe_terminal_event_created", sa.BigInteger(), nullable=True),
    )
    op.create_table(
        "stripe_webhook_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stripe_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("livemode", sa.Boolean(), nullable=False),
        sa.Column("stripe_created", sa.BigInteger(), nullable=False),
        sa.Column("stripe_object_id", sa.String(length=255), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("stripe_event_id", name="uq_stripe_webhook_events_event_id"),
    )
    op.create_index(
        "ix_stripe_webhook_events_processed_at",
        "stripe_webhook_events",
        ["processed_at"],
    )
    op.create_index(
        "ix_stripe_webhook_events_stripe_object_id",
        "stripe_webhook_events",
        ["stripe_object_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_stripe_webhook_events_stripe_object_id",
        table_name="stripe_webhook_events",
    )
    op.drop_index(
        "ix_stripe_webhook_events_processed_at",
        table_name="stripe_webhook_events",
    )
    op.drop_table("stripe_webhook_events")
    op.drop_column("subscriptions", "stripe_terminal_event_created")
    op.drop_column("subscriptions", "stripe_event_type")
    op.drop_column("subscriptions", "stripe_event_created")
