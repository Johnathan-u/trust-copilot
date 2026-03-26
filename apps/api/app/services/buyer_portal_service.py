"""Buyer portal: token access, snapshots, instant match, escalations, satisfaction, subscriptions (E4-20..E4-24)."""

import json
import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.buyer_portal import (
    BuyerChangeSubscription,
    BuyerEscalation,
    BuyerPortal,
    BuyerPortalSnapshot,
    BuyerSatisfactionSignal,
)
from app.models.evidence_item import EvidenceItem
from app.models.golden_answer import GoldenAnswer
from app.models.workspace_control import WorkspaceControl


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _unique_portal_token(db: Session) -> str:
    for _ in range(20):
        t = secrets.token_urlsafe(48)[:72]
        if not db.query(BuyerPortal).filter(BuyerPortal.portal_token == t).first():
            return t
    raise RuntimeError("Could not allocate portal token")


def create_portal(
    db: Session,
    workspace_id: int,
    display_name: str,
    frameworks_filter_json: str | None = None,
) -> dict:
    p = BuyerPortal(
        workspace_id=workspace_id,
        portal_token=_unique_portal_token(db),
        display_name=display_name,
        frameworks_filter_json=frameworks_filter_json,
        active=True,
    )
    db.add(p)
    db.flush()
    return _portal_dict(p)


def list_portals(db: Session, workspace_id: int) -> list[dict]:
    rows = (
        db.query(BuyerPortal)
        .filter(BuyerPortal.workspace_id == workspace_id)
        .order_by(BuyerPortal.created_at.desc())
        .all()
    )
    return [_portal_dict(r) for r in rows]


def get_portal_by_token(db: Session, token: str) -> BuyerPortal | None:
    return (
        db.query(BuyerPortal)
        .filter(BuyerPortal.portal_token == token, BuyerPortal.active.is_(True))
        .first()
    )


def capabilities_manifest(portal: BuyerPortal) -> dict:
    return {
        "display_name": portal.display_name,
        "workspace_id": portal.workspace_id,
        "features": {
            "instant_questionnaire_match": True,
            "trust_center_browse": True,
            "gated_documents_nda": True,
            "change_tracking": True,
            "escalations": True,
            "satisfaction_signals": True,
            "change_subscriptions": True,
        },
        "frameworks_filter": json.loads(portal.frameworks_filter_json)
        if portal.frameworks_filter_json
        else None,
    }


def _snapshot_payload(db: Session, workspace_id: int) -> dict:
    ga_count = db.query(GoldenAnswer).filter(GoldenAnswer.workspace_id == workspace_id).count()
    ev_count = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == workspace_id).count()
    wc = db.query(WorkspaceControl).filter(WorkspaceControl.workspace_id == workspace_id).all()
    by_status: dict[str, int] = {}
    for c in wc:
        by_status[c.status] = by_status.get(c.status, 0) + 1
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "golden_answers_count": ga_count,
        "evidence_items_count": ev_count,
        "workspace_control_status_counts": by_status,
    }


def capture_snapshot(db: Session, portal: BuyerPortal) -> dict:
    payload = _snapshot_payload(db, portal.workspace_id)
    snap = BuyerPortalSnapshot(
        workspace_id=portal.workspace_id,
        portal_id=portal.id,
        snapshot_json=json.dumps(payload),
    )
    db.add(snap)
    db.flush()
    return {"id": snap.id, "snapshot": payload}


def list_snapshots(db: Session, workspace_id: int, portal_id: int, limit: int = 20) -> list[dict]:
    rows = (
        db.query(BuyerPortalSnapshot)
        .filter(
            BuyerPortalSnapshot.workspace_id == workspace_id,
            BuyerPortalSnapshot.portal_id == portal_id,
        )
        .order_by(BuyerPortalSnapshot.created_at.desc())
        .limit(limit)
        .all()
    )
    out = []
    for r in rows:
        out.append(
            {
                "id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "snapshot": json.loads(r.snapshot_json),
            }
        )
    return out


