"""Add evidence_fingerprint to answers table."""

from alembic import op
import sqlalchemy as sa


revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("answers", sa.Column("evidence_fingerprint", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("answers", "evidence_fingerprint")
