"""Per-workspace quota enforcement for multi-tenant fairness."""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.workspace_quota import WorkspaceQuota, WorkspaceUsage

logger = logging.getLogger(__name__)

QUOTA_DEFAULTS = {
    "documents": 500,
    "questionnaires": 100,
    "jobs": 50,
    "exports": 30,
    "slack_ingests": 20,
    "gmail_ingests": 20,
    "ai_jobs": 10,
    "notifications": 100,
}

_QUOTA_FIELD_MAP = {
    "documents": "max_documents",
    "questionnaires": "max_questionnaires",
    "jobs": "max_jobs_per_hour",
    "exports": "max_exports_per_hour",
    "slack_ingests": "max_slack_ingests_per_hour",
    "gmail_ingests": "max_gmail_ingests_per_hour",
    "ai_jobs": "max_ai_jobs_per_hour",
    "notifications": "max_notifications_per_hour",
}


def _current_window_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(minute=0, second=0, microsecond=0)


def get_quota_limit(db: Session, workspace_id: int, resource_type: str) -> int:
    """Return the configured quota limit for a workspace/resource, or the default."""
    quota = db.query(WorkspaceQuota).filter(WorkspaceQuota.workspace_id == workspace_id).first()
    if quota:
        field = _QUOTA_FIELD_MAP.get(resource_type)
        if field:
            return getattr(quota, field, QUOTA_DEFAULTS.get(resource_type, 50))
    return QUOTA_DEFAULTS.get(resource_type, 50)


def get_current_usage(db: Session, workspace_id: int, resource_type: str) -> int:
    """Return usage count for the current hour window."""
    window = _current_window_start()
    row = db.query(WorkspaceUsage).filter(
        WorkspaceUsage.workspace_id == workspace_id,
        WorkspaceUsage.resource_type == resource_type,
        WorkspaceUsage.window_start == window,
    ).first()
    return row.count if row else 0


def record_usage(db: Session, workspace_id: int, resource_type: str, amount: int = 1) -> None:
    """Increment usage counter for current hour window."""
    window = _current_window_start()
    row = db.query(WorkspaceUsage).filter(
        WorkspaceUsage.workspace_id == workspace_id,
        WorkspaceUsage.resource_type == resource_type,
        WorkspaceUsage.window_start == window,
    ).first()
    if row:
        row.count += amount
    else:
        db.add(WorkspaceUsage(
            workspace_id=workspace_id,
            resource_type=resource_type,
            window_start=window,
            count=amount,
        ))
    db.flush()


def check_quota(db: Session, workspace_id: int, resource_type: str) -> tuple[bool, int, int]:
    """Check if workspace is within quota. Returns (allowed, current, limit)."""
    limit = get_quota_limit(db, workspace_id, resource_type)
    current = get_current_usage(db, workspace_id, resource_type)
    return current < limit, current, limit


def enforce_quota(db: Session, workspace_id: int, resource_type: str) -> None:
    """Raise ValueError if workspace is over quota for the resource type."""
    allowed, current, limit = check_quota(db, workspace_id, resource_type)
    if not allowed:
        raise ValueError(f"Workspace {workspace_id} exceeded {resource_type} quota: {current}/{limit} per hour")


def record_and_check(db: Session, workspace_id: int, resource_type: str) -> tuple[bool, int, int]:
    """Record one usage and return (allowed_before_this, current_after, limit)."""
    limit = get_quota_limit(db, workspace_id, resource_type)
    current = get_current_usage(db, workspace_id, resource_type)
    allowed = current < limit
    if allowed:
        record_usage(db, workspace_id, resource_type)
    return allowed, current + (1 if allowed else 0), limit


def cleanup_old_usage(db: Session) -> int:
    """Remove usage records older than 24 hours. Call periodically from worker."""
    cutoff = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    from datetime import timedelta
    cutoff = cutoff - timedelta(hours=24)
    deleted = db.query(WorkspaceUsage).filter(WorkspaceUsage.window_start < cutoff).delete()
    db.flush()
    return deleted
