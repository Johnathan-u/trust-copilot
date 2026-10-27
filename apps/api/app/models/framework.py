"""Compliance framework catalog rows.

Production enablement is blocked until content rights are decided (TC-01-007).
Synthetic dev rows are labelled dev/test only and are not a production catalog.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    text,
)

from app.core.database import Base


class Framework(Base):
    __tablename__ = "frameworks"
    __table_args__ = (
        Index("uq_frameworks_catalog_key", "catalog_key", unique=True),
        CheckConstraint(
            "production_catalog = false AND (enablement_state IS NULL OR "
            "enablement_state IN ('blocked', 'dev_only'))",
            name="ck_frameworks_production_blocked",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), nullable=False)
    version = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    catalog_key = Column(String(64), nullable=True)
    source_provenance = Column(Text, nullable=True)
    rights_status = Column(String(64), nullable=True)
    licence_status = Column(String(64), nullable=True)
    enablement_state = Column(String(32), nullable=True)
    catalog_kind = Column(String(32), nullable=True)
    rights_ticket = Column(String(32), nullable=True)
    contract_version = Column(String(64), nullable=True)
    content_origin = Column(String(32), nullable=True)
    # True only for rows this scaffold inserted, so rollback can remove them
    # when they still have no controls.
    scaffold_inserted = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    # Check constraint keeps this false while TC-01-007 is open.
    production_catalog = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    updated_at = Column(DateTime, nullable=True)
