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
) -> int:
    """Persist an audit event and return its id (AUD-201)."""
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
        db.flush()
        raw_id = ev.id
        db.commit()
    except Exception:
        db.rollback()
        raise
    if isinstance(raw_id, int) and not isinstance(raw_id, bool):
        return raw_id
    # A real session assigns the primary key on flush. Test doubles do not.
    if isinstance(db, Session):
        raise RuntimeError("audit event id was not assigned")
    return 0


_DECRYPT_REASONS = frozenset({"reenrol_marker", "unknown_key_id", "decrypt_failed"})


def record_decrypt_failure(
    db: Session,
    *,
    user_id: int | None,
    stored: str | None,
    reason: str,
    resource_type: str,
    resource_id: int | str | None = None,
    workspace_id: int | None = None,
    commit: bool = False,
) -> None:
    """Audit one failed decrypt. Details are the key id and reason only."""
    from app.core.keys import stored_key_id

    safe_reason = reason if reason in _DECRYPT_REASONS else "decrypt_failed"
    details = {"key_id": stored_key_id(stored), "reason": safe_reason}
    audit_log(
        "crypto.decrypt_failed",
        user_id=user_id,
        workspace_id=workspace_id,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
    )
    if commit:
        persist_audit(
            db,
            "crypto.decrypt_failed",
            user_id=user_id,
            workspace_id=workspace_id,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
        return
    from app.models import AuditEvent

    db.add(
        AuditEvent(
            action="crypto.decrypt_failed",
            user_id=user_id,
            workspace_id=workspace_id,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            details=json.dumps(details),
        )
    )
    db.flush()
