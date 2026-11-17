"""Keep soft-deleted documents out of retrieval, caches, and citation resolution.

A chunk with no document stays eligible: it is not a deleted document's chunk.
A document in another workspace is not eligible for this workspace.
"""

from __future__ import annotations

from sqlalchemy import and_, or_
from sqlalchemy.orm import Query, Session

from app.models import Chunk, Document


def eligible_chunk_query(db: Session, workspace_id: int) -> Query:
    """Chunks in this workspace whose document is active here, plus orphan chunks."""
    return (
        db.query(Chunk)
        .outerjoin(
            Document,
            and_(
                Document.id == Chunk.document_id,
                Document.workspace_id == workspace_id,
                Document.deleted_at.is_(None),
            ),
        )
        .filter(
            Chunk.workspace_id == workspace_id,
            or_(Chunk.document_id.is_(None), Document.id.isnot(None)),
        )
    )


def document_is_citable(db: Session, workspace_id: int, document_id: int | None) -> bool:
    """True for evidence with no document, or a live document in this workspace."""
    if document_id is None:
        return True
    row = (
        db.query(Document.id)
        .filter(
            Document.id == document_id,
            Document.workspace_id == workspace_id,
            Document.deleted_at.is_(None),
        )
        .first()
    )
    return row is not None


def _positive_int(value: object) -> int | None:
    if type(value) is int and value > 0:
        return value
    return None


def _known_document_ineligible(db: Session, workspace_id: int, document_ids: set[int]) -> bool:
    row = (
        db.query(Document.id)
        .filter(Document.id.in_(list(document_ids)))
        .filter(
            or_(
                Document.deleted_at.isnot(None),
                Document.workspace_id != workspace_id,
            )
        )
        .first()
    )
    return row is not None


def _known_chunk_ineligible(db: Session, workspace_id: int, chunk_ids: set[int]) -> bool:
    row = (
        db.query(Chunk.id)
        .outerjoin(Document, Document.id == Chunk.document_id)
        .filter(Chunk.id.in_(list(chunk_ids)))
        .filter(
            or_(
                Chunk.workspace_id != workspace_id,
                and_(
                    Chunk.document_id.isnot(None),
                    or_(
                        Document.id.is_(None),
                        Document.deleted_at.isnot(None),
                        Document.workspace_id != workspace_id,
                    ),
                ),
            )
        )
        .first()
    )
    return row is not None


def references_ineligible_source(
    db: Session,
    workspace_id: int,
    *,
    document_ids: set[int],
    chunk_ids: set[int],
) -> bool:
    """True when a known document or chunk is soft-deleted or outside the workspace.

    Ids that do not exist are ignored so a synthetic cache fixture is unchanged.
    """
    if document_ids and _known_document_ineligible(db, workspace_id, document_ids):
        return True
    if chunk_ids and _known_chunk_ineligible(db, workspace_id, chunk_ids):
        return True
    return False


def retrieval_rows_are_stale(db: Session, workspace_id: int, rows: list) -> bool:
    """True when cached retrieval rows cite a soft-deleted or foreign document."""
    if not isinstance(rows, list):
        return False
    document_ids: set[int] = set()
    chunk_ids: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        chunk_id = _positive_int(row.get("id"))
        if chunk_id is not None:
            chunk_ids.add(chunk_id)
        meta = row.get("metadata")
        if isinstance(meta, dict):
            document_id = _positive_int(meta.get("document_id"))
            if document_id is not None:
                document_ids.add(document_id)
    return references_ineligible_source(
        db, workspace_id, document_ids=document_ids, chunk_ids=chunk_ids
    )


def citations_are_stale(db: Session, workspace_id: int, citations: list) -> bool:
    """True when cached answer citations name a soft-deleted or foreign document."""
    if not isinstance(citations, list):
        return False
    document_ids: set[int] = set()
    chunk_ids: set[int] = set()
    for item in citations:
        if not isinstance(item, dict):
            continue
        document_id = _positive_int(item.get("document_id"))
        chunk_id = _positive_int(item.get("chunk_id"))
        if document_id is not None:
            document_ids.add(document_id)
        if chunk_id is not None:
            chunk_ids.add(chunk_id)
    return references_ineligible_source(
        db, workspace_id, document_ids=document_ids, chunk_ids=chunk_ids
    )