def summarize_changes_between_snapshots(prev_json: dict, cur_json: dict) -> dict:
    keys = ("golden_answers_count", "evidence_items_count")
    deltas = {}
    for k in keys:
        a, b = prev_json.get(k), cur_json.get(k)
        if isinstance(a, int) and isinstance(b, int):
            deltas[k] = b - a
    prev_ctrl = prev_json.get("workspace_control_status_counts") or {}
    cur_ctrl = cur_json.get("workspace_control_status_counts") or {}
    all_status = set(prev_ctrl) | set(cur_ctrl)
    control_deltas = {s: cur_ctrl.get(s, 0) - prev_ctrl.get(s, 0) for s in all_status}
    return {"deltas": deltas, "control_status_deltas": control_deltas}


def get_latest_change_summary(db: Session, portal: BuyerPortal) -> dict | None:
    rows = (
        db.query(BuyerPortalSnapshot)
        .filter(BuyerPortalSnapshot.portal_id == portal.id)
        .order_by(BuyerPortalSnapshot.created_at.desc())
        .limit(2)
        .all()
    )
    if len(rows) < 2:
        return None
    cur = json.loads(rows[0].snapshot_json)
    prev = json.loads(rows[1].snapshot_json)
    return summarize_changes_between_snapshots(prev, cur)


def _evidence_signal_mix(db: Session, workspace_id: int, evidence_ids: list[int]) -> str:
    if not evidence_ids:
        return "static"
    live_types = {"integration", "slack", "gmail"}
    items = (
        db.query(EvidenceItem)
        .filter(
            EvidenceItem.workspace_id == workspace_id,
            EvidenceItem.id.in_(evidence_ids),
        )
        .all()
    )
    if any((i.source_type or "") in live_types for i in items):
        return "live_signals"
    return "documents"


def match_questions(db: Session, workspace_id: int, questions: list[str]) -> list[dict]:
    goldens = (
        db.query(GoldenAnswer)
        .filter(
            GoldenAnswer.workspace_id == workspace_id,
            GoldenAnswer.status == "approved",
        )
        .all()
    )
    results = []
    for q in questions:
        nq = _norm(q)
        wq = set(nq.split()) if nq else set()
        best = None
        best_score = 0.0
        for ga in goldens:
            ng = _norm(ga.question_text)
            wg = set(ng.split()) if ng else set()
            if not wq or not wg:
                continue
            overlap = len(wq & wg) / max(len(wq), 1)
            if nq in ng or ng in nq:
                overlap = max(overlap, 0.88)
            if overlap > best_score:
                best_score = overlap
                best = ga
        need_review = best is None or best_score < 0.25
        if best and best.confidence is not None and best.confidence < 0.45:
            need_review = True
        ev_ids: list[int] = []
        if best and best.evidence_ids_json:
            try:
                ev_ids = json.loads(best.evidence_ids_json) or []
            except json.JSONDecodeError:
                ev_ids = []
        signal = _evidence_signal_mix(db, workspace_id, ev_ids) if best else "none"
        results.append(
            {
                "question": q,
                "match_score": round(best_score, 4),
                "need_seller_review": need_review,
                "golden_answer_id": best.id if best else None,
                "answer_text": best.answer_text if best else None,
                "confidence": best.confidence if best else None,
                "signal_backing": signal,
            }
        )
    return results


def create_escalation(
    db: Session,
    workspace_id: int,
    portal_id: int | None,
    buyer_email: str,
    escalation_type: str,
    message: str,
    question_snippet: str | None = None,
    answer_id: int | None = None,
) -> dict:
    e = BuyerEscalation(
        workspace_id=workspace_id,
        portal_id=portal_id,
        buyer_email=buyer_email,
        escalation_type=escalation_type,
        question_snippet=question_snippet,
        message=message,
        answer_id=answer_id,
        status="open",
    )
    db.add(e)
    db.flush()
    return _escalation_dict(e)


