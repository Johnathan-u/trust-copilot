"""Encrypted credential store for connector secrets and API tokens."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.core.database import Base


class CredentialStore(Base):
    """Encrypted storage for connector credentials with rotation tracking."""

    __tablename__ = "credential_store"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = Column(String(64), nullable=False, index=True)
    credential_type = Column(String(64), nullable=False)
    encrypted_value = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    last_rotated_at = Column(DateTime(timezone=True), nullable=True)
    rotation_interval_days = Column(Integer, nullable=True)
    status = Column(String(32), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
