"""Trust promise library (E2-08, E2-10, E2-11, E2-12, E2-13)."""

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.trust_promise import TrustPromise

logger = logging.getLogger(__name__)

_RETENTION_RE = re.compile(r"(\d+)\s*(day|days|month|months|year|years)", re.I)


def create_promise(
    db: Session,
    workspace_id: int,
    promise_text: str,
    source_type: str,
    **kwargs,
) -> dict:
    p = TrustPromise(
        workspace_id=workspace_id,
        promise_text=promise_text,
        source_type=source_type,
        source_ref_id=kwargs.get("source_ref_id"),
        owner_user_id=kwargs.get("owner_user_id"),
        expires_at=kwargs.get("expires_at"),
        review_at=kwargs.get("review_at"),
        control_ids_json=json.dumps(kwargs.get("control_ids") or []),
        evidence_ids_json=json.dumps(kwargs.get("evidence_ids") or []),
        deal_id=kwargs.get("deal_id"),
        contract_document_id=kwargs.get("contract_document_id"),
        topic_key=kwargs.get("topic_key") or _infer_topic(promise_text),
        status=kwargs.get("status", "active"),
    )
    db.add(p)
    db.flush()
    return _serialize(p)


def get_promise(db: Session, promise_id: int) -> dict | None:
    p = db.query(TrustPromise).filter(TrustPromise.id == promise_id).first()
    return _serialize(p) if p else None


def list_promises(db: Session, workspace_id: int, status: str | None = None, deal_id: int | None = None) -> list[dict]:
    q = db.query(TrustPromise).filter(TrustPromise.workspace_id == workspace_id)
    if status:
        q = q.filter(TrustPromise.status == status)
    if deal_id is not None:
        q = q.filter(TrustPromise.deal_id == deal_id)
    return [_serialize(x) for x in q.order_by(TrustPromise.created_at.desc()).all()]


def map_promise_to_controls(db: Session, promise_id: int, control_ids: list[int]) -> dict | None:
    """E2-10: Map promise to controls."""
    p = db.query(TrustPromise).filter(TrustPromise.id == promise_id).first()
    if not p:
        return None
    p.control_ids_json = json.dumps(control_ids)
    db.flush()
    return _serialize(p)


def promise_coverage(db: Session, promise_id: int) -> dict:
    """E2-10: Which controls are linked and simple backing heuristic."""
    p = db.query(TrustPromise).filter(TrustPromise.id == promise_id).first()
    if not p:
        return {"error": "Promise not found"}
    cids = json.loads(p.control_ids_json or "[]")
    from app.models.workspace_control import WorkspaceControl

    backed = 0
    gaps = []
    for cid in cids:
        wc = db.query(WorkspaceControl).filter(WorkspaceControl.id == cid).first()
        if wc and wc.status in ("implemented", "verified"):
            backed += 1
        else:
            gaps.append(cid)
    return {
        "promise_id": promise_id,
        "control_ids": cids,
        "fully_backed": len(cids) > 0 and backed == len(cids),
        "backed_count": backed,
        "gap_control_ids": gaps,
    }


def detect_contradictions(db: Session, workspace_id: int) -> list[dict]:
    """E2-11: Flag conflicting numeric retention-style claims per topic_key."""
    promises = db.query(TrustPromise).filter(
        TrustPromise.workspace_id == workspace_id,
        TrustPromise.status == "active",
    ).all()
    by_topic: dict[str, list[tuple[int, int | None, str]]] = {}
    for p in promises:
        key = p.topic_key or "general"
        m = _RETENTION_RE.search(p.promise_text)
        val = _retention_days(m) if m else None
        by_topic.setdefault(key, []).append((p.id, val, p.promise_text[:200]))
    out = []
    for topic, rows in by_topic.items():
        nums = {r[1] for r in rows if r[1] is not None}
        if len(nums) > 1:
            out.append({
                "topic_key": topic,
                "type": "retention_numeric_mismatch",
                "values_days": sorted(nums),
                "promise_ids": [r[0] for r in rows],
                "snippets": [r[2] for r in rows],
            })
    return out


def _retention_days(match: re.Match) -> int | None:
    n = int(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("year"):
        return n * 365
    if unit.startswith("month"):
        return n * 30
    return n


def _infer_topic(text: str) -> str:
    t = text.lower()
    if "retention" in t or "delete" in t:
        return "data_retention"
    if "encrypt" in t:
        return "encryption"
    if "mfa" in t or "multi-factor" in t:
        return "mfa"
    return "general"


def get_expiring_promises(db: Session, workspace_id: int, within_days: int = 30) -> list[dict]:
    """E2-12."""
    threshold = datetime.now(timezone.utc) + timedelta(days=within_days)
    rows = (
        db.query(TrustPromise)
        .filter(
            TrustPromise.workspace_id == workspace_id,
            TrustPromise.status == "active",
            TrustPromise.expires_at.isnot(None),
            TrustPromise.expires_at <= threshold,
        )
        .order_by(TrustPromise.expires_at.asc())
        .all()
    )
    return [_serialize(p) for p in rows]


def promise_dashboard(db: Session, workspace_id: int) -> dict:
    """E2-13."""
    all_p = db.query(TrustPromise).filter(TrustPromise.workspace_id == workspace_id).all()
    total = len(all_p)
    active = sum(1 for p in all_p if p.status == "active")
    contradictions = detect_contradictions(db, workspace_id)
    expiring = get_expiring_promises(db, workspace_id, 60)
    with_evidence = 0
    stale_evidence = 0
    for p in all_p:
        ev = json.loads(p.evidence_ids_json or "[]")
        if ev:
            with_evidence += 1
    backed = 0
    for p in all_p:
        cov = promise_coverage(db, p.id)
        if "error" not in cov and cov.get("fully_backed"):
            backed += 1
    return {
        "total_promises": total,
        "active": active,
        "backed_by_passing_controls": backed,
        "with_linked_evidence": with_evidence,
        "contradiction_groups": len(contradictions),
        "expiring_within_60_days": len(expiring),
        "contradictions": contradictions[:10],
        "expiring_sample": expiring[:10],
    }


def update_promise(db: Session, promise_id: int, **updates) -> dict | None:
    p = db.query(TrustPromise).filter(TrustPromise.id == promise_id).first()
    if not p:
        return None
    allowed = {"status", "owner_user_id", "expires_at", "review_at", "promise_text"}
    for k, v in updates.items():
        if k in allowed:
            setattr(p, k, v)
    if "control_ids" in updates:
        p.control_ids_json = json.dumps(updates["control_ids"])
    if "evidence_ids" in updates:
        p.evidence_ids_json = json.dumps(updates["evidence_ids"])
    db.flush()
    return _serialize(p)


def _serialize(p: TrustPromise) -> dict:
    return {
        "id": p.id,
        "workspace_id": p.workspace_id,
        "promise_text": p.promise_text,
        "source_type": p.source_type,
        "source_ref_id": p.source_ref_id,
        "owner_user_id": p.owner_user_id,
        "expires_at": p.expires_at.isoformat() if p.expires_at else None,
        "review_at": p.review_at.isoformat() if p.review_at else None,
        "control_ids": json.loads(p.control_ids_json or "[]"),
        "evidence_ids": json.loads(p.evidence_ids_json or "[]"),
        "deal_id": p.deal_id,
        "contract_document_id": p.contract_document_id,
        "topic_key": p.topic_key,
        "status": p.status,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }
