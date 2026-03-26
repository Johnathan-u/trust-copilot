"""Contract ingestion and mock clause extraction (E2-09)."""

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.trust_promise import ContractDocument, TrustPromise

logger = logging.getLogger(__name__)


def ingest_contract(
    db: Session,
    workspace_id: int,
    title: str,
    uploaded_by_user_id: int | None = None,
    original_filename: str | None = None,
    body_text: str | None = None,
) -> dict:
    """Store contract and populate mock extracted clauses as TrustPromise seeds."""
    clauses = _mock_extract_clauses(body_text or title)
    doc = ContractDocument(
        workspace_id=workspace_id,
        title=title,
        original_filename=original_filename,
        clauses_json=json.dumps(clauses),
        status="ready",
        uploaded_by_user_id=uploaded_by_user_id,
    )
    db.add(doc)
    db.flush()
    created_promises = []
    for c in clauses:
        p = TrustPromise(
            workspace_id=workspace_id,
            promise_text=c["text"],
            source_type="contract_clause",
            source_ref_id=doc.id,
            contract_document_id=doc.id,
            topic_key=c.get("topic_key"),
            owner_user_id=uploaded_by_user_id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=365),
            review_at=datetime.now(timezone.utc) + timedelta(days=180),
            status="active",
        )
        db.add(p)
        db.flush()
        created_promises.append(p.id)
    db.flush()
    return {
        "document_id": doc.id,
        "title": doc.title,
        "clauses": clauses,
        "promise_ids": created_promises,
    }


def list_contracts(db: Session, workspace_id: int) -> list[dict]:
    rows = db.query(ContractDocument).filter(ContractDocument.workspace_id == workspace_id).order_by(ContractDocument.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "status": r.status,
            "clause_count": len(json.loads(r.clauses_json or "[]")),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def _mock_extract_clauses(text: str) -> list[dict]:
    """Deterministic mock extraction for tests."""
    lower = text.lower()
    clauses = []
    if "retention" in lower or "90" in text:
        clauses.append({"text": "Customer data retained for 90 days after account closure", "topic_key": "data_retention"})
    if "breach" in lower or "notification" in lower:
        clauses.append({"text": "Security incidents notified within 72 hours of discovery", "topic_key": "incident_notification"})
    if "encrypt" in lower or "aes" in lower:
        clauses.append({"text": "Data encrypted at rest using industry-standard algorithms", "topic_key": "encryption"})
    if not clauses:
        clauses.append({"text": f"General commitment derived from: {text[:120]}", "topic_key": "general"})
    return clauses
