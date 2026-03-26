"""Proof graph, artifact hashes, diffs, reuse provenance (E5-25..E5-30)

Revision ID: 074
Revises: 073
"""
from alembic import op
import sqlalchemy as sa

revision = "074"
down_revision = "073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proof_graph_nodes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("node_type", sa.String(32), nullable=False),
        sa.Column("ref_table", sa.String(64), nullable=True),
        sa.Column("ref_id", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(512), nullable=True),
        sa.Column("meta_json", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "proof_graph_edges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("from_node_id", sa.Integer(), sa.ForeignKey("proof_graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("to_node_id", sa.Integer(), sa.ForeignKey("proof_graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("edge_type", sa.String(64), nullable=False),
    )
    op.create_table(
        "artifact_integrity_hashes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("artifact_kind", sa.String(64), nullable=False),
        sa.Column("artifact_id", sa.Integer(), nullable=False),
        sa.Column("sha256_hex", sa.String(64), nullable=False),
        sa.Column("content_fingerprint", sa.Text(), nullable=True),
        sa.Column("recorded_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_artifact_hash_workspace_kind_id",
        "artifact_integrity_hashes",
        ["workspace_id", "artifact_kind", "artifact_id"],
        unique=False,
    )
    op.create_table(
        "proof_graph_diffs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("trigger_event", sa.String(128), nullable=True),
        sa.Column("before_json", sa.Text(), nullable=True),
        sa.Column("after_json", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "answer_reuse_provenance",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("answer_id", sa.Integer(), nullable=False, index=True),
        sa.Column("questionnaire_id", sa.Integer(), nullable=True),
        sa.Column("deal_id", sa.Integer(), sa.ForeignKey("deals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("buyer_ref", sa.String(255), nullable=True),
        sa.Column("answer_version_hint", sa.String(64), nullable=True),
        sa.Column("evidence_ids_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("answer_reuse_provenance")
    op.drop_table("proof_graph_diffs")
    op.drop_index("ix_artifact_hash_workspace_kind_id", table_name="artifact_integrity_hashes")
    op.drop_table("artifact_integrity_hashes")
    op.drop_table("proof_graph_edges")
    op.drop_table("proof_graph_nodes")
