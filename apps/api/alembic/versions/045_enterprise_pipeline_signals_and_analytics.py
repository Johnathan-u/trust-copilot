"""Enterprise AI pipeline: question mapping signals, answer outcome fields, workspace usage tracking."""

from alembic import op
import sqlalchemy as sa


revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "question_mapping_signals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("question_id", sa.Integer, sa.ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("questionnaire_id", sa.Integer, sa.ForeignKey("questionnaires.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("framework_labels_json", sa.Text, nullable=True),
        sa.Column("subject_labels_json", sa.Text, nullable=True),
        sa.Column("raw_llm_json", sa.Text, nullable=True),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("prompt_version", sa.String(32), nullable=True),
        sa.Column("mapping_quality", sa.String(32), nullable=False, server_default="heuristic_fallback"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.add_column("answers", sa.Column("insufficient_reason", sa.String(64), nullable=True))
    op.add_column("answers", sa.Column("gating_reason", sa.String(64), nullable=True))
    op.add_column("answers", sa.Column("primary_categories_json", sa.Text, nullable=True))

    op.create_table(
        "workspace_ai_usage",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("llm_calls", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("tokens_used", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("mapping_calls", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("answer_calls", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=True, onupdate=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "period", name="uq_workspace_ai_usage_ws_period"),
    )


def downgrade() -> None:
    op.drop_table("workspace_ai_usage")
    op.drop_column("answers", "primary_categories_json")
    op.drop_column("answers", "gating_reason")
    op.drop_column("answers", "insufficient_reason")
    op.drop_table("question_mapping_signals")
