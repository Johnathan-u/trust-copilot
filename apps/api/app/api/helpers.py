"""Shared serialisation helpers used across compliance route modules."""

from app.models import EvidenceItem


def evidence_dict(e: EvidenceItem, tags: list[dict] | None = None) -> dict:
    """Serialise an EvidenceItem to a plain dict, optionally including tags."""
    d = {
        "id": e.id,
        "workspace_id": e.workspace_id,
        "document_id": e.document_id,
        "source_type": e.source_type,
        "title": e.title,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }
    if tags is not None:
        d["tags"] = tags
    return d
