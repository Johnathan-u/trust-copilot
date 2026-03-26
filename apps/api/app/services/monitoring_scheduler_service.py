"""Daily monitoring scheduler service (P1-33)."""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.services import control_engine_service as ce
from app.services import source_registry_service as sr

logger = logging.getLogger(__name__)


def run_daily_checks(db: Session, workspace_id: int) -> dict:
    """Run all daily monitoring checks for a workspace."""
    results = {
        "workspace_id": workspace_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "checks": [],
    }

    try:
        eval_result = ce.evaluate_all_controls(db, workspace_id)
        results["checks"].append({
            "name": "control_evaluation",
            "status": "completed",
            "total_controls": eval_result["total_controls"],
            "passing": eval_result["passing"],
            "failing": eval_result["failing"],
            "drift_count": eval_result["drift_count"],
        })
    except Exception as e:
        logger.error("Control evaluation failed for workspace %s: %s", workspace_id, e)
        results["checks"].append({"name": "control_evaluation", "status": "failed", "error": str(e)})

    try:
        health = sr.get_health_summary(db, workspace_id)
        results["checks"].append({
            "name": "connector_health",
            "status": "completed",
            "total_sources": health["total_sources"],
            "healthy": health["healthy"],
            "failed": health["failed"],
        })
    except Exception as e:
        logger.error("Connector health check failed for workspace %s: %s", workspace_id, e)
        results["checks"].append({"name": "connector_health", "status": "failed", "error": str(e)})

    results["completed_at"] = datetime.now(timezone.utc).isoformat()
    results["overall_status"] = "completed" if all(c["status"] == "completed" for c in results["checks"]) else "partial"

    return results
