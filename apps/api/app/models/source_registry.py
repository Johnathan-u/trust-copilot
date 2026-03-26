"""Source registry — declares every evidence source type with auth, cadence, and failure modes."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func

from app.core.database import Base


class SourceRegistry(Base):
    """Registry entry for an evidence source type (connector) in a workspace."""

    __tablename__ = "source_registry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = Column(String(64), nullable=False, index=True)
    display_name = Column(String(255), nullable=False)
    auth_method = Column(String(64), nullable=False, default="none")
    sync_cadence = Column(String(32), nullable=False, default="manual")
    object_types = Column(Text, nullable=True)
    failure_modes = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="available")
    enabled = Column(Boolean, nullable=False, default=False)
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    last_sync_status = Column(String(32), nullable=True)
    last_error = Column(Text, nullable=True)
    config_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
