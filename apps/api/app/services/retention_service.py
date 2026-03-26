"""Evidence retention, archiving, and deletion service (P1-51).

Workspace-level and per-source retention policies with archival, automated deletion,
and policy configuration.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.evidence_item import EvidenceItem
from app.models.evidence_metadata import EvidenceMetadata
from app.models.retention_policy import RetentionPolicy

logger = logging.getLogger(__name__)


def set_policy(
    db: Session,
    workspace_id: int,
    retention_days: int = 365,
    archive_after_days: int | None = None,
    auto_delete: bool = False,
    source_type: str | None = None,
) -> dict:
    existing = db.query(RetentionPolicy).filter(
        RetentionPolicy.workspace_id == workspace_id,
        RetentionPolicy.source_type == source_type,
    ).first()
    if existing:
        existing.retention_days = retention_days
        existing.archive_after_days = archive_after_days
        existing.auto_delete = auto_delete
        db.flush()
        return _serialize(existing)
    policy = RetentionPolicy(
        workspace_id=workspace_id,
        source_type=source_type,
        retention_days=retention_days,
        archive_after_days=archive_after_days,
        auto_delete=auto_delete,
    )
    db.add(policy)
    db.flush()
    return _serialize(policy)


def get_policies(db: Session, workspace_id: int) -> list[dict]:
    policies = db.query(RetentionPolicy).filter(
        RetentionPolicy.workspace_id == workspace_id,
    ).order_by(RetentionPolicy.source_type.asc().nullsfirst()).all()
    return [_serialize(p) for p in policies]


def evaluate_retention(db: Session, workspace_id: int) -> dict:
    """Evaluate all evidence against retention policies. Returns items to archive/delete."""
    items = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == workspace_id).all()
    now = datetime.now(timezone.utc)

    to_archive = []
    to_delete = []
    ok = []

    for item in items:
        policy = _effective_policy(db, workspace_id, item.source_type)
        retention_days = policy["retention_days"]
        archive_days = policy.get("archive_after_days")
        auto_del = policy.get("auto_delete", False)

        created = item.created_at
        if created and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (now - created).days if created else 9999

        entry = {
            "evidence_id": item.id,
            "title": item.title,
            "source_type": item.source_type,
            "age_days": age_days,
            "retention_days": retention_days,
        }

        if age_days >= retention_days and auto_del:
            to_delete.append(entry)
        elif archive_days and age_days >= archive_days:
            to_archive.append(entry)
        else:
            ok.append(entry)

    return {
        "total": len(items),
        "ok": len(ok),
        "to_archive": to_archive,
        "to_delete": to_delete,
    }


def run_archival(db: Session, workspace_id: int) -> dict:
    """Execute archival: mark expired evidence metadata. Does not delete."""
    evaluation = evaluate_retention(db, workspace_id)
    archived_count = 0
    for entry in evaluation["to_archive"]:
        meta = db.query(EvidenceMetadata).filter(
            EvidenceMetadata.evidence_id == entry["evidence_id"],
        ).first()
        if meta:
            meta.expires_at = datetime.now(timezone.utc)
            archived_count += 1
    db.flush()
    return {"archived": archived_count, "pending_delete": len(evaluation["to_delete"])}


def run_deletion(db: Session, workspace_id: int, dry_run: bool = True) -> dict:
    """Execute deletion for evidence past retention with auto_delete enabled."""
    evaluation = evaluate_retention(db, workspace_id)
    if dry_run:
        return {"dry_run": True, "would_delete": len(evaluation["to_delete"]), "items": evaluation["to_delete"]}
    deleted = 0
    for entry in evaluation["to_delete"]:
        ev = db.query(EvidenceItem).filter(EvidenceItem.id == entry["evidence_id"]).first()
        if ev:
            db.delete(ev)
            deleted += 1
    db.flush()
    return {"dry_run": False, "deleted": deleted}


def delete_policy(db: Session, workspace_id: int, source_type: str | None = None) -> bool:
    policy = db.query(RetentionPolicy).filter(
        RetentionPolicy.workspace_id == workspace_id,
        RetentionPolicy.source_type == source_type,
    ).first()
    if not policy:
        return False
    db.delete(policy)
    db.flush()
    return True


def _effective_policy(db: Session, workspace_id: int, source_type: str | None) -> dict:
    if source_type:
        policy = db.query(RetentionPolicy).filter(
            RetentionPolicy.workspace_id == workspace_id,
            RetentionPolicy.source_type == source_type,
        ).first()
        if policy:
            return _serialize(policy)
    workspace_policy = db.query(RetentionPolicy).filter(
        RetentionPolicy.workspace_id == workspace_id,
        RetentionPolicy.source_type.is_(None),
    ).first()
    if workspace_policy:
        return _serialize(workspace_policy)
    return {"retention_days": 365, "archive_after_days": None, "auto_delete": False}


def _serialize(p: RetentionPolicy) -> dict:
    return {
        "id": p.id,
        "workspace_id": p.workspace_id,
        "source_type": p.source_type,
        "retention_days": p.retention_days,
        "archive_after_days": p.archive_after_days,
        "auto_delete": p.auto_delete,
    }
