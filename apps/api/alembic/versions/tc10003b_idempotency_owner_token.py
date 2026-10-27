"""TC-10-003b: owner token on idempotency claims.

Adds, additively, ``idempotency_keys.owner_token`` (nullable String(64)). ``claim`` writes a random token on
insert and on reclaim of an expired row; ``set``/``release`` called with ``owner=`` only touch the row while it
still carries that token, so a late finisher whose 60s lease expired cannot free or overwrite the claim of the
request that reclaimed the key.

Nullable, no backfill: rows written before this migration have NULL and are only reachable by ``owner=None``
set/release, which is the old behavior. Plain ADD COLUMN without a default is a metadata-only change on
Postgres (no table rewrite).

Revision ID: tc10003b_idempotency_owner_token
Revises: tc24001_stripe_webhook_events
"""

from alembic import op
import sqlalchemy as sa

revision = "tc10003b_idempotency_owner_token"
down_revision = "tc24001_stripe_webhook_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("idempotency_keys", sa.Column("owner_token", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("idempotency_keys", "owner_token")
