"""Deal-linked analytics (E1-07).

Track deals closed with Trust Copilot, average time-to-close, and revenue unblocked.
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.deal import Deal

logger = logging.getLogger(__name__)


def get_analytics(db: Session, workspace_id: int) -> dict:
    deals = db.query(Deal).filter(Deal.workspace_id == workspace_id).all()
    total = len(deals)
    won = [d for d in deals if d.stage == "closed_won"]
    lost = [d for d in deals if d.stage == "closed_lost"]
    active = [d for d in deals if d.stage not in ("closed_won", "closed_lost")]

    revenue_won = sum(d.deal_value_arr or 0 for d in won)
    revenue_pipeline = sum(d.deal_value_arr or 0 for d in active)

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
        "revenue_won": revenue_won,
        "revenue_pipeline": revenue_pipeline,
        "avg_close_days": avg_close_days,
        "by_stage": by_stage,
        "win_rate": round(len(won) / max(len(won) + len(lost), 1) * 100, 1),
    }


def get_revenue_unblocked(db: Session, workspace_id: int) -> dict:
    won = db.query(Deal).filter(
        Deal.workspace_id == workspace_id,
        Deal.stage == "closed_won",
    ).all()
    total_unblocked = sum(d.deal_value_arr or 0 for d in won)
    return {
        "total_revenue_unblocked": total_unblocked,
        "deals_closed": len(won),
        "details": [
            {"deal_id": d.id, "company_name": d.company_name, "value": d.deal_value_arr}
            for d in won
        ],
    }
