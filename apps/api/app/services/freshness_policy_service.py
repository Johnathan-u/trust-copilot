"""Per-source-type freshness policy service (P1-43).

Differentiated freshness policies: live API signals may stay fresh for 7 days,
while static PDFs might be trusted for 180 days.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.evidence_item import EvidenceItem
from app.models.evidence_metadata import EvidenceMetadata
from app.models.freshness_policy import FreshnessPolicy

logger = logging.getLogger(__name__)

DEFAULT_POLICIES = {
    "integration": {"max_age_days": 7, "warn_before_days": 2},
    "ai": {"max_age_days": 30, "warn_before_days": 7},
    "manual": {"max_age_days": 180, "warn_before_days": 30},
    "document": {"max_age_days": 180, "warn_before_days": 30},
    "slack": {"max_age_days": 30, "warn_before_days": 7},
    "gmail": {"max_age_days": 30, "warn_before_days": 7},
}


def set_policy(
    db: Session,
    workspace_id: int,
    source_type: str,
    max_age_days: int,
    warn_before_days: int = 14,
) -> dict:
    existing = db.query(FreshnessPolicy).filter(
        FreshnessPolicy.workspace_id == workspace_id,
        FreshnessPolicy.source_type == source_type,
    ).first()
    if existing:
        existing.max_age_days = max_age_days
        existing.warn_before_days = warn_before_days
        db.flush()
        return _serialize(existing)
    policy = FreshnessPolicy(
        workspace_id=workspace_id,
        source_type=source_type,
        max_age_days=max_age_days,
        warn_before_days=warn_before_days,
    )
    db.add(policy)
    db.flush()
    return _serialize(policy)


def get_policies(db: Session, workspace_id: int) -> list[dict]:
    policies = db.query(FreshnessPolicy).filter(
        FreshnessPolicy.workspace_id == workspace_id,
    ).order_by(FreshnessPolicy.source_type.asc()).all()
    return [_serialize(p) for p in policies]


def get_effective_policy(db: Session, workspace_id: int, source_type: str) -> dict:
    policy = db.query(FreshnessPolicy).filter(
        FreshnessPolicy.workspace_id == workspace_id,
        FreshnessPolicy.source_type == source_type,
    ).first()
    if policy:
        return _serialize(policy)
    defaults = DEFAULT_POLICIES.get(source_type, {"max_age_days": 90, "warn_before_days": 14})
    return {"source_type": source_type, "max_age_days": defaults["max_age_days"],
            "warn_before_days": defaults["warn_before_days"], "is_default": True}


def evaluate_freshness(db: Session, workspace_id: int) -> list[dict]:
    """Check all evidence items against their source-type freshness policy."""
    items = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == workspace_id).all()
    now = datetime.now(timezone.utc)
    results = []
    for item in items:
        policy = get_effective_policy(db, workspace_id, item.source_type)
        max_age = policy["max_age_days"]
        warn_days = policy["warn_before_days"]

        meta = db.query(EvidenceMetadata).filter(EvidenceMetadata.evidence_id == item.id).first()
        ref_date = None
        if meta and meta.freshness_date:
            ref_date = meta.freshness_date
        elif meta and meta.last_verified_at:
            ref_date = meta.last_verified_at
        else:
            ref_date = item.created_at
        if ref_date and ref_date.tzinfo is None:
            ref_date = ref_date.replace(tzinfo=timezone.utc)

        age_days = (now - ref_date).days if ref_date else 9999
        stale_threshold = max_age
        warn_threshold = max_age - warn_days

        if age_days >= stale_threshold:
            status = "stale"
        elif age_days >= warn_threshold:
            status = "warning"
        else:
            status = "fresh"

        results.append({
            "evidence_id": item.id,
            "title": item.title,
            "source_type": item.source_type,
            "age_days": age_days,
            "max_age_days": max_age,
            "freshness_status": status,
        })
    return results


def delete_policy(db: Session, workspace_id: int, source_type: str) -> bool:
    policy = db.query(FreshnessPolicy).filter(
        FreshnessPolicy.workspace_id == workspace_id,
        FreshnessPolicy.source_type == source_type,
    ).first()
    if not policy:
        return False
    db.delete(policy)
    db.flush()
    return True


def _serialize(p: FreshnessPolicy) -> dict:
    return {
        "id": p.id,
        "workspace_id": p.workspace_id,
        "source_type": p.source_type,
        "max_age_days": p.max_age_days,
        "warn_before_days": p.warn_before_days,
    }
