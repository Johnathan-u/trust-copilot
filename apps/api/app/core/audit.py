"""Audit events (OPS-01, AUD-201). Logs to logger and optionally persists to DB."""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger("trustcopilot.audit")


def audit_log(
    action: str,
    *,
    user_id: int | None = None,
    email: str | None = None,
    workspace_id: int | None = None,
    resource_type: str | None = None,
    resource_id: int | str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Emit an audit event. Logs to Python logging."""
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "user_id": user_id,
        "email": email,
        "workspace_id": workspace_id,
        "resource_type": resource_type,
        "resource_id": resource_id,
        **(details or {}),
    }
    logger.info("audit %s", json.dumps({k: v for k, v in event.items() if v is not None}))


def persist_audit(
    db: Session,
    action: str,
    *,
    user_id: int | None = None,
    email: str | None = None,
    workspace_id: int | None = None,
    resource_type: str | None = None,
    resource_id: int | str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Persist an audit event to the database (AUD-201). Call from auth and high-value routes."""
    from app.models import AuditEvent

    rid = str(resource_id) if resource_id is not None else None
    try:
        details_json = json.dumps(details) if details else None
    except (TypeError, ValueError):
        details_json = str(details) if details else None
    ev = AuditEvent(
        action=action,
        user_id=user_id,
        email=email,
        workspace_id=workspace_id,
        resource_type=resource_type,
        resource_id=rid,
        details=details_json,
    )
    db.add(ev)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
