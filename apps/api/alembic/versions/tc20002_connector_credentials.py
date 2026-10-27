"""Connector credential custody columns.

Revision ID: tc20002_connector_credentials
Revises: tc24001_stripe_webhook_events

Parent is the Alembic head on master at implementation time
(tc24001_stripe_webhook_events). Additive and nullable. This module does not
import the application package.
"""

import sqlalchemy as sa

from alembic import op

revision = "tc20002_connector_credentials"
down_revision = "tc24001_stripe_webhook_events"
branch_labels = None
depends_on = None

_TABLE = "credential_store"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("secret_last4", sa.String(length=16), nullable=True))
    op.add_column(_TABLE, sa.Column("secret_fingerprint", sa.String(length=64), nullable=True))
    op.add_column(_TABLE, sa.Column("key_purpose", sa.String(length=64), nullable=True))
    op.add_column(_TABLE, sa.Column("credential_ref", sa.String(length=255), nullable=True))
    op.add_column(_TABLE, sa.Column("encryption_version", sa.String(length=32), nullable=True))
    op.add_column(
        _TABLE,
        sa.Column("destroyed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(_TABLE, sa.Column("external_account_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column(_TABLE, "external_account_id")
    op.drop_column(_TABLE, "destroyed_at")
    op.drop_column(_TABLE, "encryption_version")
    op.drop_column(_TABLE, "credential_ref")
    op.drop_column(_TABLE, "key_purpose")
    op.drop_column(_TABLE, "secret_fingerprint")
    op.drop_column(_TABLE, "secret_last4")
