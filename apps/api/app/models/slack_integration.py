"""Phase D: Per-workspace Slack integration for notifications."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base


class SlackIntegration(Base):
    """Workspace Slack connection: bot token, selected channel, enabled event types."""

    __tablename__ = "slack_integrations"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    bot_token_encrypted = Column(Text, nullable=False)
    channel_id = Column(String(64), nullable=False)
    channel_name = Column(String(255), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    event_types = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
