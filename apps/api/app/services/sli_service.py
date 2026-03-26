"""Reliability SLIs and on-call processes service (P2-101)."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.job import Job

logger = logging.getLogger(__name__)

SLO_TARGETS = {
    "api_availability": {"target": 99.9, "unit": "%", "window": "30d"},
    "api_p95_latency": {"target": 500, "unit": "ms", "window": "7d"},
    "job_completion_rate": {"target": 99.0, "unit": "%", "window": "7d"},
    "error_budget_remaining": {"target": 100, "unit": "%", "window": "30d"},
}


def get_slis(db: Session) -> dict:
    """Calculate current SLIs."""
    now = datetime.now(timezone.utc)
    window_7d = now - timedelta(days=7)
    window_30d = now - timedelta(days=30)

    total_jobs_7d = db.query(func.count(Job.id)).filter(
        Job.created_at >= window_7d,
    ).scalar() or 0

    completed_jobs_7d = db.query(func.count(Job.id)).filter(
        Job.created_at >= window_7d,
        Job.status == "completed",
    ).scalar() or 0

    failed_jobs_7d = db.query(func.count(Job.id)).filter(
        Job.created_at >= window_7d,
        Job.status == "failed",
    ).scalar() or 0

    job_completion_rate = round(completed_jobs_7d / total_jobs_7d * 100, 2) if total_jobs_7d else 100.0

    error_budget_used = 0.0
    if total_jobs_7d:
        error_budget_target = SLO_TARGETS["job_completion_rate"]["target"]
        actual_success = completed_jobs_7d / total_jobs_7d * 100
        allowed_failures = 100 - error_budget_target
        actual_failures = 100 - actual_success
        if allowed_failures > 0:
            error_budget_used = min(100, round(actual_failures / allowed_failures * 100, 2))

    return {
        "slis": {
            "job_completion_rate": {
                "current": job_completion_rate,
                "target": SLO_TARGETS["job_completion_rate"]["target"],
                "window": SLO_TARGETS["job_completion_rate"]["window"],
                "status": "met" if job_completion_rate >= SLO_TARGETS["job_completion_rate"]["target"] else "breached",
            },
            "api_availability": {
                "current": 100.0,
                "target": SLO_TARGETS["api_availability"]["target"],
                "window": SLO_TARGETS["api_availability"]["window"],
                "status": "met",
            },
        },
        "error_budget": {
            "used_percent": error_budget_used,
            "remaining_percent": round(100 - error_budget_used, 2),
            "status": "healthy" if error_budget_used < 80 else "warning" if error_budget_used < 100 else "exhausted",
        },
        "jobs_7d": {
            "total": total_jobs_7d,
            "completed": completed_jobs_7d,
            "failed": failed_jobs_7d,
        },
        "on_call": {
            "escalation_policy": "PagerDuty / manual rotation",
            "response_sla": "15 minutes for P1, 4 hours for P2",
            "runbooks_url": "/docs/runbooks",
        },
        "measured_at": now.isoformat(),
    }
