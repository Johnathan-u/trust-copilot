"""Demo proof summaries.

Additive empty table. This revision does not import application code, and it
does not rename, update, or overwrite existing rows. A historical snapshot is
not backfilled, because that would invent a proof that was never stored.
A snapshot is written later by an authorized save for that workspace, from
rows stored at that time.

Downgrade drops only demo_proof_summaries. Those rows are derived snapshot
data. They are not source evidence. The next authorized save rebuilds a
snapshot from the questionnaires, documents, evidence, and exports that this
downgrade leaves in place. Snapshot history itself is not restored.

Revision ID: tc25011_demo_proof_summaries
Revises: 075

down_revision stays 075 until this branch merges. Whoever merges second
re-parents down_revision onto master's head. The numeric id 076 is not used:
it collides with another ticket and with Core PR #16.
"""

import sqlalchemy as sa

from alembic import op

revision = "tc25011_demo_proof_summaries"
down_revision = "075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demo_proof_summaries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(length=16), nullable=False, server_default="1"),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_demo_proof_summary_workspace_key",
        ),
    )
    op.create_index(
        "ix_demo_proof_summaries_workspace_id",
        "demo_proof_summaries",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_demo_proof_summaries_workspace_id", table_name="demo_proof_summaries")
    op.drop_table("demo_proof_summaries")
