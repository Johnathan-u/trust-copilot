"""Connector health visibility service (P1-30)."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.source_registry import SourceRegistry
from app.services import credential_store_service as credentials
from app.services.provider_adapter.contract import (
    CONTRACT_NAME,
    SCHEMA_VERSION,
    ObservationState,
    ProvenanceKind,
)
from app.services.provider_adapter.surfaces import action_contract


def get_connector_health(db: Session, workspace_id: int) -> dict:
    """Get comprehensive health status for all connectors in a workspace."""
    sources = (
        db.query(SourceRegistry)
        .filter(
            SourceRegistry.workspace_id == workspace_id,
            SourceRegistry.enabled.is_(True),
        )
        .all()
    )

    connectors = []
    posture_observations = []
    for s in sources:
        health = _assess_health(s)
        posture = evidence_posture(s)
        posture_observations.append(posture)
        connectors.append(
            {
                "source_type": s.source_type,
                "display_name": s.display_name,
                "status": health["status"],
                "health_score": health["score"],
                "last_sync_at": s.last_sync_at.isoformat() if s.last_sync_at else None,
                "last_sync_status": s.last_sync_status,
                "last_error": s.last_error,
                "sync_cadence": s.sync_cadence,
                "issues": health["issues"],
                "evidence_posture": posture,
            }
        )

    healthy = sum(1 for c in connectors if c["status"] == "healthy")
    degraded = sum(1 for c in connectors if c["status"] == "degraded")
    unhealthy = sum(1 for c in connectors if c["status"] == "unhealthy")
    unknown = sum(1 for c in connectors if c["status"] == "unknown")

    overall = "healthy"
    if unhealthy > 0:
        overall = "unhealthy"
    elif degraded > 0:
        overall = "degraded"
    elif unknown == len(connectors) and len(connectors) > 0:
        overall = "unknown"

    return {
        "overall_status": overall,
        "total_connectors": len(connectors),
        "healthy": healthy,
        "degraded": degraded,
        "unhealthy": unhealthy,
        "unknown": unknown,
        "connectors": connectors,
        "credential_custody": credentials.list_credentials(db, workspace_id),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "observation_contract": {
            "schema_version": SCHEMA_VERSION,
            "contract": CONTRACT_NAME,
            "observations": posture_observations,
        },
    }


def evidence_posture(source: SourceRegistry) -> dict:
    """Evidence honesty for one registry row. Sync bookkeeping is not success."""
    if source.last_sync_status == "failed":
        state = ObservationState.FAILURE
        reason = "sync_failed"
        error_code = "sync_failed"
    elif not source.last_sync_at:
        state = ObservationState.UNKNOWN
        reason = "never_synced"
        error_code = "not_observed"
    else:
        state = ObservationState.UNKNOWN
        reason = "sync_bookkeeping_is_not_collected_evidence"
        error_code = "not_evidence"
    contract = action_contract(
        provider=source.source_type,
        resource_id=f"health:{source.source_type}",
        state=state,
        provenance_kind=ProvenanceKind.ABSENT,
        workspace_id=source.workspace_id,
        error_code=error_code,
        safe_message=reason,
        note=reason,
    )
    observation = contract["observations"][0]
    observation["reason"] = reason
    return observation


def _assess_health(source: SourceRegistry) -> dict:
    issues = []
    now = datetime.now(timezone.utc)

    if not source.last_sync_at:
        return {"status": "unknown", "score": 0, "issues": ["Never synced"]}

    last_sync = source.last_sync_at
    if last_sync.tzinfo is None:
        from datetime import timezone as tz

        last_sync = last_sync.replace(tzinfo=tz.utc)

    if source.last_sync_status == "failed":
        issues.append(f"Last sync failed: {source.last_error or 'unknown error'}")

    staleness = _get_staleness_threshold(source.sync_cadence)
    if (now - last_sync) > staleness:
        issues.append(f"Sync overdue — last sync {_format_ago(now - last_sync)} ago")

    if source.last_sync_status == "failed":
        status = "unhealthy"
        score = 20
    elif issues:
        status = "degraded"
        score = 60
    else:
        status = "healthy"
        score = 100

    return {"status": status, "score": score, "issues": issues}


def _get_staleness_threshold(cadence: str) -> timedelta:
    thresholds = {
        "realtime": timedelta(hours=1),
        "periodic_15m": timedelta(hours=1),
        "periodic_1h": timedelta(hours=3),
        "daily": timedelta(hours=36),
        "weekly": timedelta(days=10),
        "manual": timedelta(days=365),
    }
    return thresholds.get(cadence, timedelta(days=2))


def _format_ago(delta: timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    if total_seconds < 3600:
        return f"{total_seconds // 60}m"
    if total_seconds < 86400:
        return f"{total_seconds // 3600}h"
    return f"{total_seconds // 86400}d"
