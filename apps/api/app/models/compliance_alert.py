"""Persisted compliance alert condition and lifecycle."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, text

from app.core.database import Base

ALERT_STATUS_ACTIVE = "active"
ALERT_STATUS_ACKNOWLEDGED = "acknowledged"
ALERT_STATUS_SNOOZED = "snoozed"
ALERT_STATUS_RESOLVED = "resolved"
ALERT_STATUSES = (
    ALERT_STATUS_ACTIVE,
    ALERT_STATUS_ACKNOWLEDGED,
    ALERT_STATUS_SNOOZED,
    ALERT_STATUS_RESOLVED,
)
UQ_COMPLIANCE_ALERTS_ONE_ACTIVE = "uq_compliance_alerts_one_active"
ONE_ACTIVE_ALERT_WHERE = f"status = '{ALERT_STATUS_ACTIVE}'"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ComplianceAlert(Base):
    __tablename__ = "compliance_alerts"
    __table_args__ = (
        Index(
            UQ_COMPLIANCE_ALERTS_ONE_ACTIVE,
            "workspace_id",
            "condition",
            "source_ref",
            unique=True,
            postgresql_where=text(ONE_ACTIVE_ALERT_WHERE),
        ),
    )

    id = Column(Integer, primary_key=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    condition = Column(String(64), nullable=False)
    source_ref = Column(String(160), nullable=False)
    source_revision = Column(String(64), nullable=True)
    control_id = Column(Integer, nullable=True)
    control_revision = Column(String(64), nullable=True)
    status = Column(String(16), nullable=False, default=ALERT_STATUS_ACTIVE)
    severity = Column(String(16), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    metric = Column(Float, nullable=True)
    reason = Column(Text, nullable=True)
    snoozed_until = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    actor_user_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)
