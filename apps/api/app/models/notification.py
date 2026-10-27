"""Phase C: Workspace notification policies, delivery log, and per-user unsubscribes."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.core.database import Base


NOTIFICATION_EVENT_TYPES = [
    "compliance.coverage_drop",
    "compliance.blind_spot",
    "compliance.high_insufficient",
    "compliance.weak_evidence",
    "questionnaire.uploaded",
    "questionnaire.generated",
    "export.completed",
    "document.indexed",
    "member.invited",
    "member.joined",
    "member.removed",
    "member.suspended",
    "member.role_changed",
    "role.created",
    "role.updated",
    "role.deleted",
]

RECIPIENT_TYPES = ["all", "admins", "role", "user"]

NOTIFICATION_CHANNELS = ("email", "slack", "in_app")

# Visible on each delivery attempt. Hyphenated names match the acceptance wording.
DELIVERY_STATES = (
    "queued",
    "sent",
    "retrying",
    "deduped",
    "dead-lettered",
    "suppressed-by-preference",
)

# No preference row: email and Slack stay on (today's behavior). In-app through
# the shared dispatcher stays off until the user enables it, because existing
# feature code already writes the bell. TC-19-010 owns the personal inbox.
IN_APP_DEFAULT_ENABLED = False


class NotificationPolicy(Base):
    """Per-workspace policy: which events trigger email notifications and to whom."""

    __tablename__ = "notification_policies"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type = Column(String(64), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    recipient_type = Column(String(32), nullable=False, default="admins")
    recipient_value = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class NotificationLog(Base):
    """Delivery log: every notification attempt with status and error detail."""

    __tablename__ = "notification_log"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type = Column(String(64), nullable=False, index=True)
    channel = Column(String(16), nullable=False, default="email")
    recipient_email = Column(String(255), nullable=False)
    subject = Column(String(512), nullable=True)
    status = Column(String(16), nullable=False, default="sent")
    error = Column(Text, nullable=True)
    delivery_state = Column(String(32), nullable=True)
    delivered_to_provider = Column(Boolean, nullable=False, default=False)
    provider_mode = Column(String(32), nullable=True)
    dedupe_key = Column(String(512), nullable=True)
    attempt_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class NotificationUnsubscribe(Base):
    """Per-user opt-out from specific event types in a workspace."""

    __tablename__ = "notification_unsubscribes"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class NotificationDedupeClaim(Base):
    """One database claim for a dedupe key.

    Attempt rows stay non-unique. A live claim blocks a second send until it
    is released or ``expires_at`` passes.
    """

    __tablename__ = "notification_dedupe_claims"

    dedupe_key = Column(String(512), primary_key=True)
    claimed_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    released_at = Column(DateTime(timezone=True), nullable=True)


class NotificationChannelPreference(Base):
    """Per-user email, Slack, or in-app preference.

    ``event_type`` is empty when the row applies to every event on that channel.
    A specific event row overrides the channel-wide row.
    """

    __tablename__ = "notification_channel_preferences"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "user_id",
            "channel",
            "event_type",
            name="uq_notification_channel_pref",
        ),
    )

    id = Column(Integer, primary_key=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel = Column(String(16), nullable=False)
    event_type = Column(String(64), nullable=False, default="")
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class NotificationDeliveryAttempt(Base):
    """One visible state of a delivery try.

    States are queued, sent, retrying, deduped, dead-lettered, and
    suppressed-by-preference. ``deduped`` means a database claim was already
    held. Several rows share one dedupe key, so the column is indexed and
    not unique. Stored text is redacted before insert.
    """

    __tablename__ = "notification_delivery_attempts"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type = Column(String(64), nullable=False, index=True)
    channel = Column(String(16), nullable=False)
    recipient = Column(String(255), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    dedupe_key = Column(String(512), nullable=False, index=True)
    state = Column(String(32), nullable=False)
    attempt_number = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=1)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    delivered_to_provider = Column(Boolean, nullable=False, default=False)
    provider_mode = Column(String(32), nullable=True)
    template_key = Column(String(96), nullable=True)
    rendered_subject = Column(String(512), nullable=True)
    rendered_body = Column(Text, nullable=True)
    destination = Column(String(255), nullable=True)
    in_app_notification_id = Column(
        Integer, ForeignKey("in_app_notifications.id", ondelete="SET NULL"), nullable=True
    )
    notification_log_id = Column(
        Integer, ForeignKey("notification_log.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
