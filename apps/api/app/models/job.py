"""Job model for async work tracking (JOB-01)."""

from enum import Enum

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

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

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, default=JobStatus.QUEUED.value, index=True)
    payload = Column(Text, nullable=True)
    result = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    attempt = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
