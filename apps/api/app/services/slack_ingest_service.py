"""Phase E: Slack ingest service — fetch messages from approved channels, create evidence items, suggest controls."""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.audit import persist_audit
from app.models.evidence_item import EvidenceItem
from app.models.slack_ingest import SlackControlSuggestion, SlackIngestChannel
from app.models.slack_integration import SlackIntegration
from app.services.slack_service import decrypt_token, get_slack_provider

logger = logging.getLogger(__name__)


def _make_source_metadata(
    slack_team_id: str | None,
    channel_id: str,
    message_ts: str,
    sender: str | None = None,
    channel_name: str | None = None,
) -> str:
    return json.dumps({
        "slack_team_id": slack_team_id,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "message_ts": message_ts,
        "sender": sender,
    })


def _evidence_exists(db: Session, workspace_id: int, channel_id: str, message_ts: str) -> bool:
    """Check for duplicate by stable Slack identifier (channel_id + message_ts)."""
    rows = db.query(EvidenceItem).filter(
        EvidenceItem.workspace_id == workspace_id,
        EvidenceItem.source_type == "slack",
    ).all()
    for r in rows:
        if not r.source_metadata:
            continue
        try:
            meta = json.loads(r.source_metadata)
            if meta.get("channel_id") == channel_id and meta.get("message_ts") == message_ts:
                return True
        except (json.JSONDecodeError, TypeError):
            continue
    return False


def ingest_message(
    db: Session,
    workspace_id: int,
    channel_id: str,
    message_ts: str,
    text: str,
    sender: str | None = None,
    slack_team_id: str | None = None,
    channel_name: str | None = None,
    admin_user_id: int | None = None,
) -> EvidenceItem | None:
    """
    Ingest a single Slack message as evidence.
    Returns the created EvidenceItem, or None if the channel is not approved or the message is a duplicate.
    """
    ich = db.query(SlackIngestChannel).filter(
        SlackIngestChannel.workspace_id == workspace_id,
        SlackIngestChannel.channel_id == channel_id,
        SlackIngestChannel.enabled == True,
    ).first()
    if not ich:
        return None

    if _evidence_exists(db, workspace_id, channel_id, message_ts):
        logger.debug("Slack ingest dedup skip: ws=%s ch=%s ts=%s", workspace_id, channel_id, message_ts)
        return None

    title = (text or "").strip()[:500] or f"Slack message from #{channel_name or channel_id}"

    ev = EvidenceItem(
        workspace_id=workspace_id,
        source_type="slack",
        title=title,
        source_metadata=_make_source_metadata(
            slack_team_id=slack_team_id,
            channel_id=channel_id,
            message_ts=message_ts,
            sender=sender,
            channel_name=channel_name or ich.channel_name,
        ),
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)

    persist_audit(
        db, "slack.evidence_ingested",
        user_id=admin_user_id,
        workspace_id=workspace_id,
        resource_type="evidence_item",
        resource_id=ev.id,
        details={"channel_id": channel_id, "message_ts": message_ts, "sender": sender},
    )

    return ev


