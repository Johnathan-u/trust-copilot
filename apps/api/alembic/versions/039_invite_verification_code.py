"""Add invite_code_hash for email verification step before accept (AUTH-208).

Revision ID: 039
Revises: 038
"""

import sqlalchemy as sa
from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "invites",
        sa.Column("invite_code_hash", sa.String(64), nullable=True),
    )
    op.create_index("ix_invites_invite_code_hash", "invites", ["invite_code_hash"])


def downgrade() -> None:
    op.drop_index("ix_invites_invite_code_hash", table_name="invites")
    op.drop_column("invites", "invite_code_hash")
