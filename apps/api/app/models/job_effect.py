"""Per-job side-effect ledger (TC-10-003).

One row records one side effect of one job:

* ``state="applied"`` (``attempt=0``): a durable effect (questions, chunks, export record, quota usage)
  was committed. The row is written in the SAME transaction as the effect, so after a crash the row
  exists exactly when the effect exists. The unique key (job_id, effect, attempt) means a second
  execution of the same job cannot commit the effect twice.
* ``state="started" | "settled" | "uncertain"`` (``attempt=N``): a paid provider call
  (embeddings / completions) for attempt N. ``started`` is committed on its own BEFORE the call;
  ``settled`` is written with the attempt's result. A ``started`` row that is never settled (crash or
  failure) becomes ``uncertain``: the provider may have charged for work we did not keep.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from app.core.database import Base, utc_now

EFFECT_APPLIED = "applied"
EFFECT_STARTED = "started"
EFFECT_SETTLED = "settled"
EFFECT_UNCERTAIN = "uncertain"


class JobEffect(Base):
    """Ledger row for one side effect of one job (see module docstring)."""

    __tablename__ = "job_effects"
    __table_args__ = (
        UniqueConstraint("job_id", "effect", "attempt", name="uq_job_effects_job_effect_attempt"),
    )

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    effect = Column(String(64), nullable=False)
    attempt = Column(Integer, nullable=False, default=0)
    state = Column(String(16), nullable=False)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
