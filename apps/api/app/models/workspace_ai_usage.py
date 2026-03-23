"""Per-workspace per-period AI usage tracking (enterprise cost governance)."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, text

from app.core.database import Base


class WorkspaceAIUsage(Base):
    """Monthly usage counters for LLM calls, tokens, mapping and answer generation."""

    __tablename__ = "workspace_ai_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    period = Column(String(16), nullable=False)
    llm_calls = Column(Integer, nullable=False, server_default=text("0"))
    tokens_used = Column(Integer, nullable=False, server_default=text("0"))
    mapping_calls = Column(Integer, nullable=False, server_default=text("0"))
    answer_calls = Column(Integer, nullable=False, server_default=text("0"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=True, onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("workspace_id", "period", name="uq_workspace_ai_usage_ws_period"),
    )
