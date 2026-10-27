"""Notification dispatch. Email, Slack, and in-app, with preference, dedupe, and retry state."""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.in_app_notification import InAppNotification
from app.models.notification import (
    NOTIFICATION_EVENT_TYPES,
    NotificationDeliveryAttempt,
    NotificationLog,
    NotificationPolicy,
    NotificationUnsubscribe,
)
from app.models.slack_integration import SlackIntegration
from app.models.user import User, WorkspaceMember
from app.services.email_service import (
    ConsoleEmailProvider,
    EmailMessage,
    SmtpEmailProvider,
    get_email_provider,
)
from app.services.message_providers.errors import public_error_detail
from app.services.message_providers.retry_seam import (
    DEFAULT_MAX_ATTEMPTS,
    BoundedRetrySeam,
    ProviderCallResult,
    _fail,
)
from app.services.message_providers.selection import delivery_accepted
from app.services.notification_preferences import channel_enabled, preference_block_reason
from app.services.notification_redaction import redact_notification_text
from app.services.notification_templates import RenderedNotification, render_notification
from app.services.slack_service import decrypt_token, get_slack_provider

logger = logging.getLogger(__name__)

STATE_QUEUED = "queued"
STATE_SENT = "sent"
STATE_RETRYING = "retrying"
STATE_DEDUPED = "deduped"
STATE_DEAD = "dead-lettered"
STATE_SUPPRESSED = "suppressed-by-preference"


DEDUPE_ERROR_CODE = "claimed"
CLAIM_LEASE = timedelta(minutes=15)
CLAIM_TTL = timedelta(hours=24)

_CLAIM_SQL = text(
    """
    INSERT INTO notification_dedupe_claims
        (dedupe_key, claimed_at, expires_at, released_at)
    VALUES (:key, :now, :expires, NULL)
    ON CONFLICT (dedupe_key) DO UPDATE
    SET claimed_at = EXCLUDED.claimed_at,
        expires_at = EXCLUDED.expires_at,
        released_at = NULL
    WHERE notification_dedupe_claims.released_at IS NOT NULL
       OR notification_dedupe_claims.expires_at < :now
    RETURNING dedupe_key
    """
)
_EXTEND_SQL = text(
    """
    UPDATE notification_dedupe_claims
    SET expires_at = :expires
    WHERE dedupe_key = :key AND released_at IS NULL
    """
)


class _ClaimLost(Exception):
    """The in-app savepoint lost the claim and must not insert a row."""


def stable_dedupe_key(
    workspace_id: int,
    event_type: str,
    channel: str,
    recipient: str,
    event_id: str | None = None,
) -> str:
    """Sha256 hex of one event, recipient, and channel.

    The raw value is ``{workspace}:{event_type}:{event_id}:{channel}:{recipient}``.
    An empty event id does not claim: those sends are not deduped. Two
    occurrence ids never share a claim. The stored key is the hex digest.
    """
    identity = (recipient or "").strip().lower()
    event = (event_id or "").strip()
    raw = f"{int(workspace_id)}:{event_type}:{event}:{channel}:{identity}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _claim_bind(key: str, ttl: timedelta) -> dict:
    now = datetime.now(timezone.utc)
    return {"key": key, "now": now, "expires": now + ttl}


def claim_dedupe_key(key: str, *, ttl: timedelta = CLAIM_LEASE) -> bool:
    """Insert or take over one claim in its own transaction.

    The lease is 15 minutes until the provider accepts. A claim is won only
    when PostgreSQL returns the row. A live unreleased claim returns no row.
    """
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        won = claim_dedupe_key_on(db, key, ttl=ttl)
        db.commit()
        return won
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def claim_dedupe_key_on(db: Session, key: str, *, ttl: timedelta = CLAIM_LEASE) -> bool:
    """Claim on ``db`` without committing, so the caller can roll it back."""
    won = db.execute(_CLAIM_SQL, _claim_bind(key, ttl)).first()
    return won is not None


