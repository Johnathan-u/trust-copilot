"""Typed model outcome and job error codes (TC-11-001)

Additive, nullable columns only. Legacy rows keep NULL (rendered as "no typed outcome").

Adds answers.outcome_code and jobs.error_code. TC-21-001's framework_catalog_events.error_code
is a different table, so these columns do not collide with that revision.

Revision ID: tc11001_model_outcome_codes
Revises: tc21001_framework_catalog_rights

The revision id is descriptive rather than "076" so it does not collide with another migration
that also follows 075. This revision is parented on master's head after TC-21-001.
"""

import sqlalchemy as sa
from alembic import op

revision = "tc11001_model_outcome_codes"
down_revision = "tc21001_framework_catalog_rights"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("answers", sa.Column("outcome_code", sa.String(length=64), nullable=True))
    op.add_column("jobs", sa.Column("error_code", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "error_code")
    op.drop_column("answers", "outcome_code")
