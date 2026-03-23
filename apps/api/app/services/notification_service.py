"""Phase C+D: Notification dispatch service. Email + Slack delivery, dedup, logging."""

import json
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.notification import (
    NOTIFICATION_EVENT_TYPES,
    NotificationLog,
    NotificationPolicy,
    NotificationUnsubscribe,
)
from app.models.slack_integration import SlackIntegration
from app.models.user import User, WorkspaceMember
from app.services.email_service import EmailMessage, get_email_provider
from app.services.slack_service import decrypt_token, get_slack_provider, is_slack_duplicate

logger = logging.getLogger(__name__)

_recent_sends: dict[str, float] = {}
DEDUP_WINDOW_SECONDS = 60


def _dedup_key(workspace_id: int, event_type: str, email: str) -> str:
    return f"{workspace_id}:{event_type}:{email}"


def _is_duplicate(key: str) -> bool:
    now = time.monotonic()
    last = _recent_sends.get(key)
    if last and (now - last) < DEDUP_WINDOW_SECONDS:
        return True
    _recent_sends[key] = now
    _prune_dedup_cache(now)
    return False


def _prune_dedup_cache(now: float) -> None:
    stale = [k for k, v in _recent_sends.items() if now - v > DEDUP_WINDOW_SECONDS * 2]
    for k in stale:
        _recent_sends.pop(k, None)


def resolve_recipients(
    db: Session,
    workspace_id: int,
    policy: NotificationPolicy,
) -> list[str]:
    """Resolve recipient emails based on policy type. Returns deduplicated list."""
    rt = (policy.recipient_type or "").lower()

    if rt == "all":
        rows = (
            db.query(User.email)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .filter(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.suspended == False)
            .all()
        )
        return list({r[0] for r in rows if r[0]})

    if rt == "admins":
        rows = (
            db.query(User.email)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.role == "admin",
                WorkspaceMember.suspended == False,
            )
            .all()
        )
        return list({r[0] for r in rows if r[0]})

    if rt == "role":
        role_name = (policy.recipient_value or "").strip().lower()
        if not role_name:
            return []
        rows = (
            db.query(User.email)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.role == role_name,
                WorkspaceMember.suspended == False,
            )
            .all()
        )
        return list({r[0] for r in rows if r[0]})

    if rt == "user":
        try:
            uid = int(policy.recipient_value or "0")
        except (ValueError, TypeError):
            return []
        u = db.query(User).filter(User.id == uid).first()
        if not u or not u.email:
            return []
        mem = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == uid,
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.suspended == False,
        ).first()
        return [u.email] if mem else []

    return []


def get_unsubscribed_emails(
    db: Session, workspace_id: int, event_type: str
) -> set[str]:
    """Return emails of users who have unsubscribed from this event type."""
    rows = (
        db.query(User.email)
        .join(NotificationUnsubscribe, NotificationUnsubscribe.user_id == User.id)
        .filter(
            NotificationUnsubscribe.workspace_id == workspace_id,
            NotificationUnsubscribe.event_type == event_type,
        )
        .all()
    )
    return {r[0] for r in rows if r[0]}


def _build_subject(event_type: str, workspace_name: str, detail: str = "") -> str:
    labels = {
        "compliance.coverage_drop": "Coverage dropped below threshold",
        "compliance.blind_spot": "Blind spot detected",
        "compliance.high_insufficient": "High insufficient-answer rate",
        "compliance.weak_evidence": "Weak evidence detected",
        "member.invited": "New member invited",
        "member.joined": "Member joined workspace",
        "member.removed": "Member removed",
        "member.suspended": "Member suspended",
        "member.role_changed": "Member role changed",
        "role.created": "Custom role created",
        "role.updated": "Custom role updated",
        "role.deleted": "Custom role deleted",
        "questionnaire.uploaded": "Questionnaire uploaded",
        "questionnaire.generated": "Answers generated",
        "export.completed": "Export ready",
        "document.indexed": "Document indexed",
    }
    label = labels.get(event_type, event_type)
    subj = f"[{workspace_name}] {label}"
    if detail:
        subj += f" — {detail}"
    return subj


