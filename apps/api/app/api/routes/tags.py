"""Tag management API: list, add, remove, approve tags on documents."""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_review, require_session
from app.core.database import get_db
from app.models import Document
from app.services.tag_service import (
    approve_tag,
    assign_tag,
    list_available_tags,
    list_tags_for_document,
    list_tags_for_documents,
    remove_tag,
    resolve_tag,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tags", tags=["tags"])


async def _require_tag_manager(request: Request, db: Session = Depends(get_db)) -> dict:
    """Tag mutations require admin or reviewer role. Editors are excluded per enterprise tagging policy."""
    session = await require_session(request, db)
    role = session.get("role")
    if role in ("admin", "reviewer"):
        return session
    raise HTTPException(status_code=403, detail="Insufficient permissions")


@router.get("/available")
def get_available_tags(
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """List all tags available to the current workspace (system + workspace-scoped)."""
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(status_code=403, detail="No workspace")
    return list_available_tags(db, ws)


@router.get("/documents/{document_id}")
def get_document_tags(
    document_id: int,
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """List tags for a specific document."""
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(status_code=403, detail="No workspace")
    doc = db.query(Document).filter(Document.id == document_id, Document.workspace_id == ws).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return list_tags_for_document(db, document_id, ws)


class AddTagBody(BaseModel):
    category: str
    key: str


@router.post("/documents/{document_id}")
def add_document_tag(
    document_id: int,
    body: AddTagBody,
    session: dict = Depends(_require_tag_manager),
    db: Session = Depends(get_db),
):
    """Manually add a tag to a document. Requires reviewer or admin."""
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(status_code=403, detail="No workspace")
    doc = db.query(Document).filter(Document.id == document_id, Document.workspace_id == ws).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    tag = resolve_tag(db, body.category, body.key, ws)
    if not tag:
        raise HTTPException(status_code=404, detail=f"Tag {body.category}/{body.key} not found")
    dt = assign_tag(
        db,
        document_id=document_id,
        tag_id=tag.id,
        workspace_id=ws,
        source="manual",
        confidence=None,
        approved=True,
        user_id=session.get("user_id"),
    )
    db.commit()
    return list_tags_for_document(db, document_id, ws)


class RemoveTagBody(BaseModel):
    tag_id: int


@router.delete("/documents/{document_id}/{tag_id}")
def remove_document_tag(
    document_id: int,
    tag_id: int,
    session: dict = Depends(_require_tag_manager),
    db: Session = Depends(get_db),
):
    """Remove a tag from a document. Requires reviewer or admin."""
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(status_code=403, detail="No workspace")
    doc = db.query(Document).filter(Document.id == document_id, Document.workspace_id == ws).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    removed = remove_tag(db, document_id, tag_id, ws)
    if not removed:
        raise HTTPException(status_code=404, detail="Tag assignment not found")
    db.commit()
    return list_tags_for_document(db, document_id, ws)


class ApproveBody(BaseModel):
    approved: bool = True


@router.patch("/document-tags/{document_tag_id}/approve")
def approve_document_tag(
    document_tag_id: int,
    body: ApproveBody,
    session: dict = Depends(_require_tag_manager),
    db: Session = Depends(get_db),
):
    """Approve or reject an AI-suggested tag. Requires reviewer or admin."""
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(status_code=403, detail="No workspace")
    dt = approve_tag(db, document_tag_id, ws, body.approved)
    if not dt:
        raise HTTPException(status_code=404, detail="Document tag not found")
    db.commit()
    return {"id": dt.id, "approved": dt.approved}


class ChunkTagsBody(BaseModel):
    chunk_ids: List[int]


@router.post("/by-chunks")
def get_tags_by_chunks(
    body: ChunkTagsBody,
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Resolve chunk IDs to their parent document tags. Used by citation drawer."""
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(status_code=403, detail="No workspace")
    from app.models import Chunk
    chunk_ids = body.chunk_ids[:100]
    chunks = db.query(Chunk).filter(Chunk.id.in_(chunk_ids), Chunk.workspace_id == ws).all()
    doc_ids = list({c.document_id for c in chunks if c.document_id})
    tags_by_doc = list_tags_for_documents(db, doc_ids, ws) if doc_ids else {}
    chunk_doc_map = {c.id: c.document_id for c in chunks}
    result: dict[int, list[dict]] = {}
    for cid in chunk_ids:
        did = chunk_doc_map.get(cid)
        result[cid] = tags_by_doc.get(did, []) if did else []
    return result
