"""Alert acknowledgement, snooze, and override service (P1-38, P1-39)."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.alert_acknowledgment import AlertAcknowledgment

VALID_ACTIONS = ("acknowledge", "snooze", "accept_risk", "override", "dismiss")


def acknowledge(
    db: Session,
    workspace_id: int,
    alert_type: str,
    action: str,
    *,
    control_id: int | None = None,
    reason: str | None = None,
    snooze_hours: int | None = None,
    user_id: int | None = None,
) -> dict:
    if action not in VALID_ACTIONS:
        return {"error": f"Invalid action. Valid: {', '.join(VALID_ACTIONS)}"}

    snoozed_until = None
    if action == "snooze" and snooze_hours:
        snoozed_until = datetime.now(timezone.utc) + timedelta(hours=snooze_hours)

    ack = AlertAcknowledgment(
        workspace_id=workspace_id,
        control_id=control_id,
        alert_type=alert_type,
        action=action,
        reason=reason,
        snoozed_until=snoozed_until,
        acknowledged_by=user_id,
    )
    db.add(ack)
    db.flush()
    return _serialize(ack)


def list_acknowledgments(
    db: Session,
    workspace_id: int,
    control_id: int | None = None,
    active_only: bool = False,
) -> list[dict]:
    q = db.query(AlertAcknowledgment).filter(AlertAcknowledgment.workspace_id == workspace_id)
    if control_id:
        q = q.filter(AlertAcknowledgment.control_id == control_id)
    if active_only:
        now = datetime.now(timezone.utc)
        q = q.filter(
            (AlertAcknowledgment.snoozed_until.is_(None)) |
            (AlertAcknowledgment.snoozed_until > now)
        )
    return [_serialize(a) for a in q.order_by(AlertAcknowledgment.created_at.desc()).all()]


def is_snoozed(db: Session, workspace_id: int, control_id: int) -> bool:
    now = datetime.now(timezone.utc)
    return db.query(AlertAcknowledgment).filter(
        AlertAcknowledgment.workspace_id == workspace_id,
        AlertAcknowledgment.control_id == control_id,
        AlertAcknowledgment.action == "snooze",
        AlertAcknowledgment.snoozed_until > now,
    ).first() is not None


def _serialize(ack: AlertAcknowledgment) -> dict:
    return {
        "id": ack.id,
        "workspace_id": ack.workspace_id,
        "control_id": ack.control_id,
        "alert_type": ack.alert_type,
        "action": ack.action,
        "reason": ack.reason,
        "snoozed_until": ack.snoozed_until.isoformat() if ack.snoozed_until else None,
        "acknowledged_by": ack.acknowledged_by,
        "created_at": ack.created_at.isoformat() if ack.created_at else None,
    }