def extend_dedupe_claim(key: str, *, ttl: timedelta = CLAIM_TTL) -> None:
    """Keep a claim for 24 hours after the provider accepts. Own transaction."""
    if not key:
        return
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        extend_dedupe_claim_on(db, key, ttl=ttl)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def extend_dedupe_claim_on(db: Session, key: str, *, ttl: timedelta = CLAIM_TTL) -> None:
    """Extend a claim on ``db`` without committing."""
    if not key:
        return
    db.execute(_EXTEND_SQL, {"key": key, "expires": datetime.now(timezone.utc) + ttl})


def release_dedupe_claim(key: str) -> None:
    """Mark a claim released so a later send can take it. Own transaction."""
    if not key:
        return
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        db.execute(
            text(
                """
                UPDATE notification_dedupe_claims
                SET released_at = :now
                WHERE dedupe_key = :key AND released_at IS NULL
                """
            ),
            {"key": key, "now": datetime.now(timezone.utc)},
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def prune_dedupe_claims(db: Session, now: datetime | None = None) -> int:
    """Delete expired or released claims. The worker runs this on its hourly pass."""
    from app.models.notification import NotificationDedupeClaim

    moment = now or datetime.now(timezone.utc)
    deleted = (
        db.query(NotificationDedupeClaim)
        .filter(
            (NotificationDedupeClaim.released_at.isnot(None))
            | (NotificationDedupeClaim.expires_at < moment)
        )
        .delete(synchronize_session=False)
    )
    return int(deleted or 0)


def _duplicate_send(key: str, event_id: str | None) -> bool:
    """True when this send must be recorded as deduped.

    No event id means do not dedupe. Otherwise the database claim decides.
    """
    if not (event_id or "").strip():
        return False
    return not claim_dedupe_key(key)


def _dedup_key(workspace_id: int, event_type: str, email: str, event_id: str | None = None) -> str:
    """Backward-compatible email key. Includes the email channel."""
    return stable_dedupe_key(workspace_id, event_type, "email", email, event_id)


def _safe(value: object, *, limit: int = 500) -> str:
    return redact_notification_text(value, limit=limit)


def _email_facts(provider: object) -> tuple[str, bool]:
    """Return (provider_mode, counts_as_real_provider).

    The console provider is the email dev stub. A successful console send is
    not delivery to a provider. SMTP is the real email provider.
    """
    if isinstance(provider, ConsoleEmailProvider):
        return "dev-stub", False
    if isinstance(provider, SmtpEmailProvider):
        return "smtp", True
    mode = getattr(provider, "provider_mode", None)
    if isinstance(mode, str) and mode:
        return mode, bool(getattr(provider, "counts_as_provider", False))
    return "email", False


def _email_retryable(exc: BaseException) -> bool:
    name = type(exc).__name__
    return name not in {"SMTPRecipientsRefused", "SMTPSenderRefused", "SMTPDataError"}


def resolve_recipient_rows(
    db: Session,
    workspace_id: int,
    policy: NotificationPolicy,
) -> list[tuple[int, str]]:
    """Resolve (user_id, email) pairs for a policy. Deduplicated by email."""
    rt = (policy.recipient_type or "").lower()

    def _rows(query):
        seen: set[str] = set()
        out: list[tuple[int, str]] = []
        for uid, email in query.all():
            if not email or email in seen:
                continue
            seen.add(email)
            out.append((int(uid), email))
        return out

    base = (
        db.query(User.id, User.email)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.suspended == False,  # noqa: E712
        )
    )

    if rt == "all":
        return _rows(base)

    if rt == "admins":
        return _rows(base.filter(WorkspaceMember.role == "admin"))

    if rt == "role":
        role_name = (policy.recipient_value or "").strip().lower()
        if not role_name:
            return []
        return _rows(base.filter(WorkspaceMember.role == role_name))

    if rt == "user":
        try:
            uid = int(policy.recipient_value or "0")
        except (ValueError, TypeError):
            return []
        u = db.query(User).filter(User.id == uid).first()
        if not u or not u.email:
            return []
        mem = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.user_id == uid,
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.suspended == False,  # noqa: E712
            )
            .first()
        )
        return [(u.id, u.email)] if mem else []

    return []


