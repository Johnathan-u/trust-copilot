"""Create credit_ledgers and credit_transactions tables.

Revision ID: 053
Revises: 052
"""

from alembic import op
import sqlalchemy as sa

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect

    bind = op.get_bind()
    existing = sa_inspect(bind).get_table_names()

    if "credit_ledgers" not in existing:
        op.create_table(
            "credit_ledgers",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, unique=True, index=True),
            sa.Column("balance", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("monthly_allocation", sa.Integer(), nullable=False, server_default="15"),
            sa.Column("cycle_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cycle_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "credit_transactions" not in existing:
        op.create_table(
            "credit_transactions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("kind", sa.String(32), nullable=False, index=True),
            sa.Column("amount", sa.Integer(), nullable=False),
            sa.Column("balance_after", sa.Integer(), nullable=False),
            sa.Column("questionnaire_id", sa.Integer(), sa.ForeignKey("questionnaires.id", ondelete="SET NULL"), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def downgrade() -> None:
    op.drop_table("credit_transactions")
    op.drop_table("credit_ledgers")
