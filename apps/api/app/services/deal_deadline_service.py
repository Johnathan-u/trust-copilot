"""Due-date tracking and deadline alerts (E1-06)."""

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.deal import Deal

logger = logging.getLogger(__name__)


def get_upcoming_deadlines(db: Session, workspace_id: int, within_days: int = 14) -> list[dict]:
    now = datetime.now(timezone.utc)
    threshold = now + timedelta(days=within_days)
    deals = db.query(Deal).filter(
        Deal.workspace_id == workspace_id,
        Deal.close_date.isnot(None),
        Deal.stage.notin_(["closed_won", "closed_lost"]),
    ).all()

    upcoming = []
    for deal in deals:
        close = deal.close_date
        if close.tzinfo is None:
            close = close.replace(tzinfo=timezone.utc)
        if close <= threshold:
            days_until = (close - now).days
            upcoming.append({
                "deal_id": deal.id,
                "company_name": deal.company_name,
                "deal_value_arr": deal.deal_value_arr,
                "stage": deal.stage,
                "close_date": deal.close_date.isoformat(),
                "days_until_close": max(days_until, 0),
                "overdue": days_until < 0,
            })
    upcoming.sort(key=lambda d: d["days_until_close"])
    return upcoming


def get_overdue_deals(db: Session, workspace_id: int) -> list[dict]:
    now = datetime.now(timezone.utc)
    deals = db.query(Deal).filter(
        Deal.workspace_id == workspace_id,
        Deal.close_date.isnot(None),
        Deal.stage.notin_(["closed_won", "closed_lost"]),
    ).all()

    overdue = []
    for deal in deals:
        close = deal.close_date
        if close.tzinfo is None:
            close = close.replace(tzinfo=timezone.utc)
        if close < now:
            days_overdue = (now - close).days
            overdue.append({
                "deal_id": deal.id,
                "company_name": deal.company_name,
                "deal_value_arr": deal.deal_value_arr,
                "stage": deal.stage,
                "close_date": deal.close_date.isoformat(),
                "days_overdue": days_overdue,
            })
    overdue.sort(key=lambda d: d["days_overdue"], reverse=True)
    return overdue


def get_deals_at_risk_this_week(db: Session, workspace_id: int) -> list[dict]:
    return get_upcoming_deadlines(db, workspace_id, within_days=7)
