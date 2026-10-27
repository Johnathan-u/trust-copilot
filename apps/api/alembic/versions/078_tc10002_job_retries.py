"""TC-10-002: scheduled job retries.

Adds, additively (nullable, no default, no data rewrite):
* jobs.next_attempt_at: earliest time a QUEUED retry may be claimed (bounded exponential backoff + jitter).

jobs.error_code is not added here: TC-11-001 (tc11001_model_outcome_codes, master 1a0e614) already added it with the
same type, and TC-10-002 writes that column.

Stacked on TC-10-003 (tc10003_job_idempotency): job-level retries are only safe with its side-effect ledger.
Chain on this branch: 075 -> tc21001_framework_catalog_rights -> tc11001_model_outcome_codes (master 1a0e614)
-> tc10003_job_idempotency (re-parented onto tc11001, as #28 does) -> tc10002_job_retries.
If this revision ever has to land without TC-10-003, re-parent it onto master's head at that time (tc11001 today);
it must not also parent on tc11001 while tc10003 does, or alembic sees two heads.

Revision ID: tc10002_job_retries
Revises: tc10003_job_idempotency
"""

from alembic import op
import sqlalchemy as sa

revision = "tc10002_job_retries"
down_revision = "tc10003_job_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("next_attempt_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "next_attempt_at")
