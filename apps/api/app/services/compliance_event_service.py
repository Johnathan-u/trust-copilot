"""
Compliance event service: evaluates coverage KPIs after answer generation
and fires notification events when thresholds are breached.

Uses existing fire_notification (email + Slack) and notify_admins (in-app bell).
Each breach writes an audit row and uses that row id, so a repeat is a new event.
"""

import logging

from sqlalchemy.orm import Session

from app.core.audit import persist_audit
from app.services.compliance_coverage import get_compliance_coverage
from app.services.notification_service import fire_notification
from app.services.in_app_notification_service import notify_admins

logger = logging.getLogger(__name__)

COVERAGE_THRESHOLD = 80
INSUFFICIENT_THRESHOLD = 15


def _fire(
    db: Session,
    workspace_id: int,
    event_type: str,
    title: str,
    detail: str,
    workspace_name: str,
) -> bool:
    """Fire one compliance occurrence. The audit row id is the event id."""
    audit_id = persist_audit(
        db,
        event_type,
        workspace_id=workspace_id,
        resource_type="workspace",
        resource_id=workspace_id,
        details={"title": title},
    )
    fire_notification(
        db,
        workspace_id,
        event_type,
        detail,
        workspace_name,
        event_id=f"audit:{audit_id}",
    )
    notify_admins(
        db,
        workspace_id,
        title,
        detail,
        category="warning",
        link="/dashboard/compliance-gaps",
    )
    logger.info("Compliance event fired: %s for workspace %s", event_type, workspace_id)
    return True


def evaluate_and_fire_compliance_events(
    db: Session,
    workspace_id: int,
    workspace_name: str = "Workspace",
) -> int:
    """
    Compute current compliance coverage and fire notification events
    for any breached thresholds. Returns count of events fired.
    """
    try:
        data = get_compliance_coverage(db, workspace_id)
    except Exception as exc:
        logger.warning("Could not compute coverage for compliance events: %s", exc)
        return 0

    kpi = data.get("kpi", {})
    if not kpi or kpi.get("total_questions", 0) == 0:
        return 0

    fired = 0

    if kpi.get("coverage_pct", 100) < COVERAGE_THRESHOLD:
        ok = _fire(
            db,
            workspace_id,
            "compliance.coverage_drop",
            "Low coverage",
            f"Coverage is at {kpi['coverage_pct']}%, below the {COVERAGE_THRESHOLD}% target.",
            workspace_name,
        )
        if ok:
            fired += 1

    if kpi.get("insufficient_pct", 0) > INSUFFICIENT_THRESHOLD:
        ok = _fire(
            db,
            workspace_id,
            "compliance.high_insufficient",
            "High insufficient-answer rate",
            f"{kpi.get('total_insufficient', 0)} questions ({kpi['insufficient_pct']}%) lack sufficient evidence.",
            workspace_name,
        )
        if ok:
            fired += 1

    blind_spot_count = kpi.get("blind_spot_count", 0)
    if blind_spot_count > 0:
        top_blind = data.get("blind_spots", [])[:3]
        names = ", ".join(b["subject"] for b in top_blind) if top_blind else "unknown areas"
        ok = _fire(
            db,
            workspace_id,
            "compliance.blind_spot",
            f"{blind_spot_count} blind spot{'s' if blind_spot_count != 1 else ''} detected",
            f"Subject areas with insufficient evidence: {names}.",
            workspace_name,
        )
        if ok:
            fired += 1

    weak = data.get("weak_areas", [])
    if weak:
        worst = weak[0]
        ok = _fire(
            db,
            workspace_id,
            "compliance.weak_evidence",
            "Weak evidence in key area",
            f"{worst['subject']} has avg confidence of {worst['avg_confidence']}% across {worst['count']} answers.",
            workspace_name,
        )
        if ok:
            fired += 1

    if fired:
        logger.info("Fired %d compliance events for workspace %s", fired, workspace_id)

    return fired
