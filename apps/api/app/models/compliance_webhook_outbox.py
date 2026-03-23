"""Phase 5/6: Outbox for compliance webhook events; Phase 6 delivery state."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base


class ComplianceWebhookOutbox(Base):
    __tablename__ = "compliance_webhook_outbox"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    payload_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    delivered_at = Column(DateTime, nullable=True)
    status = Column(String(32), nullable=False, default="pending")
    last_error = Column(Text, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
