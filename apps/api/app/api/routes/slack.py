"""Phase D: Slack integration API — connect, configure, test, disconnect."""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import persist_audit
from app.core.auth_deps import require_can_admin
from app.core.database import get_db
from app.models import NOTIFICATION_EVENT_TYPES, SlackIntegration
from app.services.slack_service import decrypt_token, encrypt_token, get_slack_provider

router = APIRouter(prefix="/slack", tags=["slack"])


class ConnectRequest(BaseModel):
    bot_token: str
    channel_id: str
    channel_name: str | None = None
    event_types: list[str] | None = None


class UpdateRequest(BaseModel):
    channel_id: str | None = None
    channel_name: str | None = None
    enabled: bool | None = None
    event_types: list[str] | None = None


@router.get("/status")
async def slack_status(
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Return current Slack integration status for this workspace."""
    ws = session["workspace_id"]
    si = db.query(SlackIntegration).filter(SlackIntegration.workspace_id == ws).first()
    if not si:
        return {"connected": False}
    event_types = []
    if si.event_types:
        try:
            event_types = json.loads(si.event_types)
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "connected": True,
        "enabled": bool(si.enabled),
        "channel_id": si.channel_id,
        "channel_name": si.channel_name,
        "event_types": event_types,
        "updated_at": si.updated_at.isoformat() if si.updated_at else None,
    }


@router.post("/connect")
async def slack_connect(
    req: ConnectRequest,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Connect Slack to this workspace. Validates the bot token, stores encrypted."""
    ws = session["workspace_id"]
    token = (req.bot_token or "").strip()
    if not token or len(token) < 20:
        raise HTTPException(status_code=400, detail="Invalid bot token")
    channel_id = (req.channel_id or "").strip()
    if not channel_id:
        raise HTTPException(status_code=400, detail="Channel ID is required")

    provider = get_slack_provider()
    auth_result = provider.test_auth(token)
    if not auth_result.get("ok"):
        raise HTTPException(status_code=400, detail=f"Slack auth failed: {auth_result.get('error', 'unknown')}")

    valid_events = [e for e in (req.event_types or []) if e in NOTIFICATION_EVENT_TYPES]

    existing = db.query(SlackIntegration).filter(SlackIntegration.workspace_id == ws).first()
    if existing:
        existing.bot_token_encrypted = encrypt_token(token)
        existing.channel_id = channel_id
        existing.channel_name = (req.channel_name or "").strip() or None
        existing.enabled = True
        existing.event_types = json.dumps(valid_events) if valid_events else None
        db.commit()
        db.refresh(existing)
    else:
        si = SlackIntegration(
            workspace_id=ws,
            bot_token_encrypted=encrypt_token(token),
            channel_id=channel_id,
            channel_name=(req.channel_name or "").strip() or None,
            enabled=True,
            event_types=json.dumps(valid_events) if valid_events else None,
        )
        db.add(si)
        db.commit()
        db.refresh(si)

    persist_audit(db, "slack.connected", user_id=session.get("user_id"), workspace_id=ws,
                  details={"channel_id": channel_id, "channel_name": req.channel_name, "event_count": len(valid_events)})

    return {"connected": True, "channel_id": channel_id, "channel_name": req.channel_name}


@router.patch("/configure")
async def slack_configure(
    req: UpdateRequest,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Update Slack integration settings (channel, enabled, event types)."""
    ws = session["workspace_id"]
    si = db.query(SlackIntegration).filter(SlackIntegration.workspace_id == ws).first()
    if not si:
        raise HTTPException(status_code=404, detail="Slack not connected")

    changes = {}
    if req.channel_id is not None and req.channel_id != si.channel_id:
        changes["channel_id"] = {"from": si.channel_id, "to": req.channel_id}
        si.channel_id = req.channel_id
    if req.channel_name is not None:
        si.channel_name = req.channel_name.strip() or None
    if req.enabled is not None and si.enabled != req.enabled:
        changes["enabled"] = {"from": si.enabled, "to": req.enabled}
        si.enabled = req.enabled
    if req.event_types is not None:
        valid = [e for e in req.event_types if e in NOTIFICATION_EVENT_TYPES]
        si.event_types = json.dumps(valid) if valid else None
        changes["event_types"] = valid

    db.commit()
    db.refresh(si)

    if changes:
        persist_audit(db, "slack.configured", user_id=session.get("user_id"), workspace_id=ws,
                      details={"changes": changes})

    event_types = []
    if si.event_types:
        try:
            event_types = json.loads(si.event_types)
        except (json.JSONDecodeError, TypeError):
            pass

    return {"enabled": bool(si.enabled), "channel_id": si.channel_id, "channel_name": si.channel_name, "event_types": event_types}


@router.delete("/disconnect")
async def slack_disconnect(
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Disconnect Slack from this workspace. Deletes the integration record."""
    ws = session["workspace_id"]
    si = db.query(SlackIntegration).filter(SlackIntegration.workspace_id == ws).first()
    if not si:
        raise HTTPException(status_code=404, detail="Slack not connected")
    db.delete(si)
    db.commit()
    persist_audit(db, "slack.disconnected", user_id=session.get("user_id"), workspace_id=ws)
    return {"ok": True}


@router.post("/test")
async def slack_test(
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Send a test message to the configured Slack channel."""
    ws = session["workspace_id"]
    si = db.query(SlackIntegration).filter(SlackIntegration.workspace_id == ws).first()
    if not si:
        raise HTTPException(status_code=404, detail="Slack not connected")

    token = decrypt_token(si.bot_token_encrypted)
    provider = get_slack_provider()
    result = provider.send_message(token, si.channel_id, "Trust Copilot test message — Slack integration is working.")

    from app.models import NotificationLog
    db.add(NotificationLog(
        workspace_id=ws,
        event_type="slack.test",
        channel="slack",
        recipient_email=f"#{si.channel_name or si.channel_id}",
        subject="Test message",
        status="sent" if result.get("ok") else "failed",
        error=result.get("error", "")[:500] if not result.get("ok") else None,
    ))
    db.commit()

    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=f"Slack delivery failed: {result.get('error', 'unknown')}")

    return {"ok": True, "message": "Test message sent to Slack"}


@router.get("/channels")
async def slack_channels(
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """List Slack channels the bot can access (requires connected integration)."""
    ws = session["workspace_id"]
    si = db.query(SlackIntegration).filter(SlackIntegration.workspace_id == ws).first()
    if not si:
        raise HTTPException(status_code=404, detail="Slack not connected")
    token = decrypt_token(si.bot_token_encrypted)
    provider = get_slack_provider()
    channels = provider.list_channels(token)
    return {"channels": channels}
