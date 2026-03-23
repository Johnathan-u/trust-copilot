"""Index document: parse, chunk, save, embed (DOC-08, DOC-09)."""

import logging
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.pipeline_logging import log_index_failure, log_index_start, log_index_success
from app.core.metrics import INDEX_DOCUMENT_TOTAL, INDEX_DURATION_SECONDS
from app.models import Chunk, Document
from app.services.chunking import chunk_evidence
from app.services.embedding_service import EMBEDDING_DIM, embed_texts
from app.services.evidence_parser import parse_evidence
from app.services.file_service import FileService
from app.services.storage import StorageClient
from app.services.vector_util import embedding_to_vector_literal, validate_embedding_dimension


def index_document(
    db: Session,
    document_id: int,
    storage: StorageClient,
    file_svc: FileService,
    job_id: int | None = None,
) -> int:
    """
    Parse document, create chunks with metadata, generate embeddings, persist.
    Idempotent: deletes existing chunks for the document before creating new ones.
    Single transaction: one commit at the end; on failure document is left for worker to mark failed.
    Returns embedded chunk count. Raises on unrecoverable failure (0 parsed, 0 embedded, or embedding dimension mismatch).
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise ValueError(f"Document {document_id} not found")

    started = time.monotonic()
    log_index_start(document_id, doc.workspace_id, job_id=job_id)

    # Idempotent indexing: remove existing chunks so retries do not duplicate (Fix 1).
    db.query(Chunk).filter(Chunk.document_id == document_id).delete()
    db.flush()

    content = file_svc.download_raw(doc.storage_key)
    ext = Path(doc.filename or "").suffix or ".bin"
    suffix = ext if ext.startswith(".") else f".{ext}"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(content)
        path = f.name
    try:
        parsed = parse_evidence(path)
        if not parsed:
            # No false "indexed": 0 chunks => mark failed (Fix 2).
            doc.status = "failed"
            doc.index_error = ("Parse returned no content; document not indexed")[:512]
            db.commit()
            duration_ms = (time.monotonic() - started) * 1000
            log_index_failure(document_id, doc.workspace_id, "Parse returned no content", duration_ms, job_id=job_id)
            INDEX_DOCUMENT_TOTAL.labels(status="failure").inc()
            INDEX_DURATION_SECONDS.observe(duration_ms / 1000)
            raise ValueError("Parse returned no content; document not indexed")

        chunked = chunk_evidence(parsed)
        chunk_ids = []
        for c in chunked:
            meta = dict(c.get("metadata", {}))
            meta["filename"] = doc.filename
            meta["document_id"] = document_id
            if "chunk_index" not in meta:
                meta["chunk_index"] = len(chunk_ids)
            ch = Chunk(
                workspace_id=doc.workspace_id,
                document_id=doc.id,
                text=c["text"],
                metadata_=meta,
            )
            db.add(ch)
            db.flush()
            chunk_ids.append(ch.id)

        chunks = db.query(Chunk).filter(Chunk.id.in_(chunk_ids)).all()
        texts = [c.text for c in chunks]
        embeddings = embed_texts(texts)

        embedded_count = 0
        for ch, emb in zip(chunks, embeddings):
            if emb is None:
                continue
            try:
                validate_embedding_dimension(emb, context="chunk_embedding")
            except ValueError:
                continue
            vec_str = embedding_to_vector_literal(emb)
            db.execute(
                text("UPDATE chunks SET embedding = CAST(:v AS vector(1536)) WHERE id = :id"),
                {"v": vec_str, "id": ch.id},
            )
            embedded_count += 1

        # No false "indexed": require at least one embedded chunk (Fix 2). Single commit (Fix 3).
        if embedded_count == 0:
            doc.status = "failed"
            doc.index_error = ("No embeddings could be written (API error or dimension mismatch); document not indexed")[:512]
            db.commit()
            duration_ms = (time.monotonic() - started) * 1000
            log_index_failure(document_id, doc.workspace_id, "No embeddings could be written", duration_ms, job_id=job_id)
            INDEX_DOCUMENT_TOTAL.labels(status="failure").inc()
            INDEX_DURATION_SECONDS.observe(duration_ms / 1000)
            raise ValueError(
                "No embeddings could be written (API error or dimension mismatch); document not indexed"
            )

        doc.status = "indexed"

        # Auto-tag: best-effort, never blocks indexing
        try:
            from app.services.tag_service import auto_tag_document
            chunk_texts = [c.text for c in chunks if c.text]
            tag_count = auto_tag_document(db, document_id, doc.workspace_id, doc.filename or "", chunk_texts)
            if tag_count:
                logger.info("auto_tagged document_id=%s tags=%s", document_id, tag_count)
        except Exception:
            logger.debug("auto_tag_document failed for document_id=%s", document_id, exc_info=True)

        db.commit()
        # Invalidate retrieval cache when evidence corpus changes (answer pipeline)
        try:
            from app.core.corpus_version import bump_corpus_version
            from app.services.retrieval_cache import invalidate_workspace as retrieval_cache_invalidate
            bump_corpus_version(db, doc.workspace_id)
            retrieval_cache_invalidate(db, doc.workspace_id)
        except Exception:
            pass
        duration_ms = (time.monotonic() - started) * 1000
        log_index_success(document_id, doc.workspace_id, embedded_count, duration_ms, job_id=job_id)
        INDEX_DOCUMENT_TOTAL.labels(status="success").inc()
        INDEX_DURATION_SECONDS.observe(duration_ms / 1000)
        return embedded_count
    finally:
        Path(path).unlink(missing_ok=True)
