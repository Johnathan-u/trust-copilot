"""Keep ineligible documents out of retrieval, caches, and citation resolution.

A chunk is eligible when it has no document, or its document is in this
workspace, not soft-deleted, ``status`` indexed, not tombstoned, and not
indexed from a storage key the document has since replaced.

A chunk with no document stays eligible: it is not a deleted document's chunk.
A document in another workspace is not eligible for this workspace.
"""

from __future__ import annotations

from sqlalchemy import and_, or_
from sqlalchemy.orm import Query, Session
from sqlalchemy.orm.attributes import flag_modified

from app.models import Chunk, Document

INDEXED_STATUS = "indexed"
TOMBSTONE_KEY = "retrieval_tombstone"
SOURCE_VERSION_KEY = "source_version"


def _json_text(column, key: str):
    """PostgreSQL JSON text extraction (``->>``). NULL metadata yields NULL."""
    return column.op("->>")(key)


def eligible_chunk_query(db: Session, workspace_id: int) -> Query:
    """Chunks in this workspace that may be retrieved, plus orphan chunks."""
    tombstone = _json_text(Chunk.metadata_, TOMBSTONE_KEY)
    source_version = _json_text(Chunk.metadata_, SOURCE_VERSION_KEY)
    return (
        db.query(Chunk)
        .outerjoin(
            Document,
            and_(
                Document.id == Chunk.document_id,
                Document.workspace_id == workspace_id,
                Document.deleted_at.is_(None),
                Document.status == INDEXED_STATUS,
            ),
        )
        .filter(
            Chunk.workspace_id == workspace_id,
            or_(Chunk.document_id.is_(None), Document.id.isnot(None)),
            tombstone.is_(None),
            or_(
                Chunk.document_id.is_(None),
                source_version.is_(None),
                source_version == Document.storage_key,
            ),
        )
    )


def tombstone_document_chunks(db: Session, document_id: int) -> None:
    """Mark this document's chunks ineligible without deleting them.

    Restore clears the mark so the same chunks can be retrieved again.
    """
    rows = db.query(Chunk).filter(Chunk.document_id == document_id).all()
    for row in rows:
        meta = dict(row.metadata_) if isinstance(row.metadata_, dict) else {}
        meta[TOMBSTONE_KEY] = "soft_deleted"
        row.metadata_ = meta
        flag_modified(row, "metadata_")


def restore_document_chunks(db: Session, document_id: int) -> None:
    """Clear the soft-delete tombstone so restored chunks are eligible again."""
    rows = db.query(Chunk).filter(Chunk.document_id == document_id).all()
    for row in rows:
        if not isinstance(row.metadata_, dict) or TOMBSTONE_KEY not in row.metadata_:
            continue
        meta = dict(row.metadata_)
        meta.pop(TOMBSTONE_KEY, None)
        row.metadata_ = meta or None
        flag_modified(row, "metadata_")


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
                Document.status.is_(None),
                Document.status != INDEXED_STATUS,
            )
        )
        .first()
    )
    return row is not None


def _known_chunk_ineligible(db: Session, workspace_id: int, chunk_ids: set[int]) -> bool:
    tombstone = _json_text(Chunk.metadata_, TOMBSTONE_KEY)
    source_version = _json_text(Chunk.metadata_, SOURCE_VERSION_KEY)
    row = (
        db.query(Chunk.id)
        .outerjoin(Document, Document.id == Chunk.document_id)
        .filter(Chunk.id.in_(list(chunk_ids)))
        .filter(
            or_(
                Chunk.workspace_id != workspace_id,
                tombstone.isnot(None),
                and_(
                    Chunk.document_id.isnot(None),
                    or_(
                        Document.id.is_(None),
                        Document.deleted_at.isnot(None),
                        Document.workspace_id != workspace_id,
                        Document.status.is_(None),
                        Document.status != INDEXED_STATUS,
                        and_(
                            source_version.isnot(None),
                            source_version != Document.storage_key,
                        ),
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
    """True when a known document or chunk is ineligible or outside the workspace.

    Ineligible means soft-deleted, not indexed, tombstoned, or indexed from a
    storage key the document has replaced. Ids that do not exist are ignored
    so a synthetic cache fixture is unchanged.
    """
    if document_ids and _known_document_ineligible(db, workspace_id, document_ids):
        return True
    if chunk_ids and _known_chunk_ineligible(db, workspace_id, chunk_ids):
        return True
    return False


def retrieval_rows_are_stale(db: Session, workspace_id: int, rows: list) -> bool:
    """True when cached retrieval rows cite an ineligible document or chunk."""
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
    """True when cached answer citations name an ineligible document or chunk."""
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
