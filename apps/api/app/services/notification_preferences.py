"""Per-user channel and event delivery preferences.

Email and Slack are enabled when the user has no row. In-app delivery from the
shared dispatcher is disabled until the user enables that channel. An event
unsubscribe suppresses that event on every channel for that user.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.notification import (
    IN_APP_DEFAULT_ENABLED,
    NOTIFICATION_CHANNELS,
    NotificationChannelPreference,
    NotificationUnsubscribe,
)


def _stored_enabled(
    db: Session,
    workspace_id: int,
    user_id: int,
    channel: str,
    event_type: str,
) -> bool | None:
    row = (
        db.query(NotificationChannelPreference)
        .filter(
            NotificationChannelPreference.workspace_id == workspace_id,
            NotificationChannelPreference.user_id == user_id,
            NotificationChannelPreference.channel == channel,
            NotificationChannelPreference.event_type == event_type,
        )
        .first()
    )
    if row is None:
        return None
    return bool(row.enabled)


def event_unsubscribed(db: Session, workspace_id: int, user_id: int, event_type: str) -> bool:
    if not event_type:
        return False
    row = (
        db.query(NotificationUnsubscribe.id)
        .filter(
            NotificationUnsubscribe.workspace_id == workspace_id,
            NotificationUnsubscribe.user_id == user_id,
            NotificationUnsubscribe.event_type == event_type,
        )
        .first()
    )
    return row is not None


def preference_block_reason(
    db: Session,
    workspace_id: int,
    user_id: int | None,
    channel: str,
    event_type: str,
) -> str | None:
    """Why this user opted out, or None when they did not.

    ``unsubscribed`` is an event opt-out. ``preference`` is a channel or
    channel-and-event row set to disabled. A missing in-app row is not an
    opt-out: the dispatcher simply does not fan out until the user enables it.
    """
    if not user_id:
        return None
    if event_unsubscribed(db, workspace_id, user_id, event_type):
        return "unsubscribed"
    specific = _stored_enabled(db, workspace_id, user_id, channel, event_type)
    if specific is False:
        return "preference"
    if specific is True:
        return None
    channel_wide = _stored_enabled(db, workspace_id, user_id, channel, "")
    if channel_wide is False:
        return "preference"
    return None


def channel_enabled(
    db: Session,
    workspace_id: int,
    user_id: int | None,
    channel: str,
    event_type: str,
) -> bool:
    """True when this user may receive this event on this channel."""
    if preference_block_reason(db, workspace_id, user_id, channel, event_type):
        return False
    if user_id:
        specific = _stored_enabled(db, workspace_id, user_id, channel, event_type)
        if specific is not None:
            return specific
        channel_wide = _stored_enabled(db, workspace_id, user_id, channel, "")
        if channel_wide is not None:
            return channel_wide
    if channel == "in_app":
        return IN_APP_DEFAULT_ENABLED
    return True


def effective_channels(db: Session, workspace_id: int, user_id: int) -> dict[str, bool]:
    """Channel-wide switches, ignoring a single-event unsubscribe."""
    out: dict[str, bool] = {}
    for channel in NOTIFICATION_CHANNELS:
        stored = _stored_enabled(db, workspace_id, user_id, channel, "")
        if stored is not None:
            out[channel] = stored
        elif channel == "in_app":
            out[channel] = IN_APP_DEFAULT_ENABLED
        else:
            out[channel] = True
    return out


def list_preferences(
    db: Session, workspace_id: int, user_id: int
) -> list[NotificationChannelPreference]:
    return (
        db.query(NotificationChannelPreference)
        .filter(
            NotificationChannelPreference.workspace_id == workspace_id,
            NotificationChannelPreference.user_id == user_id,
        )
        .order_by(NotificationChannelPreference.channel, NotificationChannelPreference.event_type)
        .all()
    )


def set_channel_preference(
    db: Session,
    workspace_id: int,
    user_id: int,
    channel: str,
    enabled: bool,
    event_type: str | None = None,
) -> NotificationChannelPreference:
    et = (event_type or "").strip()
    row = (
        db.query(NotificationChannelPreference)
        .filter(
            NotificationChannelPreference.workspace_id == workspace_id,
            NotificationChannelPreference.user_id == user_id,
            NotificationChannelPreference.channel == channel,
            NotificationChannelPreference.event_type == et,
        )
        .first()
    )
    if row is None:
        row = NotificationChannelPreference(
            workspace_id=workspace_id,
            user_id=user_id,
            channel=channel,
            event_type=et,
            enabled=enabled,
        )
        db.add(row)
    else:
        row.enabled = enabled
    return row
