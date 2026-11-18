"""Per-workspace feature flags for controlled feature rollout."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.core.database import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FeatureFlag(Base):
    """A feature flag scoped to a workspace.

    In production a row wins over FEATURE_*. Outside production, FEATURE_*
    overrides the row. When no row exists, resolution uses the env var and
    then the built-in default. Who changed a flag is an audit_events row
    (action feature_flag.updated), not a column on this table.
    """

    __tablename__ = "feature_flags"
    __table_args__ = (
        UniqueConstraint("workspace_id", "flag_name", name="uq_feature_flags_ws_flag"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    flag_name = Column(String(128), nullable=False, index=True)
    enabled = Column(Boolean, nullable=False, default=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utc_now)
    updated_at = Column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)
