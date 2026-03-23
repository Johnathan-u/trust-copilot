"""Phase 5: Emit compliance events to audit log and webhook outbox."""

import json
import logging

from sqlalchemy.orm import Session

from app.core.audit import persist_audit
from app.models import ComplianceWebhookOutbox

logger = logging.getLogger(__name__)

EVENT_EVIDENCE_VERIFIED = "evidence.verified"
EVENT_CONTROL_VERIFIED = "control.verified"
EVENT_MAPPING_CONFIRMED = "mapping.confirmed"
EVENT_MAPPING_OVERRIDDEN = "mapping.overridden"


def emit_compliance_event(
    db: Session,
    workspace_id: int,
    event_type: str,
    payload: dict,
    *,
    user_id: int | None = None,
    email: str | None = None,
) -> None:
    """Persist to audit log (action=compliance.<event_type>) and add to webhook outbox."""
    action = f"compliance.{event_type}"
    try:
        persist_audit(
            db,
            action,
            workspace_id=workspace_id,
            user_id=user_id,
            email=email,
            resource_type=payload.get("resource_type"),
            resource_id=payload.get("resource_id"),
            details=payload,
        )
    except Exception as e:
        logger.warning("compliance audit persist failed: %s", e)
    try:
        payload_json = json.dumps(payload, default=str)
        db.add(
            ComplianceWebhookOutbox(
                workspace_id=workspace_id,
                event_type=event_type,
                payload_json=payload_json,
            )
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("compliance webhook outbox add failed: %s", e)
