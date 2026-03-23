"""Compliance foundation: frameworks, framework_controls, workspace_controls, evidence, mappings.

Revision ID: 030
Revises: 029
Create Date: 2025-01-01 00:30:00

"""
from alembic import op
import sqlalchemy as sa

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "frameworks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("version", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_frameworks_name", "frameworks", ["name"])

    op.create_table(
        "framework_controls",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("framework_id", sa.Integer(), sa.ForeignKey("frameworks.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("control_key", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("criticality", sa.String(16), nullable=False, server_default=sa.text("'medium'")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_framework_controls_control_key", "framework_controls", ["framework_id", "control_key"], unique=True)

    op.create_table(
        "workspace_controls",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("framework_control_id", sa.Integer(), sa.ForeignKey("framework_controls.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("custom_name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'not_implemented'")),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("owner_team", sa.String(128), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_workspace_controls_status", "workspace_controls", ["workspace_id", "status"])

    op.create_table(
        "control_mappings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_control_id", sa.Integer(), sa.ForeignKey("framework_controls.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("target_control_id", sa.Integer(), sa.ForeignKey("framework_controls.id", ondelete="CASCADE"), nullable=False, index=True),
    )

    op.create_table(
        "evidence_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("source_type", sa.String(32), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "control_evidence_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("control_id", sa.Integer(), sa.ForeignKey("workspace_controls.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("evidence_id", sa.Integer(), sa.ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "evidence_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("evidence_id", sa.Integer(), sa.ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_ref", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "evidence_metadata",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("evidence_id", sa.Integer(), sa.ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("freshness_date", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("evidence_metadata")
    op.drop_table("evidence_versions")
    op.drop_table("control_evidence_links")
    op.drop_table("evidence_items")
    op.drop_table("control_mappings")
    op.drop_table("workspace_controls")
    op.drop_table("framework_controls")
    op.drop_table("frameworks")
