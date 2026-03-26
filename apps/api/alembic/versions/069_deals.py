"""deals table

Revision ID: 069
Revises: 068
"""
from alembic import op
import sqlalchemy as sa

revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("buyer_contact_name", sa.String(255), nullable=True),
        sa.Column("buyer_contact_email", sa.String(255), nullable=True),
        sa.Column("deal_value_arr", sa.Float(), nullable=True),
        sa.Column("stage", sa.String(32), nullable=False, server_default="prospect"),
        sa.Column("close_date", sa.DateTime(), nullable=True),
        sa.Column("requested_frameworks", sa.Text(), nullable=True),
        sa.Column("linked_questionnaire_ids", sa.Text(), nullable=True),
        sa.Column("crm_source", sa.String(32), nullable=True),
        sa.Column("crm_external_id", sa.String(255), nullable=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("deals")
