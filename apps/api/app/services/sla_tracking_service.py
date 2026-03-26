"""SLA and turnaround tracking service (P1-61)."""

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.questionnaire import Questionnaire


def get_sla_metrics(db: Session, workspace_id: int) -> dict:
    """Get SLA and turnaround metrics for a workspace."""
    questionnaires = db.query(Questionnaire).filter(
        Questionnaire.workspace_id == workspace_id,
    ).all()

    jobs = db.query(Job).filter(
        Job.workspace_id == workspace_id,
        Job.started_at.isnot(None),
        Job.completed_at.isnot(None),
    ).all()

    turnarounds = []
    for j in jobs:
        delta = (j.completed_at - j.started_at).total_seconds()
        if delta > 0:
            turnarounds.append({
                "job_id": j.id,
                "kind": j.kind,
                "seconds": round(delta, 1),
            })

    turnaround_seconds = [t["seconds"] for t in turnarounds]
    avg = round(sum(turnaround_seconds) / len(turnaround_seconds), 1) if turnaround_seconds else 0
    p50 = _percentile(turnaround_seconds, 50) if turnaround_seconds else 0
    p95 = _percentile(turnaround_seconds, 95) if turnaround_seconds else 0
    p99 = _percentile(turnaround_seconds, 99) if turnaround_seconds else 0

    sla_target_seconds = 300
    within_sla = sum(1 for s in turnaround_seconds if s <= sla_target_seconds)
    sla_compliance = round(within_sla / len(turnaround_seconds) * 100, 1) if turnaround_seconds else 100

    return {
        "total_questionnaires": len(questionnaires),
        "total_jobs_completed": len(turnarounds),
        "turnaround": {
            "avg_seconds": avg,
            "p50_seconds": p50,
            "p95_seconds": p95,
            "p99_seconds": p99,
        },
        "sla": {
            "target_seconds": sla_target_seconds,
            "within_sla_count": within_sla,
            "total_measured": len(turnaround_seconds),
            "compliance_pct": sla_compliance,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _percentile(data: list[float], pct: int) -> float:
    if not data:
        return 0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * pct / 100)
    idx = min(idx, len(sorted_data) - 1)
    return round(sorted_data[idx], 1)
