"""Phase E: Slack ingest — approved channels and control suggestions."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String

from app.core.database import Base


class SlackIngestChannel(Base):
    """Per-workspace approved Slack channel for evidence ingestion."""

    __tablename__ = "slack_ingest_channels"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    slack_integration_id = Column(Integer, ForeignKey("slack_integrations.id", ondelete="CASCADE"), nullable=False)
    channel_id = Column(String(64), nullable=False)
    channel_name = Column(String(255), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SlackControlSuggestion(Base):
    """Suggested control link for Slack-ingested evidence. Requires manual approval."""

    __tablename__ = "slack_control_suggestions"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_id = Column(Integer, ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=False, index=True)
    control_id = Column(Integer, ForeignKey("workspace_controls.id", ondelete="CASCADE"), nullable=False)
    confidence = Column(Float, nullable=True)
    status = Column(String(16), nullable=False, default="pending")
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
