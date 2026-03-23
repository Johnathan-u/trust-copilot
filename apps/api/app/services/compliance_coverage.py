"""Compliance Coverage aggregation — drives the coverage dashboard.

Pure aggregation over existing tables: Answer, Question, Questionnaire,
QuestionMappingSignal, EvidenceGap, Document. No new models required.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Answer, Document, Question, Questionnaire
from app.models.evidence_gap import EvidenceGap
from app.models.question_mapping_signal import QuestionMappingSignal

HIGH_CONFIDENCE_THRESHOLD = 70
LOW_CONFIDENCE_THRESHOLD = 40


def get_compliance_coverage(db: Session, workspace_id: int) -> dict:
    base_qnr = (
        db.query(Questionnaire.id)
        .filter(Questionnaire.workspace_id == workspace_id, Questionnaire.deleted_at.is_(None))
        .subquery()
    )

    total_questions = (
        db.query(func.count(Question.id))
        .filter(Question.questionnaire_id.in_(db.query(base_qnr.c.id)))
        .scalar() or 0
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
            signal_map[qid] = (fw if isinstance(fw, list) else [], subj if isinstance(subj, list) else [])
        except Exception:
            signal_map[qid] = ([], [])

    # ---------- KPI computation ----------
    drafted = 0
    insufficient = 0
    high_conf = 0
    total_answered = 0

    fw_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "drafted": 0, "insufficient": 0})
    subj_insuff: Counter[str] = Counter()
    subj_conf: dict[str, list[int]] = defaultdict(list)
    subj_evidence: dict[str, list[int]] = defaultdict(list)
    daily_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"drafted": 0, "insufficient": 0, "total": 0, "low_conf": 0})
    drill_data: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"questions": 0, "answered": 0, "low_conf": 0, "insufficient": 0})

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
            day = created_at.strftime("%Y-%m-%d") if isinstance(created_at, datetime) else str(created_at)[:10]
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
            {"title": title, "improves_questions": int(cnt)}
            for title, cnt in gap_rows
            if title
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
            trends.append({
                "date": day,
                "coverage_pct": round(running_drafted / running_total * 100, 1) if running_total > 0 else 0,
                "insufficient_pct": round(running_insuff / running_total * 100, 1) if running_total > 0 else 0,
                "low_confidence_pct": round(running_low_conf / running_total * 100, 1) if running_total > 0 else 0,
            })

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

    return {
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


def _infer_evidence_suggestions(
    subj_insuff: Counter[str],
    subj_evidence: dict[str, list[int]],
) -> list[dict]:
    """When no EvidenceGap rows exist, infer suggestions from insufficient subjects."""
    _SUBJECT_TO_DOC: dict[str, str] = {
        "Risk Assessment": "Risk Assessment Policy",
        "Vendor Risk": "Vendor Risk Management Policy",
        "Vendor Management": "Vendor Risk Management Policy",
        "Business Continuity / Disaster Recovery": "Business Continuity & DR Plan",
        "Encryption": "Encryption & Key Management Policy",
        "Cryptography": "Encryption & Key Management Policy",
        "Breach Notification": "Incident Response & Breach Notification Plan",
        "Incident Response": "Incident Response Plan",
        "Access Control": "Access Control Policy",
        "Change Management": "Change Management Policy",
        "Data Retention / Disposal": "Data Retention & Disposal Policy",
        "Privacy / Data Governance": "Privacy Policy & Data Governance Framework",
        "Secure SDLC": "Secure Development Lifecycle Policy",
        "Physical Security": "Physical Security Policy",
    }
    suggestions = []
    for subj, count in subj_insuff.most_common(8):
        if subj == "Uncategorized":
            continue
        doc_title = _SUBJECT_TO_DOC.get(subj)
        if not doc_title:
            doc_title = f"{subj} Policy"
        suggestions.append({"title": f"Upload {doc_title}", "improves_questions": count})
    return suggestions
