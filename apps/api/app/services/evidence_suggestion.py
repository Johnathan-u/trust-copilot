"""Phase 2: AI evidence suggestion for a control (retrieval over workspace chunks)."""

from sqlalchemy.orm import Session

from app.models import WorkspaceControl, FrameworkControl
from app.services.retrieval import RetrievalService
from app.services.embedding_service import embed_text


def get_control_search_query(db: Session, control_id: int, workspace_id: int) -> str:
    """Build a search query string from control title/description for retrieval."""
    wc = db.query(WorkspaceControl).filter(
        WorkspaceControl.id == control_id,
        WorkspaceControl.workspace_id == workspace_id,
    ).first()
    if not wc:
        return ""
    parts = []
    if wc.custom_name and wc.custom_name.strip():
        parts.append(wc.custom_name.strip())
    if wc.framework_control_id:
        fc = db.query(FrameworkControl).filter(FrameworkControl.id == wc.framework_control_id).first()
        if fc:
            if fc.title and fc.title.strip():
                parts.append(fc.title.strip())
            if fc.description and fc.description.strip():
                parts.append(fc.description.strip()[:500])
            if fc.control_key:
                parts.append(fc.control_key)
            if fc.category:
                parts.append(fc.category)
    return " ".join(parts).strip() or f"control {control_id}"


def suggest_evidence(
    db: Session,
    control_id: int,
    workspace_id: int,
    limit: int = 10,
    min_confidence: float = 0.0,
) -> list[dict]:
    """
    Return suggested documents/chunks for the control: run retrieval with control
    title/description as query. Returns list of { document_id, chunk_id, snippet, confidence }.
    """
    from app.models import Chunk

    query = get_control_search_query(db, control_id, workspace_id)
    if not query:
        return []

    retrieval = RetrievalService(db)
    query_embedding = embed_text(query[:8000]) if query else None
    results = retrieval.search(
        workspace_id,
        query,
        limit=limit,
        query_embedding=query_embedding,
        min_score=min_confidence,
    )

    # Light tag boost: documents with framework/topic tags matching the control
    # get a small score bump (TAG_BOOST). Safe additive change — no regressions.
    TAG_BOOST = 0.03
    tagged_doc_ids: set[int] = set()
    try:
        from app.services.tag_service import list_tags_for_documents as _batch_tags
        from app.models.tag import DocumentTag
        doc_ids_in_results = list({
            db.query(Chunk.document_id).filter(Chunk.id == r.get("id"), Chunk.workspace_id == workspace_id).scalar()
            for r in results if r.get("id")
        } - {None})
        if doc_ids_in_results:
            tags_by_doc = _batch_tags(db, doc_ids_in_results, workspace_id)
            for did, tags in tags_by_doc.items():
                if any(t["category"] in ("framework", "topic") for t in tags):
                    tagged_doc_ids.add(did)
    except Exception:
        pass

    out = []
    for r in results:
        chunk_id = r.get("id")
        if chunk_id is None:
            continue
        ch = db.query(Chunk).filter(Chunk.id == chunk_id, Chunk.workspace_id == workspace_id).first()
        if not ch:
            continue
        score = r.get("score") or 0.0
        if ch.document_id in tagged_doc_ids:
            score = min(1.0, score + TAG_BOOST)
        if score < min_confidence:
            continue
        text = (r.get("text") or ch.text or "")[:500]
        out.append({
            "document_id": ch.document_id,
            "chunk_id": chunk_id,
            "snippet": text,
            "confidence": round(score, 4),
        })
    out.sort(key=lambda x: x["confidence"], reverse=True)
    return out[:limit]
