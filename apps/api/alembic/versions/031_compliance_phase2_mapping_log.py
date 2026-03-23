"""Phase 2: question-control mapping log and manual overrides. No changes to Phase 1 tables."""

from alembic import op
import sqlalchemy as sa

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "question_control_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("question_text", sa.Text(), nullable=True),
        sa.Column("question_hash", sa.String(64), nullable=False, index=True),
        sa.Column("control_ids", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_question_control_log_workspace_hash", "question_control_log", ["workspace_id", "question_hash"])

    op.create_table(
        "control_mapping_override",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("question_hash", sa.String(64), nullable=False, index=True),
        sa.Column("override_control_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_control_mapping_override_workspace_hash", "control_mapping_override", ["workspace_id", "question_hash"], unique=True)


def downgrade() -> None:
    op.drop_table("control_mapping_override")
    op.drop_table("question_control_log")
