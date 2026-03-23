"""Workspace model for tenancy (AUTH-01). ENT-202: auth policy."""

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String

from app.core.database import Base


class Workspace(Base):
    """Workspace for multi-tenant data isolation."""

    __tablename__ = "workspaces"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(64), nullable=False, unique=True, index=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    # ENT-202: per-workspace auth policy
    mfa_required = Column(Boolean, default=False, nullable=False)
    session_max_age_seconds = Column(Integer, nullable=True)  # null = use default (7 days)
    # AI-TONE-UI: optional per-workspace AI settings overrides
    ai_completion_model = Column(String(255), nullable=True)
    ai_temperature = Column(Float, nullable=True)
    # Phase 5: evidence staleness thresholds (days); null = use app default
    evidence_stale_verified_days = Column(Integer, nullable=True)
    evidence_stale_unverified_days = Column(Integer, nullable=True)
    # Phase 6: compliance webhook delivery URL (POST payload on events)
    compliance_webhook_url = Column(String(512), nullable=True)
    # Automate everything: auto-run answer generation on new questionnaires
    ai_automate_everything = Column(Boolean, default=False, nullable=False)