def fetch_and_ingest_channel(
    db: Session,
    workspace_id: int,
    channel_id: str,
    admin_user_id: int | None = None,
    limit: int = 20,
) -> dict:
    """
    Fetch recent messages from an approved Slack channel and ingest them as evidence.
    Returns {"ingested": N, "skipped": N, "errors": [...]}.
    """
    ich = db.query(SlackIngestChannel).filter(
        SlackIngestChannel.workspace_id == workspace_id,
        SlackIngestChannel.channel_id == channel_id,
        SlackIngestChannel.enabled == True,
    ).first()
    if not ich:
        return {"ingested": 0, "skipped": 0, "errors": ["Channel not approved for ingestion"]}

    si = db.query(SlackIntegration).filter(
        SlackIntegration.workspace_id == workspace_id,
        SlackIntegration.enabled == True,
    ).first()
    if not si:
        return {"ingested": 0, "skipped": 0, "errors": ["Slack not connected"]}

    try:
        token = decrypt_token(si.bot_token_encrypted)
    except Exception as e:
        return {"ingested": 0, "skipped": 0, "errors": [f"Token decrypt failed: {str(e)[:100]}"]}

    provider = get_slack_provider()

    try:
        result = provider.fetch_messages(token, channel_id, limit=limit)
    except AttributeError:
        result = _stub_fetch_messages(channel_id, limit)
    except Exception as e:
        return {"ingested": 0, "skipped": 0, "errors": [f"Slack API error: {str(e)[:200]}"]}

    if not result.get("ok", False):
        return {"ingested": 0, "skipped": 0, "errors": [result.get("error", "Unknown Slack error")]}

    messages = result.get("messages", [])
    ingested = 0
    skipped = 0
    errors = []

    auth_info = provider.test_auth(token)
    team_id = auth_info.get("team_id") or auth_info.get("team")

    for msg in messages:
        ts = msg.get("ts", "")
        text = msg.get("text", "")
        sender = msg.get("user", msg.get("username", ""))
        if not ts:
            skipped += 1
            continue
        try:
            ev = ingest_message(
                db, workspace_id, channel_id, ts, text,
                sender=sender, slack_team_id=team_id,
                channel_name=ich.channel_name,
                admin_user_id=admin_user_id,
            )
            if ev:
                ingested += 1
            else:
                skipped += 1
        except Exception as e:
            errors.append(f"ts={ts}: {str(e)[:100]}")

    return {"ingested": ingested, "skipped": skipped, "errors": errors}


def _stub_fetch_messages(channel_id: str, limit: int) -> dict:
    """Stub for ConsoleSlackProvider which doesn't have fetch_messages."""
    import time
    return {
        "ok": True,
        "messages": [
            {"ts": f"stub.{time.time()}.{i}", "text": f"Stub message {i} from #{channel_id}", "user": "U_STUB"}
            for i in range(min(limit, 3))
        ],
    }


def suggest_controls_for_evidence(
    db: Session,
    workspace_id: int,
    evidence_id: int,
) -> list[dict]:
    """
    Generate control suggestions for a Slack-ingested evidence item.
    Simple keyword matching against workspace control names. No auto-linking.
    Returns list of suggestion dicts.
    """
    from app.models import WorkspaceControl, FrameworkControl

    ev = db.query(EvidenceItem).filter(
        EvidenceItem.id == evidence_id,
        EvidenceItem.workspace_id == workspace_id,
    ).first()
    if not ev:
        return []

    title_lower = (ev.title or "").lower()
    if not title_lower:
        return []

    controls = (
        db.query(WorkspaceControl, FrameworkControl)
        .join(FrameworkControl, WorkspaceControl.framework_control_id == FrameworkControl.id)
        .filter(WorkspaceControl.workspace_id == workspace_id)
        .all()
    )

    suggestions = []
    for wc, fc in controls:
        ctrl_name = (fc.name or "").lower()
        ctrl_desc = (fc.description or "").lower() if hasattr(fc, "description") else ""
        score = 0.0
        words = ctrl_name.split()
        for w in words:
            if len(w) > 3 and w in title_lower:
                score += 0.3
        if score > 0:
            score = min(score, 0.9)
            existing = db.query(SlackControlSuggestion).filter(
                SlackControlSuggestion.evidence_id == evidence_id,
                SlackControlSuggestion.control_id == wc.id,
            ).first()
            if not existing:
                sug = SlackControlSuggestion(
                    workspace_id=workspace_id,
                    evidence_id=evidence_id,
                    control_id=wc.id,
                    confidence=round(score, 2),
                    status="pending",
                )
                db.add(sug)
                suggestions.append({"control_id": wc.id, "confidence": round(score, 2)})

    if suggestions:
        db.commit()
        try:
            from app.services.in_app_notification_service import notify_admins
            notify_admins(
                db, workspace_id,
                f"{len(suggestions)} control suggestion(s) from Slack evidence",
                f"Evidence #{evidence_id} matched {len(suggestions)} control(s). Review and approve or dismiss.",
                category="info",
                link="/dashboard/slack",
            )
        except Exception:
            pass

    return suggestions
