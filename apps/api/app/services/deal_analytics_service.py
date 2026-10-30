"""Deal-linked analytics (E1-07).

Track deals closed with Trust Copilot, average time-to-close, and revenue unblocked.
"""

import json  # noqa: F401
import logging
from datetime import datetime, timezone  # noqa: F401
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.deal import Deal
from app.services.deal_service import money_text

logger = logging.getLogger(__name__)


def get_analytics(db: Session, workspace_id: int) -> dict:
    deals = db.query(Deal).filter(Deal.workspace_id == workspace_id).all()
    total = len(deals)
    won = [d for d in deals if d.stage == "closed_won"]
    lost = [d for d in deals if d.stage == "closed_lost"]
    active = [d for d in deals if d.stage not in ("closed_won", "closed_lost")]

    revenue_won = _sum_amounts(won)
    revenue_pipeline = _sum_amounts(active)

    avg_close_days = None
    if won:
        close_times = []
        for d in won:
            if d.close_date and d.created_at:
                delta = (d.close_date - d.created_at).days
                close_times.append(delta)
        if close_times:
            avg_close_days = round(sum(close_times) / len(close_times), 1)

    by_stage = {}
    for d in deals:
        by_stage[d.stage] = by_stage.get(d.stage, 0) + 1

    return {
        "total_deals": total,
        "closed_won": len(won),
        "closed_lost": len(lost),
        "active": len(active),
        "revenue_won": revenue_won["amount"],
        "revenue_won_currency": revenue_won["currency"],
        "revenue_won_unavailable_reason": revenue_won["unavailable_reason"],
        "revenue_pipeline": revenue_pipeline["amount"],
        "revenue_pipeline_currency": revenue_pipeline["currency"],
        "revenue_pipeline_unavailable_reason": revenue_pipeline["unavailable_reason"],
        "avg_close_days": avg_close_days,
        "by_stage": by_stage,
        "win_rate": _win_rate(len(won), len(lost)),
    }


def _sum_amounts(deals: list[Deal]) -> dict:
    """Sum stored amounts only when their currency is known and identical.

    Missing amounts remain excluded. The empty sum is still 0.00, with no
    inferred currency; unavailable totals are null, never a converted value.
    """
    valued = [deal for deal in deals if deal.deal_value_arr is not None]
    currencies = {deal.currency for deal in valued}
    reason = None
    if None in currencies:
        reason = "unknown_currency"
    elif len(currencies) > 1:
        reason = "mixed_currency"
    if reason:
        return {"amount": None, "currency": None, "unavailable_reason": reason}
    total = sum((Decimal(deal.deal_value_arr) for deal in valued), Decimal("0.00"))
    return {
        "amount": format(total.quantize(Decimal("0.01")), "f"),
        "currency": next(iter(currencies), None),
        "unavailable_reason": None,
    }


def _win_rate(won: int, lost: int) -> str | None:
    """Won share of stored closed deals. None when nothing has closed."""
    closed = won + lost
    if closed == 0:
        return None
    rate = (Decimal(won) * Decimal(100) / Decimal(closed)).quantize(Decimal("0.1"))
    return format(rate, "f")


def get_revenue_unblocked(db: Session, workspace_id: int) -> dict:
    won = (
        db.query(Deal)
        .filter(
            Deal.workspace_id == workspace_id,
            Deal.stage == "closed_won",
        )
        .all()
    )
    revenue = _sum_amounts(won)
    return {
        "total_revenue_unblocked": revenue["amount"],
        "currency": revenue["currency"],
        "unavailable_reason": revenue["unavailable_reason"],
        "deals_closed": len(won),
        "details": [
            {
                "deal_id": deal.id,
                "company_name": deal.company_name,
                "value": money_text(deal.deal_value_arr),
                "currency": deal.currency,
            }
            for deal in won
        ],
    }
