"""Raw ingestion pipeline service (P1-16).

Provides a unified pipeline for ingesting evidence from any connector.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.evidence_item import EvidenceItem
from app.models.source_registry import SourceRegistry
from app.services.workspace_integrity import require_same_workspace

logger = logging.getLogger(__name__)


def ingest_evidence(
    db: Session,
    workspace_id: int,
    source_type: str,
    title: str,
    source_metadata: str | None = None,
    document_id: int | None = None,
) -> dict:
    """Ingest a single evidence item from any connector source.

    document_id must belong to workspace_id (raises CrossWorkspaceReference / InvalidReference).
    """
    require_same_workspace(db, workspace_id, document_id=document_id)
    evidence = EvidenceItem(
        workspace_id=workspace_id,
        source_type=source_type,
        title=title,
        source_metadata=source_metadata,
        document_id=document_id,
    )
    db.add(evidence)
    db.flush()

    source = (
        db.query(SourceRegistry)
        .filter(
            SourceRegistry.source_type == source_type,
        )
        .first()
    )
    if source:
        source.last_sync_at = datetime.now(timezone.utc)
        source.last_error = None

    return {
        "id": evidence.id,
        "workspace_id": workspace_id,
        "source_type": source_type,
        "title": title,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }


def ingest_batch(
    db: Session,
    workspace_id: int,
    source_type: str,
    items: list[dict],
) -> dict:
    """Ingest multiple evidence items in a batch.

    Every document_id is checked before any row is added, so a bad item rejects the whole batch.
    """
    for item in items:
        require_same_workspace(db, workspace_id, document_id=item.get("document_id"))
    results = []
    for item in items:
        result = ingest_evidence(
            db,
            workspace_id,
            source_type,
            title=item.get("title", "Untitled"),
            source_metadata=item.get("source_metadata"),
            document_id=item.get("document_id"),
        )
        results.append(result)
    return {
        "source_type": source_type,
        "ingested": len(results),
        "items": results,
    }


def get_ingestion_stats(db: Session, workspace_id: int) -> dict:
    """Get ingestion statistics per source type."""
    from sqlalchemy import func

    stats = (
        db.query(
            EvidenceItem.source_type,
            func.count(EvidenceItem.id),
        )
        .filter(
            EvidenceItem.workspace_id == workspace_id,
        )
        .group_by(EvidenceItem.source_type)
        .all()
    )

    return {
        "by_source": {st: cnt for st, cnt in stats},
        "total": sum(cnt for _, cnt in stats),
    }
