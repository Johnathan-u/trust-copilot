"""TC-10-001: per-job worker leases.

Adds, additively (nullable, no default, no backfill):

* jobs.lease_owner: token of the worker that holds the lease (NULL if unowned)
* jobs.lease_expires_at: naive UTC expiry. A running job past this time is abandoned.
* ix_jobs_running_lease_expires_at: partial index for that scan

Plain ADD COLUMN without a default is a metadata-only change on Postgres (no table rewrite).
Existing rows stay NULL. A NULL lease_expires_at is not treated as expired, so a job that was
already running when this revision is applied is not reclaimed.

Downgrade drops the index and both columns. Every other jobs column is unchanged. Re-upgrade
adds the columns back as NULL; it does not invent lease tokens.

Parent is master's alembic head at push time (tc21006_gap_evaluation, origin/master
bff2c39). The revision id is 18 characters and fits alembic_version.version_num
(varchar 32); this migration does not widen that column.

Revision ID: tc10001_job_leases
Revises: tc21006_gap_evaluation
"""

from alembic import op
import sqlalchemy as sa

revision = "tc10001_job_leases"
down_revision = "tc21006_gap_evaluation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("lease_owner", sa.String(length=64), nullable=True))
    op.add_column("jobs", sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
    op.create_index(
        "ix_jobs_running_lease_expires_at",
        "jobs",
        ["lease_expires_at"],
        postgresql_where=sa.text("status = 'running' AND lease_expires_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_running_lease_expires_at", table_name="jobs")
    op.drop_column("jobs", "lease_expires_at")
    op.drop_column("jobs", "lease_owner")
