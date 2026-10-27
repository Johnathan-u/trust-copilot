"""TC-10-002: scheduled job retries.

Adds, additively (nullable, no default, no data rewrite):
* jobs.next_attempt_at: earliest time a QUEUED retry may be claimed (bounded exponential backoff + jitter).

jobs.error_code is not added here: TC-11-001 (tc11001_model_outcome_codes, master 1a0e614) already added it with the
same type, and TC-10-002 writes that column.

Stacked on TC-10-003 (tc10003_job_idempotency): job-level retries are only safe with its side-effect ledger.
Master gained another head before this landed: #30 TC-25-011 (9733c93), revision
tc25011_demo_proof_summaries, itself parented on tc10003_job_idempotency. This revision is re-parented
onto that head so alembic has a single head. It still adds only jobs.next_attempt_at.
Chain: 075 -> tc21001_framework_catalog_rights -> tc11001_model_outcome_codes -> tc10003_job_idempotency
-> tc25011_demo_proof_summaries -> tc10002_job_retries.

Revision ID: tc10002_job_retries
Revises: tc25011_demo_proof_summaries
"""

from alembic import op
import sqlalchemy as sa

revision = "tc10002_job_retries"
down_revision = "tc25011_demo_proof_summaries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("next_attempt_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "next_attempt_at")