def resolve_recipients(
    db: Session,
    workspace_id: int,
    policy: NotificationPolicy,
) -> list[str]:
    """Resolve recipient emails based on policy type. Returns a deduplicated list."""
    return [email for _uid, email in resolve_recipient_rows(db, workspace_id, policy)]


def get_unsubscribed_emails(db: Session, workspace_id: int, event_type: str) -> set[str]:
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


def _add_attempt(
    db: Session,
    *,
    workspace_id: int,
    event_type: str,
    channel: str,
    recipient: str,
    user_id: int | None,
    dedupe_key: str,
    state: str,
    attempt_number: int,
    max_attempts: int,
    rendered: RenderedNotification | None = None,
    destination: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    delivered_to_provider: bool = False,
    provider_mode: str | None = None,
    in_app_notification_id: int | None = None,
    notification_log_id: int | None = None,
) -> NotificationDeliveryAttempt:
    body = rendered.body_text if rendered is not None else None
    row = NotificationDeliveryAttempt(
        workspace_id=workspace_id,
        event_type=event_type,
        channel=channel,
        recipient=_safe(recipient, limit=255),
        user_id=user_id,
        dedupe_key=_safe(dedupe_key, limit=512),
        state=state,
        attempt_number=attempt_number,
        max_attempts=max_attempts,
        error_code=_safe(error_code, limit=64) or None,
        error_message=_safe(error_message, limit=500) or None,
        delivered_to_provider=bool(delivered_to_provider),
        provider_mode=provider_mode,
        template_key=rendered.template_key if rendered is not None else None,
        rendered_subject=_safe(rendered.subject, limit=512) if rendered is not None else None,
        rendered_body=_safe(body, limit=2000) if body else None,
        destination=_safe(destination, limit=255) if destination else None,
        in_app_notification_id=in_app_notification_id,
        notification_log_id=notification_log_id,
    )
    db.add(row)
    return row


def _send_email_bounded(provider, message: EmailMessage, on_attempt) -> ProviderCallResult:
    seam = BoundedRetrySeam(
        max_attempts=DEFAULT_MAX_ATTEMPTS, sleeper=lambda _attempt, _retry_after: None
    )

    def attempt_call(attempt: int) -> ProviderCallResult:
        try:
            ok = bool(provider.send(message))
        except Exception as exc:
            logger.warning(
                "Notification email attempt failed event_channel=email retryable=%s",
                _email_retryable(exc),
            )
            return _fail(
                status_code=None,
                error_code="unknown",
                attempts=attempt,
                provider_error="email_send_failed",
                retryable=_email_retryable(exc),
                message="The email could not be sent.",
            )
        if ok:
            return ProviderCallResult(
                ok=True,
                status_code=None,
                body={},
                error_code=None,
                safe_message=None,
                retryable=False,
                attempts=attempt,
                provider_error=None,
            )
        return _fail(
            status_code=None,
            error_code="unknown",
            attempts=attempt,
            provider_error="email_rejected",
            retryable=True,
            message="The email provider did not accept the message.",
        )

    return seam.run_results(attempt_call, on_attempt=on_attempt)


