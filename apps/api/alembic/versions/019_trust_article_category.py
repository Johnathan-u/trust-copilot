"""Trust article category/section (TC-R-B1).

Revision ID: 019
Revises: 018
Create Date: 2026-03-14

"""
from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trust_articles", sa.Column("category", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("trust_articles", "category")
