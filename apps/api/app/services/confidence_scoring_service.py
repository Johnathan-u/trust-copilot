"""Source confidence scoring algorithm (P1-46).

Scores evidence based on source type, freshness, human approval, and completeness.
Provides rational basis for preferring one evidence source over another.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.control_evidence_link import ControlEvidenceLink
from app.models.evidence_item import EvidenceItem
from app.models.evidence_metadata import EvidenceMetadata

logger = logging.getLogger(__name__)

SOURCE_TYPE_WEIGHTS = {
    "integration": 0.9,
    "ai": 0.6,
    "manual": 0.7,
    "document": 0.75,
    "slack": 0.5,
    "gmail": 0.5,
}


def score_evidence(db: Session, evidence_id: int) -> dict:
    ev = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_id).first()
    if not ev:
        return {"error": "Evidence not found"}

    source_score = SOURCE_TYPE_WEIGHTS.get(ev.source_type, 0.5)

    freshness_score = _freshness_score(db, evidence_id, ev.created_at)

    approval_score = _approval_score(ev)

    completeness_score = _completeness_score(ev)

    weights = {"source_type": 0.25, "freshness": 0.30, "approval": 0.25, "completeness": 0.20}
    total = (
        source_score * weights["source_type"]
        + freshness_score * weights["freshness"]
        + approval_score * weights["approval"]
        + completeness_score * weights["completeness"]
    )

    link = db.query(ControlEvidenceLink).filter(ControlEvidenceLink.evidence_id == evidence_id).first()
    if link:
        link.confidence_score = round(total, 3)
        db.flush()

    return {
        "evidence_id": evidence_id,
        "total_score": round(total, 3),
        "breakdown": {
            "source_type": round(source_score, 3),
            "freshness": round(freshness_score, 3),
            "approval": round(approval_score, 3),
            "completeness": round(completeness_score, 3),
        },
        "weights": weights,
    }


def score_all_for_control(db: Session, control_id: int) -> list[dict]:
    links = db.query(ControlEvidenceLink).filter(ControlEvidenceLink.control_id == control_id).all()
    results = []
    for link in links:
        result = score_evidence(db, link.evidence_id)
        if "error" not in result:
            results.append(result)
    results.sort(key=lambda r: r["total_score"], reverse=True)
    return results


def _freshness_score(db: Session, evidence_id: int, created_at: datetime) -> float:
    meta = db.query(EvidenceMetadata).filter(EvidenceMetadata.evidence_id == evidence_id).first()
    now = datetime.now(timezone.utc)
    ref_date = None
    if meta and meta.freshness_date:
        ref_date = meta.freshness_date
    elif meta and meta.last_verified_at:
        ref_date = meta.last_verified_at
    else:
        ref_date = created_at
    if ref_date and ref_date.tzinfo is None:
        ref_date = ref_date.replace(tzinfo=timezone.utc)
    age_days = (now - ref_date).days if ref_date else 365
    if age_days <= 7:
        return 1.0
    elif age_days <= 30:
        return 0.9
    elif age_days <= 90:
        return 0.7
    elif age_days <= 180:
        return 0.5
    elif age_days <= 365:
        return 0.3
    return 0.1


def _approval_score(ev: EvidenceItem) -> float:
    status = getattr(ev, "approval_status", None)
    if status == "approved":
        return 1.0
    elif status == "pending":
        return 0.5
    elif status == "rejected":
        return 0.1
    return 0.5


def _completeness_score(ev: EvidenceItem) -> float:
    score = 0.0
    if ev.title:
        score += 0.4
    if ev.source_metadata:
        score += 0.3
    if ev.document_id:
        score += 0.3
    return min(score, 1.0)
