"""Typed model outcome and job error codes (TC-11-001)

Additive, nullable columns only. Legacy rows keep NULL (rendered as "no typed outcome").

Revision ID: tc11001_model_outcome_codes
Revises: 075

The revision id is descriptive rather than "076" because another team's TC-25-005 also adds a
migration after 075. Whichever merges second adds an alembic merge revision (or re-points its
down_revision); neither id collides.
"""

import sqlalchemy as sa
from alembic import op

revision = "tc11001_model_outcome_codes"
down_revision = "075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("answers", sa.Column("outcome_code", sa.String(length=64), nullable=True))
    op.add_column("jobs", sa.Column("error_code", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "error_code")
    op.drop_column("answers", "outcome_code")
