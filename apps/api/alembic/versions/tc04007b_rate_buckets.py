"""Shared rate-limit buckets (TC-04-007b).

One row per limiter key. ``attempt_count`` and ``window_started`` are the fixed
window previously kept in process memory. Login, reset, resend, invite, and the
other callers of ``app.core.rate_limit`` share these rows across processes when
``REDIS_URL`` is unset.

Downgrade drops the table. Open windows are discarded. Re-upgrade starts empty,
so a caller that was limited can try again until the new window fills.

The revision id is 21 characters and fits ``alembic_version.version_num``
(varchar(32)). ``down_revision`` is the single Alembic head on master when this
file is parented. This revision does not import the application package.

Revision ID: tc04007b_rate_buckets
Revises: tc12004a_answer_revisions
"""

import sqlalchemy as sa
from alembic import op

revision = "tc04007b_rate_buckets"
down_revision = "tc12004a_answer_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_buckets",
        sa.Column("bucket_key", sa.String(length=512), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("window_started", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("bucket_key"),
    )


def downgrade() -> None:
    op.drop_table("rate_limit_buckets")
