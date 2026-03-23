"""Phase 2: Gap detection - controls with no or low-confidence evidence."""

import time
from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.auth_deps import require_can_admin, require_can_review
from app.core.database import get_db
from app.models import (
    WorkspaceControl,
    FrameworkControl,
    Framework,
    ControlEvidenceLink,
)
from app.models.ai_mapping import QuestionMappingPreference
from app.models.questionnaire import Question, Questionnaire
from app.api.constants import LOW_CONFIDENCE_THRESHOLD
from app.services.in_app_notification_service import notify_admins

router = APIRouter(prefix="/compliance/gaps", tags=["compliance-gaps"])

_last_gap_notify: dict[int, float] = {}
GAP_NOTIFY_COOLDOWN = 3600

_QUESTION_TEXT_PREVIEW_LEN = 160


def _truncate_question_text(text: str | None, max_len: int = _QUESTION_TEXT_PREVIEW_LEN) -> str:
    t = (text or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _control_display_fields(db: Session, wc: WorkspaceControl) -> tuple[str | None, str | None, str | None]:
    framework_name = None
    control_key = None
    title = wc.custom_name or None
    if wc.framework_control_id:
        fc = db.query(FrameworkControl).filter(FrameworkControl.id == wc.framework_control_id).first()
        if fc:
            control_key = fc.control_key
            title = title or fc.title
            fw = db.query(Framework).filter(Framework.id == fc.framework_id).first()
            if fw:
                framework_name = fw.name
    return control_key, title, framework_name


def global_gaps_list(
    db: Session,
    workspace_id: int,
    low_confidence_threshold: float,
) -> list[dict]:
    """Workspace-wide control gaps (no / low-confidence evidence)."""
    rows = (
        db.query(WorkspaceControl)
        .filter(WorkspaceControl.workspace_id == workspace_id)
        .all()
    )

    out = []
    for wc in rows:
        link_stats = (
            db.query(
                func.count(ControlEvidenceLink.id),
                func.max(ControlEvidenceLink.confidence_score),
            )
            .filter(ControlEvidenceLink.control_id == wc.id)
        ).first()
        evidence_count = link_stats[0] or 0
        max_conf = link_stats[1]
        if max_conf is None:
            max_conf = 0.0

        if evidence_count == 0:
            gap_reason = "no_evidence"
        elif max_conf < low_confidence_threshold:
            gap_reason = "low_confidence"
        else:
            continue

        control_key, title, framework_name = _control_display_fields(db, wc)

        out.append({
            "control_id": wc.id,
            "control_key": control_key,
            "name": title,
            "framework": framework_name,
            "evidence_count": evidence_count,
            "max_confidence": round(max_conf, 4) if max_conf is not None else None,
            "gap_reason": gap_reason,
        })

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
    link_rows = (
        db.query(ControlEvidenceLink.control_id, func.count(ControlEvidenceLink.id))
        .filter(ControlEvidenceLink.control_id.in_(ctrl_ids))
        .group_by(ControlEvidenceLink.control_id)
        .all()
    )
    link_count_by_control = {int(r[0]): int(r[1] or 0) for r in link_rows}

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
        qnr_by_id = {q.id: q for q in db.query(Questionnaire).filter(Questionnaire.id.in_(qnr_ids)).all()}
    q_by_id: dict[int, Question] = {}
    if question_ids:
        q_by_id = {q.id: q for q in db.query(Question).filter(Question.id.in_(question_ids)).all()}

    by_control: dict[int, list[QuestionMappingPreference]] = defaultdict(list)
    for m in mappings:
        cid = int(m.preferred_control_id)
        if link_count_by_control.get(cid, 0) > 0:
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
            refs.append({
                "questionnaire_id": m.questionnaire_id,
                "questionnaire_title": qtitle,
                "question_id": m.question_id,
                "question_text_preview": _truncate_question_text(qtext),
            })

        out.append({
            "gap_kind": "questionnaire_mapping_no_evidence",
            "control_id": wc.id,
            "control_key": control_key,
            "name": title,
            "framework": framework_name,
            "evidence_link_count": 0,
            "questionnaire_refs": refs,
        })

    out.sort(key=lambda r: ((r.get("control_key") or ""), r.get("control_id") or 0))
    return out


@router.get("")
def list_gaps(
    low_confidence_threshold: float = Query(LOW_CONFIDENCE_THRESHOLD, ge=0, le=1),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """
    Returns workspace-wide control gaps plus questionnaire-driven no-evidence gaps.

    - ``gaps``: controls with no evidence or only low-confidence evidence (unchanged shape per row).
    - ``questionnaire_evidence_gaps``: approved/manual mapped controls with zero ControlEvidenceLink rows,
      grouped by control with questionnaire context for each distinct question.
    """
    ws = session.get("workspace_id")
    if ws is None:
        return {"gaps": [], "questionnaire_evidence_gaps": []}

    return {
        "gaps": global_gaps_list(db, ws, low_confidence_threshold),
        "questionnaire_evidence_gaps": questionnaire_evidence_gaps_list(db, ws),
    }


@router.post("/scan-and-notify", response_model=dict)
def scan_and_notify_gaps(
    low_confidence_threshold: float = Query(LOW_CONFIDENCE_THRESHOLD, ge=0, le=1),
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Run a gap scan and notify admins if gaps are found. Rate-limited to once per hour per workspace."""
    ws = session.get("workspace_id")
    if ws is None:
        return {"gaps": 0, "notified": False}

    now = time.monotonic()
    last = _last_gap_notify.get(ws, 0)
    if now - last < GAP_NOTIFY_COOLDOWN:
        gaps = global_gaps_list(db, ws, low_confidence_threshold)
        return {"gaps": len(gaps), "notified": False, "reason": "cooldown"}

    gaps = global_gaps_list(db, ws, low_confidence_threshold)
    if gaps:
        try:
            no_ev = sum(1 for g in gaps if g["gap_reason"] == "no_evidence")
            low_conf = sum(1 for g in gaps if g["gap_reason"] == "low_confidence")
            body = f"{no_ev} control(s) missing evidence, {low_conf} with low confidence."
            notify_admins(db, ws, f"{len(gaps)} compliance gap(s) detected", body, category="warning", link="/dashboard/compliance-gaps")
            _last_gap_notify[ws] = now
        except Exception:
            pass
        return {"gaps": len(gaps), "notified": True}

    return {"gaps": 0, "notified": False}
