"""One template source for notification copy.

Email, Slack, and in-app all render through ``render_notification``. Channel
wrappers differ. The label and the redacted detail do not.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from app.services.notification_redaction import redact_notification_text

# Single copy table. Do not duplicate these strings in a sender.
_EVENT_LABELS = {
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

IN_APP_LINK = "/dashboard/notifications"


def event_label(event_type: str) -> str:
    return _EVENT_LABELS.get(event_type, event_type)


def _category(event_type: str) -> str:
    if event_type.startswith("compliance."):
        return "warning"
    if event_type.startswith("member.") or event_type.startswith("role."):
        return "admin"
    return "info"


@dataclass(frozen=True)
class RenderedNotification:
    template_key: str
    event_type: str
    channel: str
    label: str
    subject: str
    title: str
    body_text: str
    body_html: str
    slack_text: str
    link: str
    category: str


def render_notification(
    event_type: str,
    channel: str,
    workspace_name: str = "Workspace",
    detail: str = "",
) -> RenderedNotification:
    """Render one event for one channel from the shared label table."""
    label = event_label(event_type)
    safe_detail = redact_notification_text(detail or "", limit=240)
    safe_workspace = (
        redact_notification_text(workspace_name or "Workspace", limit=80) or "Workspace"
    )
    subject = f"[{safe_workspace}] {label}"
    if safe_detail:
        subject = f"{subject} — {safe_detail}"
    subject = subject[:512]
    body_text = f"{subject}\n\nEvent: {event_type}"
    if safe_detail:
        body_text = f"{body_text}\n{safe_detail}"
    body_html = (
        f"<p><strong>{html.escape(subject)}</strong></p>"
        f"<p>{html.escape(safe_detail or event_type)}</p>"
    )
    slack_text = f"*{subject}*\n{safe_detail}" if safe_detail else subject
    return RenderedNotification(
        template_key=f"{event_type}:{channel}",
        event_type=event_type,
        channel=channel,
        label=label,
        subject=subject,
        title=label[:255],
        body_text=body_text,
        body_html=body_html,
        slack_text=slack_text,
        link=IN_APP_LINK,
        category=_category(event_type),
    )