def fire_notification(
    db: Session,
    workspace_id: int,
    event_type: str,
    detail: str = "",
    workspace_name: str = "Workspace",
) -> int:
    """
    Fire a notification for the given event type.
    Looks up the policy, resolves recipients, filters unsubscribes + dedup, sends emails, logs results.
    Returns the number of emails successfully sent.
    """
    if event_type not in NOTIFICATION_EVENT_TYPES:
        return 0

    policy = db.query(NotificationPolicy).filter(
        NotificationPolicy.workspace_id == workspace_id,
        NotificationPolicy.event_type == event_type,
        NotificationPolicy.enabled == True,
    ).first()

    if not policy:
        return 0

    recipients = resolve_recipients(db, workspace_id, policy)
    if not recipients:
        return 0

    unsubs = get_unsubscribed_emails(db, workspace_id, event_type)
    recipients = [e for e in recipients if e not in unsubs]
    if not recipients:
        return 0

    subject = _build_subject(event_type, workspace_name, detail)
    body_text = f"{subject}\n\nEvent: {event_type}\n{detail}" if detail else subject
    body_html = f"<p><strong>{subject}</strong></p><p>{detail or event_type}</p>"

    provider = get_email_provider()
    sent = 0

    for email in recipients:
        dk = _dedup_key(workspace_id, event_type, email)
        if _is_duplicate(dk):
            logger.debug("Dedup skip: %s", dk)
            continue

        status = "sent"
        error_msg = None
        try:
            ok = provider.send(EmailMessage(to=email, subject=subject, body_text=body_text, body_html=body_html))
            if not ok:
                status = "failed"
                error_msg = "Provider returned false"
        except Exception as exc:
            status = "failed"
            error_msg = str(exc)[:500]
            logger.warning("Notification delivery failed to=%s event=%s: %s", email, event_type, error_msg)

        db.add(NotificationLog(
            workspace_id=workspace_id,
            event_type=event_type,
            recipient_email=email,
            subject=subject,
            status=status,
            error=error_msg,
        ))
        if status == "sent":
            sent += 1

    # --- Slack delivery ---
    slack_sent = _fire_slack_notification(db, workspace_id, event_type, detail, workspace_name)
    sent += slack_sent

    try:
        db.commit()
    except Exception:
        db.rollback()

    return sent


def _fire_slack_notification(
    db: Session,
    workspace_id: int,
    event_type: str,
    detail: str,
    workspace_name: str,
) -> int:
    """Deliver notification to Slack if configured for this workspace + event type."""
    try:
        si = db.query(SlackIntegration).filter(
            SlackIntegration.workspace_id == workspace_id,
            SlackIntegration.enabled == True,
        ).first()
        if not si:
            return 0

        enabled_types = []
        if si.event_types:
            try:
                enabled_types = json.loads(si.event_types)
            except (json.JSONDecodeError, TypeError):
                enabled_types = []
        if enabled_types and event_type not in enabled_types:
            return 0

        if is_slack_duplicate(workspace_id, event_type):
            logger.debug("Slack dedup skip: ws=%s evt=%s", workspace_id, event_type)
            return 0

        label = _build_subject(event_type, workspace_name, detail)
        text = f"*{label}*\n{detail}" if detail else label

        token = decrypt_token(si.bot_token_encrypted)
        provider = get_slack_provider()
        result = provider.send_message(token, si.channel_id, text)

        status = "sent" if result.get("ok") else "failed"
        error_msg = result.get("error", "")[:500] if not result.get("ok") else None

        db.add(NotificationLog(
            workspace_id=workspace_id,
            event_type=event_type,
            channel="slack",
            recipient_email=f"#{si.channel_name or si.channel_id}",
            subject=label,
            status=status,
            error=error_msg,
        ))

        if not result.get("ok"):
            logger.warning("Slack delivery failed ws=%s ch=%s: %s", workspace_id, si.channel_id, error_msg)
            try:
                from app.services.in_app_notification_service import notify_admins
                notify_admins(
                    db, workspace_id,
                    "Slack delivery failed",
                    f"Event '{event_type}' failed to deliver to Slack: {error_msg}",
                    category="error",
                    link="/dashboard/notifications",
                )
            except Exception:
                pass

        return 1 if status == "sent" else 0

    except Exception as exc:
        logger.warning("Slack notification error ws=%s: %s", workspace_id, str(exc)[:200])
        try:
            db.add(NotificationLog(
                workspace_id=workspace_id,
                event_type=event_type,
                channel="slack",
                recipient_email="slack-error",
                subject=event_type,
                status="failed",
                error=str(exc)[:500],
            ))
        except Exception:
            pass
        return 0