def list_escalations(
    db: Session, workspace_id: int, status: str | None = None
) -> list[dict]:
    q = db.query(BuyerEscalation).filter(BuyerEscalation.workspace_id == workspace_id)
    if status:
        q = q.filter(BuyerEscalation.status == status)
    rows = q.order_by(BuyerEscalation.created_at.desc()).all()
    return [_escalation_dict(r) for r in rows]


def update_escalation(
    db: Session,
    escalation_id: int,
    workspace_id: int,
    status: str | None = None,
    seller_notes: str | None = None,
) -> dict | None:
    e = (
        db.query(BuyerEscalation)
        .filter(
            BuyerEscalation.id == escalation_id,
            BuyerEscalation.workspace_id == workspace_id,
        )
        .first()
    )
    if not e:
        return None
    if status is not None:
        e.status = status
        if status == "resolved":
            e.resolved_at = datetime.now(timezone.utc)
    if seller_notes is not None:
        e.seller_notes = seller_notes
    db.flush()
    return _escalation_dict(e)


def record_satisfaction(
    db: Session,
    workspace_id: int,
    portal_id: int | None,
    questionnaire_id: int | None = None,
    accepted_without_edits: bool | None = None,
    follow_up_count: int | None = None,
    cycle_hours: float | None = None,
    deal_closed: bool | None = None,
    extra_json: str | None = None,
) -> dict:
    s = BuyerSatisfactionSignal(
        workspace_id=workspace_id,
        portal_id=portal_id,
        questionnaire_id=questionnaire_id,
        accepted_without_edits=accepted_without_edits,
        follow_up_count=follow_up_count,
        cycle_hours=cycle_hours,
        deal_closed=deal_closed,
        extra_json=extra_json,
    )
    db.add(s)
    db.flush()
    return _satisfaction_dict(s)


def subscribe_changes(
    db: Session,
    portal_id: int,
    email: str,
    frameworks_json: str | None = None,
) -> dict:
    sub = BuyerChangeSubscription(
        portal_id=portal_id,
        email=email,
        frameworks_json=frameworks_json,
        active=True,
    )
    db.add(sub)
    db.flush()
    return {
        "id": sub.id,
        "portal_id": sub.portal_id,
        "email": sub.email,
        "active": sub.active,
    }


def list_subscriptions(db: Session, workspace_id: int, portal_id: int) -> list[dict]:
    portal = (
        db.query(BuyerPortal)
        .filter(BuyerPortal.id == portal_id, BuyerPortal.workspace_id == workspace_id)
        .first()
    )
    if not portal:
        return []
    rows = (
        db.query(BuyerChangeSubscription)
        .filter(BuyerChangeSubscription.portal_id == portal_id)
        .order_by(BuyerChangeSubscription.created_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "email": r.email,
            "frameworks_json": r.frameworks_json,
            "active": r.active,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def _portal_dict(p: BuyerPortal) -> dict:
    return {
        "id": p.id,
        "workspace_id": p.workspace_id,
        "portal_token": p.portal_token,
        "display_name": p.display_name,
        "frameworks_filter_json": p.frameworks_filter_json,
        "active": p.active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _escalation_dict(e: BuyerEscalation) -> dict:
    return {
        "id": e.id,
        "workspace_id": e.workspace_id,
        "portal_id": e.portal_id,
        "buyer_email": e.buyer_email,
        "escalation_type": e.escalation_type,
        "question_snippet": e.question_snippet,
        "message": e.message,
        "answer_id": e.answer_id,
        "status": e.status,
        "seller_notes": e.seller_notes,
        "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def _satisfaction_dict(s: BuyerSatisfactionSignal) -> dict:
    return {
        "id": s.id,
        "workspace_id": s.workspace_id,
        "portal_id": s.portal_id,
        "questionnaire_id": s.questionnaire_id,
        "accepted_without_edits": s.accepted_without_edits,
        "follow_up_count": s.follow_up_count,
        "cycle_hours": s.cycle_hours,
        "deal_closed": s.deal_closed,
        "extra_json": s.extra_json,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }
