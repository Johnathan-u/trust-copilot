"""Phase 2: Gap detection - controls with no or low-confidence evidence.

Each applicable control is explained with a state, a rule, and a next step.
A file count is not enough. GET does not write.
"""

import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_can_review
from app.core.database import get_db
from app.core.idempotency import claim as idempotency_claim
from app.core.idempotency import get as idempotency_get
from app.core.idempotency import release as idempotency_release
from app.core.idempotency import set as idempotency_set
from app.models import (
    CONTROL_CHECK,
    Document,
    CONTROL_CHECK_CLOSE_REASON,
    EvidenceGap,
    EvidenceItem,
    EvidenceMetadata,
    WorkspaceControl,
    FrameworkControl,
    Framework,
    ControlEvidenceLink,
)
from app.models.ai_mapping import QuestionMappingPreference
from app.models.questionnaire import Question, Questionnaire
from app.api.constants import LOW_CONFIDENCE_THRESHOLD
from app.services.in_app_notification_service import notify_admins

logger = logging.getLogger(__name__)

CONTROL_NOT_FOUND = "Control not found"
_BLOCKED_RIGHTS = {"blocked_pending_rights", "blocked"}
_ACTIONS = {
    "no_evidence": "collect_evidence",
    "not_approved": "approve_evidence",
    "deleted_document": "replace_deleted_evidence",
    "foreign_evidence": "replace_evidence",
    "expired": "refresh_evidence",
    "missing_evidence_row": "resolve_reference",
    "missing_document": "resolve_reference",
    "missing_framework": "resolve_reference",
    "check_error": "retry_check",
}
_SEVERITY = {"gap": 1, "stale": 2, "unknown": 3, "failed": 4}

router = APIRouter(prefix="/compliance/gaps", tags=["compliance-gaps"])

_last_gap_notify: dict[int, float] = {}
GAP_NOTIFY_COOLDOWN = 3600
# Injectable clock (tests replace it with a fixed/fake clock). time.monotonic counts from
# host boot, so it must never be compared against a 0 default (see scan_and_notify_gaps).
_clock = time.monotonic

_QUESTION_TEXT_PREVIEW_LEN = 160


