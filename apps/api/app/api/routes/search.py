"""Search API (RET-01)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_review
from app.core.database import get_db
from app.services.retrieval import RetrievalService

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/")
@router.get("")
def search(
    workspace_id: int = Query(...),
    q: str = Query(...),
    limit: int = Query(10, le=50),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Semantic + keyword search over document chunks (uses embedding when OPENAI_API_KEY set)."""
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    from app.services.embedding_service import embed_text

    query_emb = embed_text(q) if q.strip() else None
    svc = RetrievalService(db)
    return {"results": svc.search(workspace_id, q, limit=limit, query_embedding=query_emb)}
