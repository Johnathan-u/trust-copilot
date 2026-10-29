"""Compliance Coverage aggregation — drives the coverage dashboard.

Pure aggregation over existing tables: Answer, Question, Questionnaire,
QuestionMappingSignal, EvidenceGap, Document. No new models required.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta  # noqa: F401

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Answer, Document, Question, Questionnaire  # noqa: F401
from app.models.control_evidence_link import ControlEvidenceLink
from app.models.evidence_gap import EvidenceGap
from app.models.evidence_item import EvidenceItem
from app.models.evidence_metadata import EvidenceMetadata
from app.models.framework import Framework
from app.models.framework_control import FrameworkControl
from app.models.question_mapping_signal import QuestionMappingSignal
from app.models.workspace_control import WorkspaceControl
from app.services.evidence_gap_service import suggested_evidence_title

HIGH_CONFIDENCE_THRESHOLD = 70
LOW_CONFIDENCE_THRESHOLD = 40
CONTROL_COVERAGE_SCHEMA = "compliance-coverage-controls/v1"
_BLOCKED_RIGHTS = {"blocked_pending_rights", "blocked"}


def get_compliance_coverage(db: Session, workspace_id: int) -> dict:
    base_qnr = (
        db.query(Questionnaire.id)
        .filter(Questionnaire.workspace_id == workspace_id, Questionnaire.deleted_at.is_(None))
        .subquery()
    )

    total_questions = (
        db.query(func.count(Question.id))
        .filter(Question.questionnaire_id.in_(db.query(base_qnr.c.id)))
        .scalar()
        or 0
    )

    answer_rows = (
        db.query(
            Answer.id,
            Answer.question_id,
            Answer.status,
            Answer.confidence,
            Answer.primary_categories_json,
            Answer.citations,
            Answer.created_at,
        )
        .join(Question, Question.id == Answer.question_id)
        .filter(Question.questionnaire_id.in_(db.query(base_qnr.c.id)))
        .all()
    )

    signal_rows = (
        db.query(
            QuestionMappingSignal.question_id,
            QuestionMappingSignal.framework_labels_json,
            QuestionMappingSignal.subject_labels_json,
        )
        .filter(QuestionMappingSignal.workspace_id == workspace_id)
        .all()
    )
    signal_map: dict[int, tuple[list[str], list[str]]] = {}
    for qid, fw_json, subj_json in signal_rows:
        try:
            fw = json.loads(fw_json or "[]")
            subj = json.loads(subj_json or "[]")
            signal_map[qid] = (
                fw if isinstance(fw, list) else [],
                subj if isinstance(subj, list) else [],
            )
        except Exception:
            signal_map[qid] = ([], [])

    # ---------- KPI computation ----------
    drafted = 0
    insufficient = 0
    high_conf = 0
    total_answered = 0

    fw_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "drafted": 0, "insufficient": 0}
    )
    subj_insuff: Counter[str] = Counter()
    subj_conf: dict[str, list[int]] = defaultdict(list)
    subj_evidence: dict[str, list[int]] = defaultdict(list)
    daily_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"drafted": 0, "insufficient": 0, "total": 0, "low_conf": 0}
    )
    drill_data: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"questions": 0, "answered": 0, "low_conf": 0, "insufficient": 0}
    )

    for aid, qid, status, conf, cats_json, citations_json, created_at in answer_rows:
        total_answered += 1
        is_draft = status in ("draft", "approved")
        is_insuff = status == "insufficient_evidence"

        if is_draft:
            drafted += 1
        if is_insuff:
            insufficient += 1
        if conf is not None and conf >= HIGH_CONFIDENCE_THRESHOLD and is_draft:
            high_conf += 1

        cit_count = 0
        if citations_json:
            try:
                cits = json.loads(citations_json)
                if isinstance(cits, list):
                    cit_count = len(cits)
            except Exception:
                pass

        frameworks: list[str] = []
        subjects: list[str] = []

        if cats_json:
            try:
                cats = json.loads(cats_json)
                frameworks = cats.get("frameworks") or []
                subjects = cats.get("subjects") or []
            except Exception:
                pass

        if not frameworks or not subjects:
            sig = signal_map.get(qid)
            if sig:
                if not frameworks:
                    frameworks = sig[0]
                if not subjects:
                    subjects = sig[1]

        fw_list = [f for f in frameworks if f and f not in ("Other", "Unknown")]
        subj_list = [s for s in subjects if s]

        if not fw_list:
            fw_list = ["Uncategorized"]
        if not subj_list:
            subj_list = ["Uncategorized"]

        for fw in fw_list:
            fw_stats[fw]["total"] += 1
            if is_draft:
                fw_stats[fw]["drafted"] += 1
            if is_insuff:
                fw_stats[fw]["insufficient"] += 1

        for subj in subj_list:
            if is_insuff:
                subj_insuff[subj] += 1
            if conf is not None:
                subj_conf[subj].append(conf)
            subj_evidence[subj].append(cit_count)

            for fw in fw_list:
                key = (subj, fw)
                drill_data[key]["questions"] += 1
                if is_draft:
                    drill_data[key]["answered"] += 1
                if is_insuff:
                    drill_data[key]["insufficient"] += 1
                if conf is not None and conf < LOW_CONFIDENCE_THRESHOLD and is_draft:
                    drill_data[key]["low_conf"] += 1

        if created_at:
            day = (
                created_at.strftime("%Y-%m-%d")
                if isinstance(created_at, datetime)
                else str(created_at)[:10]
            )
            daily_stats[day]["total"] += 1
            if is_draft:
                daily_stats[day]["drafted"] += 1
            if is_insuff:
                daily_stats[day]["insufficient"] += 1
            if conf is not None and conf < LOW_CONFIDENCE_THRESHOLD and is_draft:
                daily_stats[day]["low_conf"] += 1

    coverage_pct = round(drafted / total_questions * 100, 1) if total_questions > 0 else 0
    high_conf_pct = round(high_conf / drafted * 100, 1) if drafted > 0 else 0
    insuff_pct = round(insufficient / total_questions * 100, 1) if total_questions > 0 else 0

    blind_spots = [s for s, c in subj_insuff.most_common(20) if s != "Uncategorized"]

    # ---------- Section data ----------
    framework_coverage = sorted(
        [
            {
                "framework": fw,
                "total": s["total"],
                "drafted": s["drafted"],
                "insufficient": s["insufficient"],
                "coverage_pct": round(s["drafted"] / s["total"] * 100, 1) if s["total"] > 0 else 0,
            }
            for fw, s in fw_stats.items()
            if fw != "Uncategorized"
        ],
        key=lambda x: x["total"],
        reverse=True,
    )[:12]

    blind_spot_items = [
        {"subject": s, "insufficient_count": c, "total": len(subj_evidence.get(s, []))}
        for s, c in subj_insuff.most_common(10)
        if s != "Uncategorized"
    ]

    weak_areas = sorted(
        [
            {
                "subject": subj,
                "avg_confidence": round(sum(scores) / len(scores), 1),
                "count": len(scores),
            }
            for subj, scores in subj_conf.items()
            if subj != "Uncategorized" and len(scores) >= 2 and sum(scores) / len(scores) < 60
        ],
        key=lambda x: x["avg_confidence"],
    )[:10]

    evidence_strength = sorted(
        [
            {
                "subject": subj,
                "avg_evidence_count": round(sum(counts) / len(counts), 1) if counts else 0,
                "total_answers": len(counts),
            }
            for subj, counts in subj_evidence.items()
            if subj != "Uncategorized" and len(counts) >= 2
        ],
        key=lambda x: x["avg_evidence_count"],
        reverse=True,
    )[:10]

    # ---------- Recommended evidence (from EvidenceGap) ----------
    gap_suggestions: list[dict] = []
    try:
        gap_rows = (
            db.query(
                EvidenceGap.suggested_evidence_doc_title,
                func.count(EvidenceGap.id).label("cnt"),
            )
            .filter(
                EvidenceGap.workspace_id == workspace_id,
                EvidenceGap.status == "open",
                EvidenceGap.suggested_evidence_doc_title.isnot(None),
            )
            .group_by(EvidenceGap.suggested_evidence_doc_title)
            .order_by(func.count(EvidenceGap.id).desc())
            .limit(8)
            .all()
        )
        gap_suggestions = [
            {"title": title, "improves_questions": int(cnt)} for title, cnt in gap_rows if title
        ]
    except Exception:
        pass

    if not gap_suggestions:
        gap_suggestions = _infer_evidence_suggestions(subj_insuff, subj_evidence)

    # ---------- Trends ----------
    trends: list[dict] = []
    if daily_stats:
        running_drafted = 0
        running_insuff = 0
        running_total = 0
        running_low_conf = 0
        for day in sorted(daily_stats.keys()):
            ds = daily_stats[day]
            running_drafted += ds["drafted"]
            running_insuff += ds["insufficient"]
            running_total += ds["total"]
            running_low_conf += ds["low_conf"]
            trends.append(
                {
                    "date": day,
                    "coverage_pct": round(running_drafted / running_total * 100, 1)
                    if running_total > 0
                    else 0,
                    "insufficient_pct": round(running_insuff / running_total * 100, 1)
                    if running_total > 0
                    else 0,
                    "low_confidence_pct": round(running_low_conf / running_total * 100, 1)
                    if running_total > 0
                    else 0,
                }
            )

    # ---------- Drill-down ----------
    drill_down = sorted(
        [
            {
                "subject": subj,
                "framework": fw,
                "questions_seen": d["questions"],
                "answered": d["answered"],
                "low_confidence": d["low_conf"],
                "insufficient": d["insufficient"],
            }
            for (subj, fw), d in drill_data.items()
            if subj != "Uncategorized"
        ],
        key=lambda x: x["insufficient"],
        reverse=True,
    )[:50]

    payload = {
        "kpi": {
            "total_questions": total_questions,
            "total_answered": total_answered,
            "total_drafted": drafted,
            "total_insufficient": insufficient,
            "coverage_pct": coverage_pct,
            "high_confidence_pct": high_conf_pct,
            "insufficient_pct": insuff_pct,
            "blind_spot_count": len(blind_spots),
        },
        "framework_coverage": framework_coverage,
        "blind_spots": blind_spot_items,
        "weak_areas": weak_areas,
        "evidence_strength": evidence_strength,
        "recommended_evidence": gap_suggestions,
        "trends": trends,
        "drill_down": drill_down,
    }
    payload["control_coverage"] = control_coverage(db, workspace_id)
    return payload


def _explanation(
    control_id: int,
    state: str,
    rule: str,
    effect: str,
    denominator_changed: bool,
    framework_id: int | None,
) -> dict:
    return {
        "control_id": control_id,
        "state": state,
        "rule": rule,
        "effect": effect,
        "denominator_changed": denominator_changed,
        "framework_id": framework_id,
    }


def _evidence_is_current(db: Session, ev: EvidenceItem, workspace_id: int, now: datetime) -> str:
    """Return qualifies, stale, deleted_document, not_approved, or missing.

    Missing covers a foreign workspace and a missing document. The caller does
    not keep that evidence id.
    """
    if ev.workspace_id != workspace_id:
        return "missing"
    if ev.approval_status != "approved":
        return "not_approved"
    if ev.document_id is not None:
        doc = db.query(Document).filter(Document.id == ev.document_id).first()
        if doc is None or doc.workspace_id != workspace_id:
            return "missing"
        if doc.deleted_at is not None:
            return "deleted_document"
    metas = db.query(EvidenceMetadata).filter(EvidenceMetadata.evidence_id == ev.id).all()
    for meta in metas:
        if meta.expires_at is not None and meta.expires_at <= now:
            return "stale"
    return "qualifies"


def _explain_control_inner(db: Session, wc: WorkspaceControl, workspace_id: int) -> dict:
    lifecycle = (wc.lifecycle or "").strip().lower()
    status = (getattr(wc, "status", None) or "").strip().lower()
    if lifecycle == "disabled" or status == "disabled":
        return _explanation(
            wc.id, "disabled", "lifecycle_disabled", "excluded_from_denominator", True, None
        )
    framework_id = None
    if wc.framework_control_id:
        fc = (
            db.query(FrameworkControl)
            .filter(FrameworkControl.id == wc.framework_control_id)
            .first()
        )
        if fc is None:
            return _explanation(
                wc.id, "unknown", "missing_framework", "excluded_from_denominator", True, None
            )
        fw = db.query(Framework).filter(Framework.id == fc.framework_id).first()
        if fw is None:
            return _explanation(
                wc.id, "unknown", "missing_framework", "excluded_from_denominator", True, None
            )
        framework_id = fw.id
        rights = (fw.rights_status or "").strip().lower()
        enablement = (fw.enablement_state or "").strip().lower()
        if rights in _BLOCKED_RIGHTS or enablement == "blocked":
            return _explanation(
                wc.id,
                "blocked",
                "framework_blocked",
                "excluded_from_denominator",
                True,
                framework_id,
            )
    now = datetime.utcnow()
    links = db.query(ControlEvidenceLink).filter(ControlEvidenceLink.control_id == wc.id).all()
    if not links:
        return _explanation(
            wc.id, "gap", "no_evidence", "excluded_from_numerator", False, framework_id
        )
    saw_expired = False
    saw_deleted = False
    saw_unapproved = False
    for link in links:
        ev = db.query(EvidenceItem).filter(EvidenceItem.id == link.evidence_id).first()
        if ev is None:
            continue
        kind = _evidence_is_current(db, ev, workspace_id, now)
        if kind == "qualifies":
            return _explanation(
                wc.id, "qualified", "evidence_qualifies", "counted", False, framework_id
            )
        if kind == "stale":
            saw_expired = True
        elif kind == "deleted_document":
            saw_deleted = True
        elif kind == "not_approved":
            saw_unapproved = True
    if saw_expired:
        return _explanation(
            wc.id, "stale", "expired", "excluded_from_numerator", False, framework_id
        )
    if saw_deleted:
        return _explanation(
            wc.id, "gap", "deleted_document", "excluded_from_numerator", False, framework_id
        )
    if saw_unapproved:
        return _explanation(
            wc.id, "gap", "not_approved", "excluded_from_numerator", False, framework_id
        )
    return _explanation(wc.id, "gap", "no_evidence", "excluded_from_numerator", False, framework_id)


def _explain_control(db: Session, wc: WorkspaceControl, workspace_id: int) -> dict:
    try:
        return _explain_control_inner(db, wc, workspace_id)
    except Exception:
        return _explanation(wc.id, "failed", "check_error", "excluded_from_numerator", False, None)


def control_coverage(db: Session, workspace_id: int) -> dict:
    """Distinct applicable controls in a qualified state, with every exclusion named.

    Disabled, unknown, and blocked controls leave the denominator. Stale, gap,
    and failed controls stay in it and stay out of the numerator. Nothing here
    is stored.
    """
    rows = db.query(WorkspaceControl).filter(WorkspaceControl.workspace_id == workspace_id).all()
    if not isinstance(rows, list):
        rows = []
    explanations = []
    qualified: list[int] = []
    denominator = 0
    for wc in rows:
        if not hasattr(wc, "id"):
            continue
        item = _explain_control(db, wc, workspace_id)
        explanations.append(item)
        if item["effect"] != "excluded_from_denominator":
            denominator += 1
        if item["effect"] == "counted":
            qualified.append(int(wc.id))
    explanations.sort(key=lambda item: item["control_id"])
    qualified_ids = sorted(set(qualified))
    numerator = len(qualified_ids)
    return {
        "schema_version": CONTROL_COVERAGE_SCHEMA,
        "numerator": numerator,
        "denominator": denominator,
        "coverage_pct": round(numerator / denominator * 100, 1) if denominator else 0,
        "qualified_control_ids": qualified_ids,
        "explanations": explanations,
    }


def _infer_evidence_suggestions(
    subj_insuff: Counter[str],
    subj_evidence: dict[str, list[int]],
) -> list[dict]:
    """When no EvidenceGap rows exist, infer suggestions from insufficient subjects."""
    suggestions = []
    for subj, count in subj_insuff.most_common(8):
        if subj == "Uncategorized":
            continue
        doc_title = suggested_evidence_title(subj)
        suggestions.append({"title": f"Upload {doc_title}", "improves_questions": count})
    return suggestions
