"""Supporting + suggested evidence for questionnaire mapping review."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models import Chunk, ControlEvidenceLink, Document, EvidenceItem

# Noisy placeholder content — deprioritize when other documents exist.
_STUB_NAME_RE = re.compile(
    r"placeholder|sample\s+evidence|\bstub\b|lorem\s+ipsum|^\s*test\.txt\s*$",
    re.IGNORECASE,
)


def is_stub_like(filename: str | None, title: str | None) -> bool:
    fn = (filename or "").strip()
    tl = (title or "").strip()
    if _STUB_NAME_RE.search(fn) or _STUB_NAME_RE.search(tl):
        return True
    if fn.lower() == "sample_evidence.txt" or "sample evidence" in tl.lower():
        return True
    return False


def batch_supporting_evidence_for_workspace_controls(
    db: Session,
    workspace_id: int,
    control_ids: list[int | None],
    *,
    limit_per_control: int = 3,
) -> dict[int, list[dict]]:
    """
    For each workspace_control id, return evidence linked via ControlEvidenceLink.

    - Scoped to ``workspace_id`` on EvidenceItem / Document.
    - Sorted: verified links first, then higher link confidence, stable by evidence id.
    - **Deduped by document_id** (one row per document; best link wins).
    - Framework-agnostic: uses only link + evidence + document metadata.
    """
    raw_ids = sorted({int(cid) for cid in control_ids if cid is not None})
    if not raw_ids:
        return {}

    links = (
        db.query(ControlEvidenceLink)
        .filter(ControlEvidenceLink.control_id.in_(raw_ids))
        .all()
    )
    if not links:
        return {cid: [] for cid in raw_ids}

    ev_ids = {ln.evidence_id for ln in links}
    evidence_rows = (
        db.query(EvidenceItem)
        .filter(
            EvidenceItem.id.in_(ev_ids),
            EvidenceItem.workspace_id == workspace_id,
        )
        .all()
    )
    ev_by_id = {e.id: e for e in evidence_rows}

    doc_ids = {e.document_id for e in evidence_rows if e.document_id}
    doc_by_id: dict[int, Document] = {}
    if doc_ids:
        for d in (
            db.query(Document)
            .filter(
                Document.id.in_(doc_ids),
                Document.workspace_id == workspace_id,
                Document.deleted_at.is_(None),
            )
            .all()
        ):
            doc_by_id[d.id] = d

    buckets: dict[int, list[tuple[tuple, dict]]] = {cid: [] for cid in raw_ids}

    for ln in links:
        cid = ln.control_id
        if cid not in buckets:
            continue
        ev = ev_by_id.get(ln.evidence_id)
        if not ev:
            continue
        doc = doc_by_id.get(ev.document_id) if ev.document_id else None
        conf = ln.confidence_score if ln.confidence_score is not None else 0.0
        verified = bool(ln.verified)
        sort_key = (0 if verified else 1, -conf, ev.id)
        payload = {
            "evidence_id": ev.id,
            "document_id": ev.document_id,
            "title": ev.title or "",
            "filename": doc.filename if doc else None,
            "display_name": (doc.filename if doc else None) or ev.title or f"Evidence #{ev.id}",
            "link_confidence": round(conf, 4) if conf else None,
            "verified": verified,
            "source": "control_evidence_link",
        }
        buckets[cid].append((sort_key, payload))

    out: dict[int, list[dict]] = {}
    for cid in raw_ids:
        items = buckets[cid]
        items.sort(key=lambda x: x[0])
        # Dedupe by document_id (keep best sort_key per document)
        best_by_doc: dict[tuple[str, int], tuple[tuple, dict]] = {}
        for sk, payload in items:
            did = payload.get("document_id")
            key: tuple[str, int] = ("doc", int(did)) if did is not None else ("ev", int(payload["evidence_id"]))
            prev = best_by_doc.get(key)
            if prev is None or sk < prev[0]:
                best_by_doc[key] = (sk, payload)
        merged = sorted(best_by_doc.values(), key=lambda x: x[0])
        row_list = [p for _, p in merged[:limit_per_control]]
        # Deprioritize stub-like rows if we have alternatives
        non_stub = [p for p in row_list if not is_stub_like(p.get("filename"), p.get("title"))]
        if non_stub:
            row_list = non_stub[:limit_per_control]
        out[cid] = row_list

    return out


def suggest_documents_for_mapping_review(
    db: Session,
    workspace_id: int,
    question_text: str,
    control_id: int | None,
    *,
    exclude_document_ids: set[int],
    limit: int = 3,
) -> list[dict]:
    """
    Secondary evidence layer when there is no ControlEvidenceLink (or to supplement context):
    retrieval over indexed chunks using question + control metadata.

    Labeled ``source: suggested_match`` — not verified / not explicitly linked to the control.
    """
    from app.services.embedding_service import embed_text
    from app.services.evidence_suggestion import get_control_search_query
    from app.services.retrieval import RetrievalService

    if not control_id or not (question_text or "").strip():
        return []
    cq = get_control_search_query(db, int(control_id), workspace_id)
    if not cq:
        return []
    qt = (question_text or "").strip()[:2800]
    query = f"{qt}\n\n{cq}"[:8000]

    try:
        emb = embed_text(query)
    except Exception:
        emb = None
    retrieval = RetrievalService(db)
    try:
        raw = retrieval.search(
            workspace_id,
            query,
            limit=max(18, limit * 6),
            query_embedding=emb,
            min_score=0.0,
        )
    except Exception:
        return []

    scored: list[tuple[float, int, int | None, str]] = []
    for r in raw:
        chunk_id = r.get("id")
        if chunk_id is None:
            continue
        ch = db.query(Chunk).filter(Chunk.id == chunk_id, Chunk.workspace_id == workspace_id).first()
        if not ch or not ch.document_id:
            continue
        if ch.document_id in exclude_document_ids:
            continue
        sc = float(r.get("score") or 0.0)
        snippet = (r.get("text") or ch.text or "")[:220].replace("\n", " ").strip()
        scored.append((sc, ch.document_id, ch.id, snippet))

    scored.sort(key=lambda x: -x[0])
    # One entry per document (best chunk)
    by_doc: dict[int, tuple[float, int | None, str]] = {}
    for sc, did, chid, snip in scored:
        if did in by_doc and sc <= by_doc[did][0]:
            continue
        by_doc[did] = (sc, chid, snip)

    docs_meta: list[tuple[int, float, int | None, str]] = []
    for did, (sc, chid, snip) in by_doc.items():
        docs_meta.append((did, sc, chid, snip))
    docs_meta.sort(key=lambda x: -x[1])

    candidates: list[dict] = []
    for did, sc, _chid, snip in docs_meta:
        doc = (
            db.query(Document)
            .filter(
                Document.id == did,
                Document.workspace_id == workspace_id,
                Document.deleted_at.is_(None),
            )
            .first()
        )
        if not doc:
            continue
        display = (doc.filename or "").strip() or (doc.display_id or "") or f"Document #{did}"
        candidates.append({
            "document_id": did,
            "display_name": display,
            "filename": doc.filename,
            "snippet": snip,
            "relevance": round(min(1.0, max(0.0, sc)), 4),
            "source": "suggested_match",
        })

    non_stub = [x for x in candidates if not is_stub_like(x.get("filename"), x.get("display_name"))]
    if len(non_stub) >= limit:
        return non_stub[:limit]
    return candidates[:limit]
