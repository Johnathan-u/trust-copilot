"""Job model for async work tracking (JOB-01)."""

from enum import Enum

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, text

from app.core.database import Base, utc_now


class JobKind(str, Enum):
    """Job type for routing execution."""

    PARSE_QUESTIONNAIRE = "parse_questionnaire"
    PARSE_EVIDENCE = "parse_evidence"
    INDEX_DOCUMENT = "index_document"
    GENERATE_ANSWERS = "generate_answers"
    EXPORT = "export"


class JobStatus(str, Enum):
    """Job lifecycle status."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(Base):
    """Background job for async processing."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index(
            "uq_jobs_queued_idempotency_key",
            "workspace_id",
            "kind",
            "idempotency_key",
            unique=True,
            postgresql_where=text("status = 'queued' AND idempotency_key IS NOT NULL"),
        ),
        Index(
            "ix_jobs_running_lease_expires_at",
            "lease_expires_at",
            postgresql_where=text("status = 'running' AND lease_expires_at IS NOT NULL"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, default=JobStatus.QUEUED.value, index=True)
    payload = Column(Text, nullable=True)
    result = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    # TC-11-001: stable typed error code for failed jobs (safe message lives in ``error``).
    error_code = Column(String(64), nullable=True)
    attempt = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    # TC-10-003: server-derived dedupe key (unique among QUEUED jobs per workspace+kind) and the version of
    # the input the job was enqueued for (e.g. the source object's storage key). Both nullable/additive.
    idempotency_key = Column(String(128), nullable=True)
    input_version = Column(String(512), nullable=True)
    # TC-10-002: for a QUEUED retry, the earliest time it may be claimed (nullable/additive). TC-10-002 also
    # writes error_code above (TC-11-001 model_* codes for model failures, app.core.job_errors codes otherwise).
    next_attempt_at = Column(DateTime, nullable=True)
    # TC-10-001: owner token and expiry. NULL is not an expired lease. TC-10-001b abandons it
    # only after JOB_NULL_LEASE_GRACE_SECONDS.
    lease_owner = Column(String(64), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