def _deliver_email(
    db: Session,
    *,
    workspace_id: int,
    event_type: str,
    user_id: int,
    email: str,
    rendered: RenderedNotification,
    provider,
    event_id: str | None = None,
) -> bool:
    mode, counts_as_provider = _email_facts(provider)
    destination = email
    key = stable_dedupe_key(workspace_id, event_type, "email", email, event_id)
    if preference_block_reason(db, workspace_id, user_id, "email", event_type):
        _add_attempt(
            db,
            workspace_id=workspace_id,
            event_type=event_type,
            channel="email",
            recipient=email,
            user_id=user_id,
            dedupe_key=key,
            state=STATE_SUPPRESSED,
            attempt_number=0,
            max_attempts=DEFAULT_MAX_ATTEMPTS,
            rendered=rendered,
            destination=destination,
            provider_mode=mode,
        )
        return False
    claimed = _duplicate_send(key, event_id)
    if claimed:
        _add_attempt(
            db,
            workspace_id=workspace_id,
            event_type=event_type,
            channel="email",
            recipient=email,
            user_id=user_id,
            dedupe_key=key,
            state=STATE_DEDUPED,
            attempt_number=0,
            max_attempts=DEFAULT_MAX_ATTEMPTS,
            rendered=rendered,
            destination=destination,
            error_code=DEDUPE_ERROR_CODE,
            provider_mode=mode,
        )
        return False
    hold_claim = bool((event_id or "").strip())

    _add_attempt(
        db,
        workspace_id=workspace_id,
        event_type=event_type,
        channel="email",
        recipient=email,
        user_id=user_id,
        dedupe_key=key,
        state=STATE_QUEUED,
        attempt_number=0,
        max_attempts=DEFAULT_MAX_ATTEMPTS,
        rendered=rendered,
        destination=destination,
        provider_mode=mode,
    )

    def on_attempt(result: ProviderCallResult, will_retry: bool) -> None:
        if not will_retry:
            return
        _add_attempt(
            db,
            workspace_id=workspace_id,
            event_type=event_type,
            channel="email",
            recipient=email,
            user_id=user_id,
            dedupe_key=key,
            state=STATE_RETRYING,
            attempt_number=result.attempts,
            max_attempts=DEFAULT_MAX_ATTEMPTS,
            rendered=rendered,
            destination=destination,
            error_code=result.error_code,
            error_message=result.safe_message,
            provider_mode=mode,
        )

    message = EmailMessage(
        to=email,
        subject=rendered.subject,
        body_text=rendered.body_text,
        body_html=rendered.body_html,
    )
    try:
        result = _send_email_bounded(provider, message, on_attempt)
    except Exception:
        if hold_claim:
            release_dedupe_claim(key)
        raise
    accepted = bool(result.ok)
    if hold_claim:
        if accepted:
            extend_dedupe_claim(key)
        else:
            release_dedupe_claim(key)
    delivered = bool(accepted and counts_as_provider)
    final_state = STATE_SENT if accepted else STATE_DEAD
    error_message = (
        None if accepted else _safe(result.safe_message or "The email could not be sent.")
    )
    log = NotificationLog(
        workspace_id=workspace_id,
        event_type=event_type,
        channel="email",
        recipient_email=_safe(email, limit=255),
        subject=_safe(rendered.subject, limit=512),
        status="sent" if accepted else "failed",
        error=error_message,
        delivery_state=final_state,
        delivered_to_provider=delivered,
        provider_mode=mode,
        dedupe_key=key,
        attempt_count=result.attempts,
    )
    db.add(log)
    db.flush()
    _add_attempt(
        db,
        workspace_id=workspace_id,
        event_type=event_type,
        channel="email",
        recipient=email,
        user_id=user_id,
        dedupe_key=key,
        state=final_state,
        attempt_number=result.attempts,
        max_attempts=DEFAULT_MAX_ATTEMPTS,
        rendered=rendered,
        destination=destination,
        error_code=None if accepted else result.error_code,
        error_message=error_message,
        delivered_to_provider=delivered,
        provider_mode=mode,
        notification_log_id=log.id,
    )
    return accepted


