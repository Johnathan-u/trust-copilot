"""CRM connection for a selected pipeline (TC-20-050).

One row is one workspace, provider, and pipeline. Salesforce and HubSpot share
the table. The cursor is the page to resume, or the high-water mark after a
completed pass. No credential is stored here.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from app.core.database import Base


class CrmConnection(Base):
    __tablename__ = "crm_connections"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider",
            "pipeline_id",
            name="uq_crm_connections_ws_provider_pipeline",
        ),
    )

    id = Column(Integer, primary_key=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider = Column(String(32), nullable=False)
    pipeline_id = Column(String(64), nullable=False)
    cursor = Column(Text, nullable=True)
    cursor_kind = Column(String(16), nullable=True)
    seen_external_ids = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
