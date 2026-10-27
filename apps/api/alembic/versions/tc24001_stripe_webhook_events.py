"""Stripe webhook replay store and subscription event watermarks.

Revision ID: tc24001_stripe_webhook_events
Revises: tc11001_model_outcome_codes

Master's Alembic head is tc11001_model_outcome_codes. This revision
re-parents onto that head only. Sibling revisions tc25005 and tc10003
also sit on 075 and are not parents of this revision.
"""

import sqlalchemy as sa

from alembic import op

# Frozen snapshot of the table definitions and constants this revision needs.
# Intentionally duplicated so later app changes cannot break upgrade or downgrade.
# This module must not import the application package.

revision = "tc24001_stripe_webhook_events"
down_revision = "tc11001_model_outcome_codes"
branch_labels = None
depends_on = None

_SUBSCRIPTIONS = "subscriptions"
_EVENTS = "stripe_webhook_events"
_EVENT_ID_UNIQUE = "uq_stripe_webhook_events_event_id"
_IX_PROCESSED_AT = "ix_stripe_webhook_events_processed_at"
_IX_OBJECT_ID = "ix_stripe_webhook_events_stripe_object_id"
_STRIPE_ID_LEN = 255
_EVENT_TYPE_LEN = 128
_OUTCOME_LEN = 32


def upgrade() -> None:
    op.add_column(
        _SUBSCRIPTIONS,
        sa.Column("stripe_event_created", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        _SUBSCRIPTIONS,
        sa.Column("stripe_event_type", sa.String(length=_EVENT_TYPE_LEN), nullable=True),
    )
    op.add_column(
        _SUBSCRIPTIONS,
        sa.Column("stripe_terminal_event_created", sa.BigInteger(), nullable=True),
    )
    op.create_table(
        _EVENTS,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stripe_event_id", sa.String(length=_STRIPE_ID_LEN), nullable=False),
        sa.Column("event_type", sa.String(length=_EVENT_TYPE_LEN), nullable=False),
        sa.Column("livemode", sa.Boolean(), nullable=False),
        sa.Column("stripe_created", sa.BigInteger(), nullable=False),
        sa.Column("stripe_object_id", sa.String(length=_STRIPE_ID_LEN), nullable=True),
        sa.Column("outcome", sa.String(length=_OUTCOME_LEN), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("stripe_event_id", name=_EVENT_ID_UNIQUE),
    )
    op.create_index(_IX_PROCESSED_AT, _EVENTS, ["processed_at"])
    op.create_index(_IX_OBJECT_ID, _EVENTS, ["stripe_object_id"])


def downgrade() -> None:
    op.drop_index(_IX_OBJECT_ID, table_name=_EVENTS)
    op.drop_index(_IX_PROCESSED_AT, table_name=_EVENTS)
    op.drop_table(_EVENTS)
    op.drop_column(_SUBSCRIPTIONS, "stripe_terminal_event_created")
    op.drop_column(_SUBSCRIPTIONS, "stripe_event_type")
    op.drop_column(_SUBSCRIPTIONS, "stripe_event_created")
