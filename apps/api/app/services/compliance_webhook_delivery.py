"""Phase 6: Deliver compliance webhook outbox to configured URL with retry/backoff."""

import json
import logging
import time
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from sqlalchemy.orm import Session

from app.models import ComplianceWebhookOutbox, Workspace

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BACKOFF_BASE_SEC = 1  # 1, 2, 4, 8, 16
BATCH_SIZE = 20


def _post_payload(url: str, payload: dict, timeout: int = 10) -> tuple[bool, str]:
    """POST JSON payload to URL. Returns (success, error_message)."""
    try:
        data = json.dumps(payload, default=str).encode("utf-8")
        req = Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout) as resp:
            if 200 <= resp.getcode() < 300:
                return True, ""
            return False, f"HTTP {resp.getcode()}"
    except HTTPError as e:
        return False, f"HTTP {e.code} {e.reason}"
    except URLError as e:
        return False, str(e.reason) if getattr(e, "reason", None) else str(e)
    except Exception as e:
        return False, str(e)[:500]


def process_compliance_webhook_outbox(db: Session) -> int:
    """
    Process pending outbox rows: POST to workspace compliance_webhook_url with retry/backoff.
    Returns number of rows processed (delivered or marked failed).
    """
    pending = (
        db.query(ComplianceWebhookOutbox)
        .filter(
            ComplianceWebhookOutbox.delivered_at.is_(None),
            ComplianceWebhookOutbox.status == "pending",
            ComplianceWebhookOutbox.attempt_count < MAX_ATTEMPTS,
        )
        .order_by(ComplianceWebhookOutbox.created_at)
        .limit(BATCH_SIZE)
        .all()
    )
    if not pending:
        return 0
    workspace_ids = list({r.workspace_id for r in pending})
    workspaces = {w.id: w for w in db.query(Workspace).filter(Workspace.id.in_(workspace_ids)).all()}
    processed = 0
    for row in pending:
        ws = workspaces.get(row.workspace_id)
        url = ws.compliance_webhook_url if ws else None
        if not url or not url.strip():
            row.last_error = "No webhook URL configured"
            row.attempt_count = MAX_ATTEMPTS
            row.status = "failed"
            db.commit()
            processed += 1
            continue
        url = url.strip()
        try:
            payload = json.loads(row.payload_json) if row.payload_json else {}
        except Exception:
            payload = {"raw": row.payload_json}
        payload["_event_type"] = row.event_type
        payload["_created_at"] = row.created_at.isoformat() if row.created_at else None
        attempt = row.attempt_count
        backoff = BACKOFF_BASE_SEC * (2 ** attempt)
        if attempt > 0:
            time.sleep(min(backoff, 60))
        ok, err = _post_payload(url, payload)
        row.attempt_count = row.attempt_count + 1
        if ok:
            row.delivered_at = datetime.utcnow()
            row.status = "delivered"
            row.last_error = None
            db.commit()
            processed += 1
            logger.info("compliance_webhook_delivered outbox_id=%s workspace_id=%s event_type=%s", row.id, row.workspace_id, row.event_type)
        else:
            row.last_error = err[:1000] if err else "Unknown error"
            if row.attempt_count >= MAX_ATTEMPTS:
                row.status = "failed"
                logger.warning(
                    "compliance_webhook_failed outbox_id=%s workspace_id=%s attempt=%s error=%s",
                    row.id, row.workspace_id, row.attempt_count, row.last_error,
                )
            db.commit()
            processed += 1
    return processed
