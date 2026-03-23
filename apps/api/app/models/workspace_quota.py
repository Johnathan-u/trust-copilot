"""Per-workspace quotas and usage tracking for multi-tenant fairness."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, ForeignKey, String

from app.core.database import Base


class WorkspaceQuota(Base):
    """Configurable per-workspace resource limits."""

    __tablename__ = "workspace_quotas"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    max_documents = Column(Integer, nullable=False, default=500)
    max_questionnaires = Column(Integer, nullable=False, default=100)
    max_jobs_per_hour = Column(Integer, nullable=False, default=50)
    max_exports_per_hour = Column(Integer, nullable=False, default=30)
    max_slack_ingests_per_hour = Column(Integer, nullable=False, default=20)
    max_gmail_ingests_per_hour = Column(Integer, nullable=False, default=20)
    max_ai_jobs_per_hour = Column(Integer, nullable=False, default=10)
    max_notifications_per_hour = Column(Integer, nullable=False, default=100)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkspaceUsage(Base):
    """Rolling usage counters per workspace per resource type per hour window."""

    __tablename__ = "workspace_usage"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    resource_type = Column(String(64), nullable=False)
    window_start = Column(DateTime, nullable=False)
    count = Column(Integer, nullable=False, default=0)
