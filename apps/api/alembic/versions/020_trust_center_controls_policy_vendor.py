"""Trust Center: controls, evidence linking, policy flag, acknowledgments, vendor requests (TC-R-B2, B3, B5, B6).

Revision ID: 020
Revises: 019
Create Date: 2026-03-14

"""
from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trust_articles", sa.Column("is_policy", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "controls",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("framework", sa.String(64), nullable=False),
        sa.Column("control_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="in_review"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_controls_workspace_framework", "controls", ["workspace_id", "framework"])

    op.create_table(
        "control_evidence",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("control_id", sa.Integer(), sa.ForeignKey("controls.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("trust_article_id", sa.Integer(), sa.ForeignKey("trust_articles.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("export_record_id", sa.Integer(), sa.ForeignKey("export_records.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "policy_acknowledgments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("trust_article_id", sa.Integer(), sa.ForeignKey("trust_articles.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_policy_ack_user_article", "policy_acknowledgments", ["user_id", "trust_article_id"], unique=True)

    op.create_table(
        "vendor_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("vendor_email", sa.String(255), nullable=False),
        sa.Column("questionnaire_id", sa.Integer(), sa.ForeignKey("questionnaires.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="sent"),
        sa.Column("link_token", sa.String(64), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("vendor_requests")
    op.drop_table("policy_acknowledgments")
    op.drop_table("control_evidence")
    op.drop_table("controls")
    op.drop_column("trust_articles", "is_policy")
