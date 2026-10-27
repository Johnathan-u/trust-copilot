"""Persisted evidence-backed demonstration proof summaries (TC-25-011)."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func

from app.core.database import Base


class DemoProofSummary(Base):
    """Idempotent snapshot of a workspace demonstration proof summary.

    Rows are derived from stored workspace records. Rollback drops this table
    only. Nothing in this table is commercial traction.
    """

    __tablename__ = "demo_proof_summaries"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_demo_proof_summary_workspace_key",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(
        Integer,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    schema_version = Column(String(16), nullable=False, server_default="1")
    idempotency_key = Column(String(64), nullable=False)
    content_hash = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)
    window_start = Column(DateTime(timezone=True), nullable=True)
    window_end = Column(DateTime(timezone=True), nullable=True)
    timezone = Column(String(64), nullable=False, server_default="UTC")
    summary_json = Column(Text, nullable=False)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