def _deliver_in_app(
    db: Session,
    *,
    workspace_id: int,
    event_type: str,
    user_id: int,
    email: str,
    rendered: RenderedNotification,
    event_id: str | None = None,
) -> bool:
    destination = f"user:{user_id}"
    key = stable_dedupe_key(workspace_id, event_type, "in_app", destination, event_id)
    if preference_block_reason(db, workspace_id, user_id, "in_app", event_type):
        _add_attempt(
            db,
            workspace_id=workspace_id,
            event_type=event_type,
            channel="in_app",
            recipient=email,
            user_id=user_id,
            dedupe_key=key,
            state=STATE_SUPPRESSED,
            attempt_number=0,
            max_attempts=1,
            rendered=rendered,
            destination=destination,
            provider_mode="local",
        )
        return False
    if not channel_enabled(db, workspace_id, user_id, "in_app", event_type):
        return False
    note_id = None
    try:
        with db.begin_nested():
            if (event_id or "").strip() and not claim_dedupe_key_on(db, key):
                raise _ClaimLost()
            _add_attempt(
                db,
                workspace_id=workspace_id,
                event_type=event_type,
                channel="in_app",
                recipient=email,
                user_id=user_id,
                dedupe_key=key,
                state=STATE_QUEUED,
                attempt_number=0,
                max_attempts=1,
                rendered=rendered,
                destination=destination,
                provider_mode="local",
            )
            note = InAppNotification(
                workspace_id=workspace_id,
                user_id=user_id,
                title=_safe(rendered.title, limit=255),
                body=_safe(rendered.body_text, limit=2000),
                category=rendered.category,
                link=rendered.link,
                is_read=False,
                admin_only=False,
            )
            db.add(note)
            db.flush()
            note_id = note.id
            if (event_id or "").strip():
                extend_dedupe_claim_on(db, key)
    except _ClaimLost:
        _add_attempt(
            db,
            workspace_id=workspace_id,
            event_type=event_type,
            channel="in_app",
            recipient=email,
            user_id=user_id,
            dedupe_key=key,
            state=STATE_DEDUPED,
            attempt_number=0,
            max_attempts=1,
            rendered=rendered,
            destination=destination,
            error_code=DEDUPE_ERROR_CODE,
            provider_mode="local",
        )
        return False
    except Exception:
        logger.warning(
            "In-app notification insert failed workspace=%s event=%s", workspace_id, event_type
        )
        _add_attempt(
            db,
            workspace_id=workspace_id,
            event_type=event_type,
            channel="in_app",
            recipient=email,
            user_id=user_id,
            dedupe_key=key,
            state=STATE_DEAD,
            attempt_number=1,
            max_attempts=1,
            rendered=rendered,
            destination=destination,
            error_code="unknown",
            error_message="The in-app notification could not be stored.",
            provider_mode="local",
        )
        return False

    _add_attempt(
        db,
        workspace_id=workspace_id,
        event_type=event_type,
        channel="in_app",
        recipient=email,
        user_id=user_id,
        dedupe_key=key,
        state=STATE_SENT,
        attempt_number=1,
        max_attempts=1,
        rendered=rendered,
        destination=destination,
        delivered_to_provider=False,
        provider_mode="local",
        in_app_notification_id=note_id,
    )
    return True


def _slack_event_allowed(si: SlackIntegration, event_type: str) -> bool:
    if not si.event_types:
        return True
    try:
        enabled_types = json.loads(si.event_types)
    except (json.JSONDecodeError, TypeError):
        return True
    if not enabled_types:
        return True
    return event_type in enabled_types


