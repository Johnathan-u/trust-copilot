"""Phase 4: Evidence last_verified_at; control verified_at / verified_by_user_id."""

from alembic import op
import sqlalchemy as sa

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "control_evidence_links",
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "workspace_controls",
        sa.Column("verified_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "workspace_controls",
        sa.Column("verified_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_workspace_controls_verified_by_user_id", "workspace_controls", ["verified_by_user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_workspace_controls_verified_by_user_id", table_name="workspace_controls")
    op.drop_column("workspace_controls", "verified_by_user_id")
    op.drop_column("workspace_controls", "verified_at")
    op.drop_column("control_evidence_links", "last_verified_at")
