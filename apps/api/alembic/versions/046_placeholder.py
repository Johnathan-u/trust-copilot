"""Placeholder migration to fix chain (046 was missing)."""

from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401


revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