def _truncate_question_text(text: str | None, max_len: int = _QUESTION_TEXT_PREVIEW_LEN) -> str:
    t = (text or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _control_display_fields(
    db: Session, wc: WorkspaceControl
) -> tuple[str | None, str | None, str | None]:
    framework_name = None
    control_key = None
    title = wc.custom_name or None
    if wc.framework_control_id:
        fc = (
            db.query(FrameworkControl)
            .filter(FrameworkControl.id == wc.framework_control_id)
            .first()
        )
        if fc:
            control_key = fc.control_key
            title = title or fc.title
            fw = db.query(Framework).filter(Framework.id == fc.framework_id).first()
            if fw:
                framework_name = fw.name
    return control_key, title, framework_name


def _scope(db: Session, wc: WorkspaceControl) -> str:
    """applicable, unknown, or skipped. Blocked catalogs are not applicable."""
    if not wc.framework_control_id:
        return "applicable"
    fc = db.query(FrameworkControl).filter(FrameworkControl.id == wc.framework_control_id).first()
    if fc is None:
        return "unknown"
    fw = db.query(Framework).filter(Framework.id == fc.framework_id).first()
    if fw is None:
        return "unknown"
    if (fw.rights_status or "").strip().lower() in _BLOCKED_RIGHTS:
        return "skipped"
    return "applicable"


def _classify_evidence(
    db: Session, ev: EvidenceItem | None, evidence_id: int, workspace_id: int, now
):
    if ev is None:
        return "unknown", "missing_evidence_row", evidence_id
    if ev.workspace_id != workspace_id:
        # Another workspace's evidence id is not returned. Treat the link as missing.
        return "unknown", "missing_evidence_row", None
    if ev.approval_status != "approved":
        return "gap", "not_approved", ev.id
    if ev.document_id is not None:
        doc = db.query(Document).filter(Document.id == ev.document_id).first()
        if doc is None or doc.workspace_id != workspace_id:
            return "unknown", "missing_document", ev.id
        if doc.deleted_at is not None:
            return "gap", "deleted_document", ev.id
    metas = db.query(EvidenceMetadata).filter(EvidenceMetadata.evidence_id == ev.id).all()
    for meta in metas:
        if meta.expires_at is not None and meta.expires_at <= now:
            return "stale", "expired", ev.id
    return "clear", None, ev.id


def _next_step(wc: WorkspaceControl, rule: str) -> dict:
    owner = wc.owner_user_id
    return {
        "owner_user_id": owner,
        "owner_missing": owner is None,
        "action": _ACTIONS[rule],
    }


def _gap_row(
    db: Session, wc: WorkspaceControl, state: str, rule: str, evidence_ids: list[int]
) -> dict:
    link_stats = (
        db.query(
            func.count(ControlEvidenceLink.id),
            func.max(ControlEvidenceLink.confidence_score),
        ).filter(ControlEvidenceLink.control_id == wc.id)
    ).first()
    evidence_count = link_stats[0] or 0
    max_conf = link_stats[1]
    control_key, title, framework_name = _control_display_fields(db, wc)
    reason = {"rule": rule, "control_id": wc.id, "evidence_ids": evidence_ids}
    return {
        "control_id": wc.id,
        "control_key": control_key,
        "name": title,
        "framework": framework_name,
        "evidence_count": evidence_count,
        "max_confidence": round(float(max_conf), 4) if max_conf is not None else None,
        "gap_reason": rule,
        "state": state,
        "rule": rule,
        "evidence_ids": evidence_ids,
        "reason": reason,
        "next_step": _next_step(wc, rule),
    }


def evaluate_control(db: Session, wc: WorkspaceControl, workspace_id: int) -> dict | None:
    """Return a gap, unknown, stale, or failed result. None means the control is clear."""
    try:
        scope = _scope(db, wc)
        if scope == "skipped":
            return None
        if scope == "unknown":
            return _gap_row(db, wc, "unknown", "missing_framework", [])
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        links = db.query(ControlEvidenceLink).filter(ControlEvidenceLink.control_id == wc.id).all()
        if not links:
            return _gap_row(db, wc, "gap", "no_evidence", [])
        best: tuple[str, str, int] | None = None
        evidence_ids: list[int] = []
        for link in links:
            ev = db.query(EvidenceItem).filter(EvidenceItem.id == link.evidence_id).first()
            state, rule, evidence_id = _classify_evidence(
                db, ev, link.evidence_id, workspace_id, now
            )
            if state == "clear":
                return None
            if evidence_id is not None:
                evidence_ids.append(evidence_id)
            if best is None or _SEVERITY[state] > _SEVERITY[best[0]]:
                best = (state, rule, evidence_id)
        assert best is not None
        return _gap_row(db, wc, best[0], best[1], evidence_ids)
    except Exception:
        logger.exception("compliance gap check failed", extra={"control_id": wc.id})
        return _gap_row(db, wc, "failed", "check_error", [])


def global_gaps_list(
    db: Session,
    workspace_id: int,
    low_confidence_threshold: float,
) -> list[dict]:
    """Applicable controls that are gap, unknown, stale, or failed.

    ``low_confidence_threshold`` is accepted for callers and is not a pass.
    A count of linked files is not a pass.
    """
    del low_confidence_threshold
    rows = db.query(WorkspaceControl).filter(WorkspaceControl.workspace_id == workspace_id).all()
    out = []
    for wc in rows:
        item = evaluate_control(db, wc, workspace_id)
        if item is not None:
            out.append(item)
    return out


def questionnaire_evidence_gaps_list(db: Session, workspace_id: int) -> list[dict]:
    """
    Approved / manual questionnaire mappings whose workspace control has zero ControlEvidenceLink rows.
    Grouped by control; questionnaire_refs lists unique question sources (deduped by questionnaire + question).
    """
    mappings = (
        db.query(QuestionMappingPreference)
        .filter(
            QuestionMappingPreference.workspace_id == workspace_id,
            QuestionMappingPreference.status.in_(("approved", "manual")),
            QuestionMappingPreference.preferred_control_id.isnot(None),
        )
        .all()
    )
    if not mappings:
        return []

    ctrl_ids = sorted({int(m.preferred_control_id) for m in mappings})
    wcs = {
        wc.id: wc
        for wc in db.query(WorkspaceControl)
        .filter(
            WorkspaceControl.workspace_id == workspace_id,
            WorkspaceControl.id.in_(ctrl_ids),
        )
        .all()
    }

    qnr_ids = {m.questionnaire_id for m in mappings if m.questionnaire_id is not None}
    question_ids = {m.question_id for m in mappings if m.question_id is not None}
    qnr_by_id: dict[int, Questionnaire] = {}
    if qnr_ids:
        qnr_by_id = {
            q.id: q for q in db.query(Questionnaire).filter(Questionnaire.id.in_(qnr_ids)).all()
        }
    q_by_id: dict[int, Question] = {}
    if question_ids:
        q_by_id = {q.id: q for q in db.query(Question).filter(Question.id.in_(question_ids)).all()}

    by_control: dict[int, list[QuestionMappingPreference]] = defaultdict(list)
    for m in mappings:
        cid = int(m.preferred_control_id)
        from app.api.routes.compliance_controls import _has_qualifying_evidence

        if _has_qualifying_evidence(db, cid, workspace_id):
            continue
        if cid not in wcs:
            continue
        by_control[cid].append(m)

    out: list[dict] = []
    for cid in sorted(by_control.keys()):
        wc = wcs[cid]
        control_key, title, framework_name = _control_display_fields(db, wc)
        refs: list[dict] = []
        seen: set[tuple[int | None, int | None]] = set()
        for m in sorted(
            by_control[cid],
            key=lambda x: (x.questionnaire_id or 0, x.question_id or 0),
        ):
            key = (m.questionnaire_id, m.question_id)
            if key in seen:
                continue
            seen.add(key)
            qnr = qnr_by_id.get(m.questionnaire_id) if m.questionnaire_id else None
            if qnr:
                qtitle = qnr.filename or qnr.display_id or f"Questionnaire #{qnr.id}"
            elif m.questionnaire_id is not None:
                qtitle = f"Questionnaire #{m.questionnaire_id}"
            else:
                qtitle = "Questionnaire"
            qrow = q_by_id.get(m.question_id) if m.question_id else None
            qtext = qrow.text if qrow else m.normalized_question_text
            refs.append(
                {
                    "questionnaire_id": m.questionnaire_id,
                    "questionnaire_title": qtitle,
                    "question_id": m.question_id,
                    "question_text_preview": _truncate_question_text(qtext),
                }
            )

        out.append(
            {
                "gap_kind": "questionnaire_mapping_no_evidence",
                "control_id": wc.id,
                "control_key": control_key,
                "name": title,
                "framework": framework_name,
                "evidence_link_count": 0,
                "questionnaire_refs": refs,
            }
        )

    out.sort(key=lambda r: ((r.get("control_key") or ""), r.get("control_id") or 0))
    return out


def _controls_for_read(db: Session, workspace_id: int, control_id: int | None):
    if control_id is None:
        return None
    row = (
        db.query(WorkspaceControl)
        .filter(WorkspaceControl.id == control_id, WorkspaceControl.workspace_id == workspace_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=CONTROL_NOT_FOUND)
    return row


@router.get("")
def list_gaps(
    low_confidence_threshold: float = Query(LOW_CONFIDENCE_THRESHOLD, ge=0, le=1),
    control_id: int | None = Query(None),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Read-only gap list. This route does not persist.

    A missing control id and a control from another workspace return the same 404.
    """
    ws = session.get("workspace_id")
    if ws is None:
        return {"gaps": [], "questionnaire_evidence_gaps": []}
    chosen = _controls_for_read(db, ws, control_id)
    gaps = global_gaps_list(db, ws, low_confidence_threshold)
    if chosen is not None:
        gaps = [item for item in gaps if item["control_id"] == chosen.id]
    return {
        "gaps": gaps,
        "questionnaire_evidence_gaps": questionnaire_evidence_gaps_list(db, ws),
    }


def _idempotency_key(request: Request | None, workspace_id: int) -> str | None:
    if request is None:
        return None
    raw = (request.headers.get("Idempotency-Key") or "").strip()
    if not raw:
        return None
    if len(raw) > 160:
        raise HTTPException(status_code=422, detail="Idempotency-Key is too long")
    return f"gaps:{workspace_id}:{raw}"


def _claim_or_replay(db: Session, key: str | None):
    if not key:
        return None, None
    cached = idempotency_get(db, key)
    if cached:
        return JSONResponse(content=cached[1], status_code=cached[0]), None
    owner = idempotency_claim(db, key)
    if owner is None:
        cached_again = idempotency_get(db, key)
        if cached_again:
            return JSONResponse(content=cached_again[1], status_code=cached_again[0]), None
        raise HTTPException(
            status_code=409, detail="Request in progress; retry with same Idempotency-Key"
        )
    return None, owner


def _settle(db: Session, key: str | None, owner: str | None, payload: dict | None) -> None:
    if not key or payload is None:
        return
    db.rollback()
    try:
        idempotency_set(db, key, 200, payload, owner=owner)
    except Exception:
        logger.exception("gap scan idempotency store failed after commit")
        db.rollback()
        from app.core.idempotency import set as complete_claim

        try:
            complete_claim(db, key, 200, payload, owner=owner)
        except Exception:
            logger.exception(
                "gap scan second idempotency store failed after commit; the original error is unchanged"
            )


def _lock_control_gap_writes(db: Session, control_id: int) -> None:
    """Same transaction lock as a manual open control gap (pg_advisory_xact_lock 150016)."""
    bind = db.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", None)
    if dialect != "postgresql":
        return
    db.execute(
        text("SELECT pg_advisory_xact_lock(150016, :control_id)"),
        {"control_id": int(control_id)},
    )


def _persist_control_checks(db: Session, workspace_id: int, gaps: list[dict]) -> set[int]:
    """Update open control-check rows. Return control ids a reviewer already decided.

    Accepted, dismissed, and any other non-open status stay as stored. A decided
    control does not get a second open row, and it is not included in the notify set.
    """
    if not isinstance(db, Session):
        return set()
    rows = (
        db.query(EvidenceGap)
        .filter(
            EvidenceGap.workspace_id == workspace_id,
            EvidenceGap.gap_type == CONTROL_CHECK,
            EvidenceGap.status != "resolved",
        )
        .all()
    )
    open_by_control: dict[int, list[EvidenceGap]] = defaultdict(list)
    decided: set[int] = set()
    for row in rows:
        if row.control_id is None:
            continue
        if row.status == "open":
            open_by_control[row.control_id].append(row)
        else:
            decided.add(row.control_id)
    seen: set[int] = set()
    now = datetime.now(timezone.utc)
    for item in gaps:
        control_id = int(item["control_id"])
        seen.add(control_id)
        _lock_control_gap_writes(db, control_id)
        if control_id in decided:
            continue
        refs = json.dumps(item["evidence_ids"])
        open_rows = (
            db.query(EvidenceGap)
            .filter(
                EvidenceGap.workspace_id == workspace_id,
                EvidenceGap.control_id == control_id,
                EvidenceGap.gap_type == CONTROL_CHECK,
                EvidenceGap.status == "open",
            )
            .all()
        )
        if not open_rows:
            db.add(
                EvidenceGap(
                    workspace_id=workspace_id,
                    gap_type=CONTROL_CHECK,
                    reason=json.dumps(item["reason"]),
                    status="open",
                    control_id=control_id,
                    evaluation_state=item["state"],
                    rule_code=item["rule"],
                    evidence_refs=refs,
                    next_action=item["next_step"]["action"],
                    owner_user_id=item["next_step"]["owner_user_id"],
                )
            )
        else:
            for row in open_rows:
                row.reason = json.dumps(item["reason"])
                row.evaluation_state = item["state"]
                row.rule_code = item["rule"]
                row.evidence_refs = refs
                row.next_action = item["next_step"]["action"]
                row.owner_user_id = item["next_step"]["owner_user_id"]
                row.updated_at = now
    for control_id, open_rows in open_by_control.items():
        if control_id in seen or control_id in decided:
            continue
        for row in open_rows:
            row.status = "resolved"
            row.closed_at = now
            row.close_reason = CONTROL_CHECK_CLOSE_REASON
            row.updated_at = now
    return decided


@router.post("/scan-and-notify", response_model=dict)
def scan_and_notify_gaps(
    low_confidence_threshold: float = Query(LOW_CONFIDENCE_THRESHOLD, ge=0, le=1),
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """Run a gap scan, persist the explainable results, then notify admins.

    Rate-limited to once per hour per workspace. A failed notification does not
    roll back the saved results. Idempotency-Key is optional.
    """
    ws = session.get("workspace_id")
    if ws is None:
        return {"gaps": 0, "notified": False}

    key = _idempotency_key(request, ws)
    cached, owner = _claim_or_replay(db, key)
    if cached is not None:
        return cached
    try:
        now = _clock()
        last = _last_gap_notify.get(ws)
        # No previous notification means no cooldown. (Defaulting to 0 put every workspace in
        # cooldown for the first hour after host boot, which made CI runners flaky.)
        if last is not None and now - last < GAP_NOTIFY_COOLDOWN:
            gaps = global_gaps_list(db, ws, low_confidence_threshold)
            payload = {"gaps": len(gaps), "notified": False, "reason": "cooldown"}
        else:
            gaps = global_gaps_list(db, ws, low_confidence_threshold)
            decided = _persist_control_checks(db, ws, gaps)
            if isinstance(db, Session):
                db.commit()
            actionable = [item for item in gaps if int(item["control_id"]) not in decided]
            payload = {
                "gaps": len(gaps),
                "notified": False,
                "persisted": len(gaps),
                "states": sorted({item.get("state", "gap") for item in gaps}),
            }
            if actionable:
                try:
                    body = ", ".join(
                        f"{item.get('state', 'gap')}:{item.get('rule', item.get('gap_reason', 'gap'))}"
                        for item in actionable[:12]
                    )
                    notify_admins(
                        db,
                        ws,
                        f"{len(actionable)} compliance gap(s) detected",
                        body,
                        category="warning",
                        link="/dashboard/compliance-gaps",
                    )
                    _last_gap_notify[ws] = now
                    payload["notified"] = True
                except Exception:
                    db.rollback()
                    payload["notified"] = False
                    payload["notification_error"] = "delivery_failed"
        return payload
    except Exception:
        db.rollback()
        if key:
            idempotency_release(db, key, owner=owner)
        raise
    finally:
        if key and "payload" in locals() and isinstance(payload, dict):
            _settle(db, key, owner, payload)
