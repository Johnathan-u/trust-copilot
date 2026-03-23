"""Workspace AI usage metering (enterprise cost governance)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.workspace_ai_usage import WorkspaceAIUsage

logger = logging.getLogger(__name__)


def _current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _get_or_create(db: Session, workspace_id: int, period: str) -> WorkspaceAIUsage:
    row = (
        db.query(WorkspaceAIUsage)
        .filter(WorkspaceAIUsage.workspace_id == workspace_id, WorkspaceAIUsage.period == period)
        .first()
    )
    if row:
        return row
    row = WorkspaceAIUsage(workspace_id=workspace_id, period=period)
    db.add(row)
    db.flush()
    return row


def record_mapping_calls(db: Session, workspace_id: int, llm_calls: int, tokens: int = 0) -> None:
    row = _get_or_create(db, workspace_id, _current_period())
    row.mapping_calls = (row.mapping_calls or 0) + llm_calls
    row.llm_calls = (row.llm_calls or 0) + llm_calls
    row.tokens_used = (row.tokens_used or 0) + tokens


def record_answer_calls(db: Session, workspace_id: int, llm_calls: int, tokens: int = 0) -> None:
    row = _get_or_create(db, workspace_id, _current_period())
    row.answer_calls = (row.answer_calls or 0) + llm_calls
    row.llm_calls = (row.llm_calls or 0) + llm_calls
    row.tokens_used = (row.tokens_used or 0) + tokens


def get_usage(db: Session, workspace_id: int, period: str | None = None) -> dict:
    p = period or _current_period()
    row = (
        db.query(WorkspaceAIUsage)
        .filter(WorkspaceAIUsage.workspace_id == workspace_id, WorkspaceAIUsage.period == p)
        .first()
    )
    if not row:
        return {"period": p, "llm_calls": 0, "tokens_used": 0, "mapping_calls": 0, "answer_calls": 0}
    return {
        "period": row.period,
        "llm_calls": row.llm_calls or 0,
        "tokens_used": row.tokens_used or 0,
        "mapping_calls": row.mapping_calls or 0,
        "answer_calls": row.answer_calls or 0,
    }
