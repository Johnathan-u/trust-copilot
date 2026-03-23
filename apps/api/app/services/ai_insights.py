"""AI Insights aggregation — drives the AI Insights dashboard.

Pure aggregation over existing tables: Answer, Question, Questionnaire,
QuestionMappingSignal, EvidenceGap. No new models required.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Answer, Question, Questionnaire
from app.models.question_mapping_signal import QuestionMappingSignal


GATING_REASON_LABELS = {
    "no_evidence": "No evidence available",
    "retrieval_noise_floor": "Evidence too generic / noisy",
    "weak_control_path": "Weak control-path match",
    "weak_control_path_low_tier": "Weak control-path (low-tier docs)",
    "weak_retrieval_no_control": "Low retrieval score, no control path",
    "weak_retrieval_low_tier_docs": "Low retrieval score (low-tier docs only)",
}


def get_ai_insights(db: Session, workspace_id: int) -> dict:
    base_qnr = (
        db.query(Questionnaire.id)
        .filter(Questionnaire.workspace_id == workspace_id, Questionnaire.deleted_at.is_(None))
        .subquery()
    )

    answer_rows = (
        db.query(
            Answer.id,
            Answer.status,
            Answer.confidence,
            Answer.citations,
            Answer.gating_reason,
            Answer.insufficient_reason,
            Answer.primary_categories_json,
        )
        .join(Question, Question.id == Answer.question_id)
        .filter(Question.questionnaire_id.in_(db.query(base_qnr.c.id)))
        .all()
    )

    total_questions = (
        db.query(func.count(Question.id))
        .filter(Question.questionnaire_id.in_(db.query(base_qnr.c.id)))
        .scalar() or 0
    )

    # ── Performance overview ──
    total_answers = len(answer_rows)
    drafted = 0
    insufficient = 0
    conf_values: list[int] = []
    conf_buckets = {"high": 0, "medium": 0, "low": 0, "none": 0}

    gating_counter: Counter[str] = Counter()
    insuff_reason_counter: Counter[str] = Counter()

    subj_conf: dict[str, list[int]] = defaultdict(list)
    subj_insuff: Counter[str] = Counter()
    subj_total: Counter[str] = Counter()

    evidence_depth_buckets: dict[str, list[int]] = {
        "0 citations": [],
        "1-2 citations": [],
        "3-5 citations": [],
        "6+ citations": [],
    }

    for _aid, status, conf, citations_json, gating, insuff_reason, cats_json in answer_rows:
        is_draft = status in ("draft", "approved")
        is_insuff = status == "insufficient_evidence"

        if is_draft:
            drafted += 1
        if is_insuff:
            insufficient += 1
            if gating:
                gating_counter[gating] += 1
            elif insuff_reason:
                insuff_reason_counter[insuff_reason] += 1
            else:
                gating_counter["unknown"] += 1

        if conf is not None:
            conf_values.append(conf)
            if conf >= 70:
                conf_buckets["high"] += 1
            elif conf >= 40:
                conf_buckets["medium"] += 1
            else:
                conf_buckets["low"] += 1
        else:
            conf_buckets["none"] += 1

        cit_count = 0
        if citations_json:
            try:
                cits = json.loads(citations_json)
                if isinstance(cits, list):
                    cit_count = len(cits)
            except Exception:
                pass

        if cit_count == 0:
            bucket = "0 citations"
        elif cit_count <= 2:
            bucket = "1-2 citations"
        elif cit_count <= 5:
            bucket = "3-5 citations"
        else:
            bucket = "6+ citations"
        if conf is not None:
            evidence_depth_buckets[bucket].append(conf)

        subjects: list[str] = []
        if cats_json:
            try:
                cats = json.loads(cats_json)
                subjects = cats.get("subjects") or []
            except Exception:
                pass
        if not subjects:
            subjects = ["Uncategorized"]

        for subj in subjects:
            if subj == "Uncategorized":
                continue
            subj_total[subj] += 1
            if conf is not None:
                subj_conf[subj].append(conf)
            if is_insuff:
                subj_insuff[subj] += 1

    avg_confidence = round(sum(conf_values) / len(conf_values), 1) if conf_values else 0

    # ── Mapping quality ──
    signal_rows = (
        db.query(QuestionMappingSignal.mapping_quality)
        .filter(QuestionMappingSignal.workspace_id == workspace_id)
        .all()
    )
    mapping_quality: Counter[str] = Counter()
    for (mq,) in signal_rows:
        mapping_quality[mq or "unknown"] += 1
    total_signals = sum(mapping_quality.values())
    questions_with_signals = total_signals

    # ── Where AI struggles (top weak subjects) ──
    weak_subjects = sorted(
        [
            {
                "subject": subj,
                "avg_confidence": round(sum(scores) / len(scores), 1),
                "count": len(scores),
                "insufficient": subj_insuff.get(subj, 0),
            }
            for subj, scores in subj_conf.items()
            if len(scores) >= 2
        ],
        key=lambda x: x["avg_confidence"],
    )[:10]

    top_insufficient_subjects = [
        {"subject": subj, "insufficient_count": cnt, "total": subj_total.get(subj, cnt)}
        for subj, cnt in subj_insuff.most_common(10)
    ]

    # ── Why answers fail ──
    failure_reasons = []
    all_reasons = gating_counter + insuff_reason_counter
    for reason, count in all_reasons.most_common(10):
        failure_reasons.append({
            "reason": reason,
            "label": GATING_REASON_LABELS.get(reason, reason.replace("_", " ")),
            "count": count,
        })

    # ── Evidence depth vs confidence ──
    evidence_vs_confidence = []
    for bucket_name in ["0 citations", "1-2 citations", "3-5 citations", "6+ citations"]:
        confs = evidence_depth_buckets[bucket_name]
        evidence_vs_confidence.append({
            "bucket": bucket_name,
            "answer_count": len(confs),
            "avg_confidence": round(sum(confs) / len(confs), 1) if confs else 0,
        })

    return {
        "performance": {
            "total_questions": total_questions,
            "total_answers": total_answers,
            "drafted": drafted,
            "insufficient": insufficient,
            "avg_confidence": avg_confidence,
            "confidence_distribution": conf_buckets,
        },
        "weak_subjects": weak_subjects,
        "top_insufficient_subjects": top_insufficient_subjects,
        "mapping_quality": {
            "total_signals": total_signals,
            "questions_with_signals": questions_with_signals,
            "questions_without_signals": max(0, total_questions - questions_with_signals),
            "by_quality": dict(mapping_quality),
        },
        "evidence_vs_confidence": evidence_vs_confidence,
        "failure_reasons": failure_reasons,
    }
