"""Compliance foundation: evidence items (create, get). Linking is under compliance_controls. Phase 6: evidence metadata."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.helpers import evidence_dict as _evidence_dict
from app.core.auth_deps import require_can_admin, require_can_review
from app.core.database import get_db
from app.models import EvidenceItem, EvidenceMetadata, EVIDENCE_SOURCE_TYPES
from app.services.tag_service import list_tags_for_document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/compliance/evidence", tags=["compliance-evidence"])


class EvidenceCreateBody(BaseModel):
    title: str
    document_id: int | None = None
    source_type: str = "manual"


@router.post("", response_model=dict)
def create_evidence(
    body: EvidenceCreateBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Create an evidence item. Requires admin. Enforces workspace isolation."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    if body.source_type not in EVIDENCE_SOURCE_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid source_type. Allowed: {EVIDENCE_SOURCE_TYPES}")
    e = EvidenceItem(
        workspace_id=ws,
        document_id=body.document_id,
        source_type=body.source_type,
        title=body.title.strip(),
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return _evidence_dict(e)


@router.get("/{evidence_id}", response_model=dict)
def get_evidence(
    evidence_id: int,
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Get an evidence item by id. Enforces workspace isolation."""
    ws = session.get("workspace_id")
    if ws is None:
        raise HTTPException(status_code=403, detail="No workspace")
    e = db.query(EvidenceItem).filter(
        EvidenceItem.id == evidence_id,
        EvidenceItem.workspace_id == ws,
    ).first()
    if not e:
        raise HTTPException(status_code=404, detail="Evidence not found")
    tags = list_tags_for_document(db, e.document_id, ws) if e.document_id else []
    return _evidence_dict(e, tags=tags)


def _ensure_evidence_workspace(db: Session, evidence_id: int, workspace_id: int) -> EvidenceItem | None:
    return db.query(EvidenceItem).filter(
        EvidenceItem.id == evidence_id,
        EvidenceItem.workspace_id == workspace_id,
    ).first()


class EvidenceMetadataBody(BaseModel):
    expires_at: str | None = None
    freshness_date: str | None = None


def _parse_iso_datetime(s: str | None):
    if not s or not s.strip():
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


@router.get("/{evidence_id}/metadata", response_model=dict)
def get_evidence_metadata(
    evidence_id: int,
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Get evidence metadata (freshness_date, expires_at). Enforces workspace isolation."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    if not _ensure_evidence_workspace(db, evidence_id, ws):
        raise HTTPException(status_code=404, detail="Evidence not found")
    meta = db.query(EvidenceMetadata).filter(EvidenceMetadata.evidence_id == evidence_id).first()
    if not meta:
        return {"evidence_id": evidence_id, "freshness_date": None, "expires_at": None, "last_verified_at": None}
    return {
        "evidence_id": evidence_id,
        "freshness_date": meta.freshness_date.isoformat() if meta.freshness_date else None,
        "expires_at": meta.expires_at.isoformat() if meta.expires_at else None,
        "last_verified_at": meta.last_verified_at.isoformat() if meta.last_verified_at else None,
    }


@router.patch("/{evidence_id}/metadata", response_model=dict)
def update_evidence_metadata(
    evidence_id: int,
    body: EvidenceMetadataBody,
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Set evidence metadata (expires_at, freshness_date). Create or update. Requires review. Enforces workspace isolation."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    if not _ensure_evidence_workspace(db, evidence_id, ws):
        raise HTTPException(status_code=404, detail="Evidence not found")
    meta = db.query(EvidenceMetadata).filter(EvidenceMetadata.evidence_id == evidence_id).first()
    if not meta:
        meta = EvidenceMetadata(evidence_id=evidence_id)
        db.add(meta)
    updates = body.model_dump(exclude_unset=True)
    if "expires_at" in updates:
        meta.expires_at = _parse_iso_datetime(body.expires_at) if body.expires_at else None
    if "freshness_date" in updates:
        meta.freshness_date = _parse_iso_datetime(body.freshness_date) if body.freshness_date else None
    db.commit()
    db.refresh(meta)
    return {
        "evidence_id": evidence_id,
        "freshness_date": meta.freshness_date.isoformat() if meta.freshness_date else None,
        "expires_at": meta.expires_at.isoformat() if meta.expires_at else None,
        "last_verified_at": meta.last_verified_at.isoformat() if meta.last_verified_at else None,
    }
