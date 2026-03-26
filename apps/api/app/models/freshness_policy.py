"""Per-source-type freshness policy (P1-43)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.core.database import Base


class FreshnessPolicy(Base):
    __tablename__ = "freshness_policies"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = Column(String(64), nullable=False)
    max_age_days = Column(Integer, nullable=False, default=90)
    warn_before_days = Column(Integer, nullable=False, default=14)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