def _fire_slack_notification(
    db: Session,
    workspace_id: int,
    event_type: str,
    recipients: list[tuple[int, str]],
    rendered: RenderedNotification,
    event_id: str | None = None,
) -> int:
    """Post once to the workspace Slack channel when at least one recipient allows it."""
    channel_key = ""
    hold_claim = False
    send_started = False
    accepted_post = False
    try:
        si = (
            db.query(SlackIntegration)
            .filter(
                SlackIntegration.workspace_id == workspace_id,
                SlackIntegration.enabled == True,  # noqa: E712
            )
            .first()
        )
        if not si or not _slack_event_allowed(si, event_type):
            return 0

        allowed = [
            (uid, email)
            for uid, email in recipients
            if channel_enabled(db, workspace_id, uid, "slack", event_type)
        ]
        suppressed = [
            (uid, email)
            for uid, email in recipients
            if preference_block_reason(db, workspace_id, uid, "slack", event_type)
        ]
        destination = si.channel_id
        channel_key = stable_dedupe_key(workspace_id, event_type, "slack", destination, event_id)
        for uid, email in suppressed:
            user_key = stable_dedupe_key(workspace_id, event_type, "slack", f"user:{uid}", event_id)
            _add_attempt(
                db,
                workspace_id=workspace_id,
                event_type=event_type,
                channel="slack",
                recipient=email,
                user_id=uid,
                dedupe_key=user_key,
                state=STATE_SUPPRESSED,
                attempt_number=0,
                max_attempts=DEFAULT_MAX_ATTEMPTS,
                rendered=rendered,
                destination=destination,
                provider_mode=None,
            )
        if not allowed:
            return 0

        if _duplicate_send(channel_key, event_id):
            _add_attempt(
                db,
                workspace_id=workspace_id,
                event_type=event_type,
                channel="slack",
                recipient=f"#{si.channel_name or si.channel_id}",
                user_id=None,
                dedupe_key=channel_key,
                state=STATE_DEDUPED,
                attempt_number=0,
                max_attempts=DEFAULT_MAX_ATTEMPTS,
                rendered=rendered,
                destination=destination,
                error_code=DEDUPE_ERROR_CODE,
            )
            return 0
        hold_claim = bool((event_id or "").strip())

        label = f"#{si.channel_name or si.channel_id}"
        _add_attempt(
            db,
            workspace_id=workspace_id,
            event_type=event_type,
            channel="slack",
            recipient=label,
            user_id=None,
            dedupe_key=channel_key,
            state=STATE_QUEUED,
            attempt_number=0,
            max_attempts=DEFAULT_MAX_ATTEMPTS,
            rendered=rendered,
            destination=destination,
        )

        def on_attempt(result: ProviderCallResult, will_retry: bool) -> None:
            if not will_retry:
                return
            _add_attempt(
                db,
                workspace_id=workspace_id,
                event_type=event_type,
                channel="slack",
                recipient=label,
                user_id=None,
                dedupe_key=channel_key,
                state=STATE_RETRYING,
                attempt_number=result.attempts,
                max_attempts=DEFAULT_MAX_ATTEMPTS,
                rendered=rendered,
                destination=destination,
                error_code=result.error_code,
                error_message=result.safe_message,
                provider_mode="http",
            )

        token = decrypt_token(si.bot_token_encrypted)
        provider = get_slack_provider()
        send_started = True
        result = provider.send_message(
            token, si.channel_id, rendered.slack_text, on_attempt=on_attempt
        )
        accepted = delivery_accepted(result)
        if accepted:
            accepted_post = True
            if hold_claim:
                extend_dedupe_claim(channel_key)
        elif hold_claim:
            release_dedupe_claim(channel_key)
        delivered = bool(accepted and result.get("delivered_to_provider") is True)
        mode = result.get("provider_mode") if isinstance(result.get("provider_mode"), str) else None
        attempts = result.get("attempts") if isinstance(result.get("attempts"), int) else 1
        error_message = None
        error_code = None
        if not accepted:
            error_message = _safe(
                public_error_detail(result, "The Slack message was not accepted.")
            )
            raw_code = result.get("error_code")
            error_code = raw_code if isinstance(raw_code, str) else "unknown"
        final_state = STATE_SENT if accepted else STATE_DEAD
        log = NotificationLog(
            workspace_id=workspace_id,
            event_type=event_type,
            channel="slack",
            recipient_email=_safe(label, limit=255),
            subject=_safe(rendered.subject, limit=512),
            status="sent" if accepted else "failed",
            error=error_message,
            delivery_state=final_state,
            delivered_to_provider=delivered,
            provider_mode=mode,
            dedupe_key=channel_key,
            attempt_count=attempts,
        )
        db.add(log)
        db.flush()
        _add_attempt(
            db,
            workspace_id=workspace_id,
            event_type=event_type,
            channel="slack",
            recipient=label,
            user_id=None,
            dedupe_key=channel_key,
            state=final_state,
            attempt_number=attempts,
            max_attempts=DEFAULT_MAX_ATTEMPTS,
            rendered=rendered,
            destination=destination,
            error_code=error_code,
            error_message=error_message,
            delivered_to_provider=delivered,
            provider_mode=mode,
            notification_log_id=log.id,
        )
        if not accepted:
            logger.warning(
                "Slack delivery failed workspace=%s channel=%s code=%s",
                workspace_id,
                si.channel_id,
                error_code,
            )
            try:
                from app.services.in_app_notification_service import notify_admins

                notify_admins(
                    db,
                    workspace_id,
                    "Slack delivery failed",
                    f"Event '{event_type}' failed to deliver to Slack: {error_message}",
                    category="error",
                    link="/dashboard/notifications",
                )
            except Exception:
                pass
        return 1 if accepted else 0
    except Exception:
        if hold_claim and not accepted_post and not send_started:
            release_dedupe_claim(channel_key)
        logger.warning("Slack notification error workspace=%s event=%s", workspace_id, event_type)
        try:
            safe_error = "The Slack message could not be sent."
            db.add(
                NotificationLog(
                    workspace_id=workspace_id,
                    event_type=event_type,
                    channel="slack",
                    recipient_email="slack-error",
                    subject=event_type,
                    status="failed",
                    error=safe_error,
                    delivery_state=STATE_DEAD,
                    delivered_to_provider=False,
                    provider_mode=None,
                    attempt_count=1,
                )
            )
            _add_attempt(
                db,
                workspace_id=workspace_id,
                event_type=event_type,
                channel="slack",
                recipient="slack-error",
                user_id=None,
                dedupe_key=stable_dedupe_key(
                    workspace_id, event_type, "slack", "slack-error", event_id
                ),
                state=STATE_DEAD,
                attempt_number=1,
                max_attempts=DEFAULT_MAX_ATTEMPTS,
                error_code="unknown",
                error_message=safe_error,
                delivered_to_provider=False,
            )
        except Exception:
            pass
        return 0


