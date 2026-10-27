"""Typed model outcome and job error codes (TC-11-001)

Additive, nullable columns only. Legacy rows keep NULL (rendered as "no typed outcome").

Revision ID: 076
Revises: 075
"""

import sqlalchemy as sa
from alembic import op

revision = "076"
down_revision = "075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("answers", sa.Column("outcome_code", sa.String(length=64), nullable=True))
    op.add_column("jobs", sa.Column("error_code", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "error_code")
    op.drop_column("answers", "outcome_code")
