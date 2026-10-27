"""TC-10-003: idempotent job side effects.

Adds, additively:
* jobs.idempotency_key / jobs.input_version, plus a partial unique index so at most one QUEUED job exists
  per (workspace_id, kind, idempotency_key);
* job_effects: per-job side-effect ledger (applied effects, provider-call charge state);
* export_records.job_id (unique when set) so a retried export job reuses its record.

Plain additive DDL: no data rewrite, no table lock beyond the ALTERs. Migration serialization
(one migrator, API/worker wait) is TC-03-005's job and is not assumed here.

Revision ID: tc10003_job_idempotency
Revises: tc11001_model_outcome_codes
"""

from alembic import op
import sqlalchemy as sa

revision = "tc10003_job_idempotency"
down_revision = "tc11001_model_outcome_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("idempotency_key", sa.String(128), nullable=True))
    op.add_column("jobs", sa.Column("input_version", sa.String(512), nullable=True))
    op.create_index(
        "uq_jobs_queued_idempotency_key",
        "jobs",
        ["workspace_id", "kind", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("status = 'queued' AND idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "job_effects",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("effect", sa.String(64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "job_id", "effect", "attempt", name="uq_job_effects_job_effect_attempt"
        ),
    )
    op.create_index("ix_job_effects_id", "job_effects", ["id"])
    op.create_index("ix_job_effects_job_id", "job_effects", ["job_id"])
    op.create_index("ix_job_effects_workspace_id", "job_effects", ["workspace_id"])

    op.add_column(
        "export_records",
        sa.Column(
            "job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
        ),
    )
    op.create_index(
        "uq_export_records_job_id",
        "export_records",
        ["job_id"],
        unique=True,
        postgresql_where=sa.text("job_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_export_records_job_id", table_name="export_records")
    op.drop_column("export_records", "job_id")
    op.drop_index("ix_job_effects_workspace_id", table_name="job_effects")
    op.drop_index("ix_job_effects_job_id", table_name="job_effects")
    op.drop_index("ix_job_effects_id", table_name="job_effects")
    op.drop_table("job_effects")
    op.drop_index("uq_jobs_queued_idempotency_key", table_name="jobs")
    op.drop_column("jobs", "input_version")
    op.drop_column("jobs", "idempotency_key")
