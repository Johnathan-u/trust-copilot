"""AI mapping and governance tables.

Revision ID: 037
Revises: 036
"""
import sqlalchemy as sa
from alembic import op

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "framework_control_mappings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("framework_key", sa.String(128), nullable=False),
        sa.Column("control_id", sa.Integer, sa.ForeignKey("workspace_controls.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("approved", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_by_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "framework_key", "control_id", name="uq_fcm_ws_fk_ctrl"),
    )

    op.create_table(
        "control_evidence_mappings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("control_id", sa.Integer, sa.ForeignKey("workspace_controls.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("evidence_id", sa.Integer, sa.ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("approved", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("override_priority", sa.Integer, nullable=True),
        sa.Column("created_by_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "control_id", "evidence_id", name="uq_cem_ws_ctrl_ev"),
    )

    op.create_table(
        "evidence_tag_mappings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("evidence_id", sa.Integer, sa.ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("tag_id", sa.Integer, sa.ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("approved", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_by_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "evidence_id", "tag_id", name="uq_etm_ws_ev_tag"),
    )

    op.create_table(
        "question_mapping_preferences",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("questionnaire_id", sa.Integer, sa.ForeignKey("questionnaires.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("question_id", sa.Integer, sa.ForeignKey("questions.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("normalized_question_text", sa.Text, nullable=True),
        sa.Column("preferred_control_id", sa.Integer, sa.ForeignKey("workspace_controls.id", ondelete="SET NULL"), nullable=True),
        sa.Column("preferred_tag_id", sa.Integer, sa.ForeignKey("tags.id", ondelete="SET NULL"), nullable=True),
        sa.Column("preferred_framework_key", sa.String(128), nullable=True),
        sa.Column("weight", sa.Float, nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("approved", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_by_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "ai_governance_settings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, unique=True, index=True),
        sa.Column("require_approved_mappings", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("require_approved_ai_tags", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("minimum_ai_mapping_confidence", sa.Float, nullable=True),
        sa.Column("minimum_ai_tag_confidence", sa.Float, nullable=True),
        sa.Column("manual_mapping_boost", sa.Float, nullable=False, server_default=sa.text("0.05")),
        sa.Column("approved_mapping_boost", sa.Float, nullable=False, server_default=sa.text("0.04")),
        sa.Column("approved_tag_boost", sa.Float, nullable=False, server_default=sa.text("0.03")),
        sa.Column("control_match_boost", sa.Float, nullable=False, server_default=sa.text("0.04")),
        sa.Column("framework_match_boost", sa.Float, nullable=False, server_default=sa.text("0.03")),
        sa.Column("allow_ai_unapproved_for_retrieval", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("allow_manual_overrides", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ai_governance_settings")
    op.drop_table("question_mapping_preferences")
    op.drop_table("evidence_tag_mappings")
    op.drop_table("control_evidence_mappings")
    op.drop_table("framework_control_mappings")