def fire_notification(
    db: Session,
    workspace_id: int,
    event_type: str,
    detail: str = "",
    workspace_name: str = "Workspace",
    event_id: str | None = None,
) -> int:
    """
    Fire a notification for the given event type.

    Looks up the policy, resolves recipients, applies channel preferences and
    the event unsubscribe list, renders one template, and records each delivery
    state. Returns the number of email and Slack deliveries accepted locally.
    A dev stub acceptance counts here and is stored with delivered_to_provider false.
    """
    if event_type not in NOTIFICATION_EVENT_TYPES:
        return 0

    policy = (
        db.query(NotificationPolicy)
        .filter(
            NotificationPolicy.workspace_id == workspace_id,
            NotificationPolicy.event_type == event_type,
            NotificationPolicy.enabled == True,  # noqa: E712
        )
        .first()
    )
    if not policy:
        return 0

    recipients = resolve_recipient_rows(db, workspace_id, policy)
    if not recipients:
        return 0

    provider = get_email_provider()
    sent = 0
    for user_id, email in recipients:
        rendered = render_notification(event_type, "email", workspace_name, detail)
        if _deliver_email(
            db,
            workspace_id=workspace_id,
            event_type=event_type,
            user_id=user_id,
            email=email,
            rendered=rendered,
            provider=provider,
            event_id=event_id,
        ):
            sent += 1
        in_app = render_notification(event_type, "in_app", workspace_name, detail)
        _deliver_in_app(
            db,
            workspace_id=workspace_id,
            event_type=event_type,
            user_id=user_id,
            email=email,
            rendered=in_app,
            event_id=event_id,
        )

    slack_rendered = render_notification(event_type, "slack", workspace_name, detail)
    sent += _fire_slack_notification(
        db, workspace_id, event_type, recipients, slack_rendered, event_id
    )

    try:
        db.commit()
    except Exception:
        db.rollback()

    return sent
