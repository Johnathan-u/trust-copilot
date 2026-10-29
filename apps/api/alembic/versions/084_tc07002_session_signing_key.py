"""Record which session key id signed a stored session (TC-07-002).

Nullable. Existing rows stay null and keep working with unprefixed cookies.
Downgrade drops the column only.

Revision ID: tc07002_session_key_id
Revises: tc10001_job_leases
"""

import sqlalchemy as sa
from alembic import op

revision = "tc07002_session_key_id"
down_revision = "tc10001_job_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_sessions",
        sa.Column("signing_key_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_sessions", "signing_key_id")
