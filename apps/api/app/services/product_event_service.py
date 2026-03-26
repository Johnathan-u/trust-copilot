"""Product event service (P0-86) — track and query usage events."""

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.product_event import ProductEvent

logger = logging.getLogger(__name__)

EVENT_CATEGORIES = ("auth", "document", "questionnaire", "answer", "export", "trust_center", "connector", "billing", "admin")


def track(
    db: Session,
    workspace_id: int,
    event_type: str,
    *,
    user_id: int | None = None,
    event_category: str = "general",
    resource_type: str | None = None,
    resource_id: int | None = None,
    metadata: dict | None = None,
) -> None:
    """Record a product event."""
    db.add(ProductEvent(
        workspace_id=workspace_id,
        user_id=user_id,
        event_type=event_type,
        event_category=event_category,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata_json=json.dumps(metadata) if metadata else None,
    ))
    db.flush()


def get_event_counts(
    db: Session,
    workspace_id: int,
    days: int = 30,
) -> dict:
    """Get event counts grouped by type for the last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(ProductEvent.event_type, func.count(ProductEvent.id))
        .filter(ProductEvent.workspace_id == workspace_id, ProductEvent.created_at >= cutoff)
        .group_by(ProductEvent.event_type)
        .all()
    )
    return {r[0]: r[1] for r in rows}


def get_category_counts(db: Session, workspace_id: int, days: int = 30) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(ProductEvent.event_category, func.count(ProductEvent.id))
        .filter(ProductEvent.workspace_id == workspace_id, ProductEvent.created_at >= cutoff)
        .group_by(ProductEvent.event_category)
        .all()
    )
    return {r[0]: r[1] for r in rows}


def get_daily_activity(db: Session, workspace_id: int, days: int = 14) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(
            func.date(ProductEvent.created_at).label("day"),
            func.count(ProductEvent.id).label("count"),
        )
        .filter(ProductEvent.workspace_id == workspace_id, ProductEvent.created_at >= cutoff)
        .group_by(func.date(ProductEvent.created_at))
        .order_by(func.date(ProductEvent.created_at))
        .all()
    )
    return [{"date": str(r.day), "events": r.count} for r in rows]


def get_funnel(db: Session, workspace_id: int, days: int = 30) -> dict:
    """Get simple product funnel: logins -> uploads -> answers -> exports."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    base = db.query(func.count(ProductEvent.id)).filter(
        ProductEvent.workspace_id == workspace_id,
        ProductEvent.created_at >= cutoff,
    )
    return {
        "logins": base.filter(ProductEvent.event_type == "auth.login").scalar() or 0,
        "document_uploads": base.filter(ProductEvent.event_type == "document.upload").scalar() or 0,
        "questionnaire_uploads": base.filter(ProductEvent.event_type == "questionnaire.upload").scalar() or 0,
        "answers_generated": base.filter(ProductEvent.event_type == "answer.generate").scalar() or 0,
        "exports": base.filter(ProductEvent.event_type == "export.complete").scalar() or 0,
    }
