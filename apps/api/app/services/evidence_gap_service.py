"""Evidence gap service — generation and CRUD for EvidenceGap records.

Used by the compliance-coverage dashboard to populate "Recommended Next Evidence"
and allow users to accept/dismiss individual gap suggestions.

``generate_gaps_for_questionnaire`` runs after answer generation (TC-02-BUG-015). It is
deterministic and makes no model calls: every answer that ended as insufficient evidence
for an evidence reason becomes one open ``missing_evidence`` gap. Model failures are not
evidence gaps and are skipped; they are retried as answer-generation failures instead.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models import Answer, Question, Questionnaire
from app.models.evidence_gap import EvidenceGap, GAP_STATUSES
from app.models.question_mapping_signal import QuestionMappingSignal

# Subject label -> document a reviewer should upload. Shared with compliance_coverage so
# generated gaps and the inferred fallback suggest the same titles.
SUBJECT_TO_EVIDENCE_DOC: dict[str, str] = {
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

# Answer outcome codes (TC-11-001) that mean "the evidence does not support an answer".
# NULL covers rows written before outcome codes existed. Every model_* failure is excluded.
GAP_OUTCOME_CODES = ("no_evidence", "model_abstained")
INSUFFICIENT_STATUS = "insufficient_evidence"
GAP_TYPE_MISSING_EVIDENCE = "missing_evidence"
# TC-10-002 retry placeholders. They are not evidence gaps; the next attempt rewrites them.
LLM_ERROR_REASON = "llm_error"
_DEFAULT_REASON = "No workspace evidence supports an answer to this question."
# pg_advisory_xact_lock namespace for TC-02-BUG-015. Distinct from any other advisory lock in the app.
_GAP_LOCK_NAMESPACE = 150015


def suggested_evidence_title(subject: str) -> str:
    """Document title to request for a subject label."""
    return SUBJECT_TO_EVIDENCE_DOC.get(subject) or f"{subject} Policy"


def _subjects(raw: str | None, *, nested: bool) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if nested:
        data = data.get("subjects", []) if isinstance(data, dict) else []
    if not isinstance(data, list):
        return []
    return [s for s in data if isinstance(s, str) and s and s != "Uncategorized"]


def _gap_reason(answer: Answer) -> str:
    code = answer.insufficient_reason or answer.gating_reason
    if code:
        # Stable machine codes only (e.g. no_citations); never answer or model text.
        return f"{_DEFAULT_REASON} Reason code: {code[:64]}."
    return _DEFAULT_REASON


def _lock_questionnaire_gap_writes(db: Session, questionnaire_id: int) -> None:
    """Serialize gap inserts for one questionnaire until this session commits or rolls back.

    ``pg_advisory_xact_lock`` is held by the current transaction, so the existing-gap read and
    the inserts below must stay on ``db`` with no commit between the lock and ``db.commit()``.
    Non-Postgres binds (SQLite unit tests, if any) skip the lock; production is Postgres.
    """
    bind = db.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", None)
    if dialect != "postgresql":
        return
    # Literal 150015 is the BUG-015 namespace (_GAP_LOCK_NAMESPACE). The lock and the later
    # db.commit() are the same session transaction; do not commit between them.
    db.execute(
        text(f"SELECT pg_advisory_xact_lock({_GAP_LOCK_NAMESPACE}, :questionnaire_id)"),
        {"questionnaire_id": int(questionnaire_id)},
    )


def generate_gaps_for_questionnaire(db: Session, workspace_id: int, questionnaire_id: int) -> dict:
    """Create one open evidence gap per insufficient-evidence answer in a questionnaire.

    Idempotent: a question that already has a gap (any status) is left alone, so reruns do
    not duplicate and accepted/dismissed gaps are not reopened. Concurrent callers take a
    transaction advisory lock before reading existing gaps, so two overlapping runs still
    insert once. Scoped to the workspace that owns the questionnaire. Returns
    ``{"generated": n, "total_insufficient": m}``.
    """
    rows = (
        db.query(Answer, Question)
        .join(Question, Question.id == Answer.question_id)
        .join(Questionnaire, Questionnaire.id == Question.questionnaire_id)
        .filter(
            Question.questionnaire_id == questionnaire_id,
            Questionnaire.workspace_id == workspace_id,
            Answer.status == INSUFFICIENT_STATUS,
        )
        .order_by(Question.id)
        .all()
    )
    eligible = [
        (a, q)
        for a, q in rows
        if (a.outcome_code is None or a.outcome_code in GAP_OUTCOME_CODES)
        and a.insufficient_reason != LLM_ERROR_REASON
    ]
    if not eligible:
        return {"generated": 0, "total_insufficient": 0}

    # Same session and transaction as the commit at the end of this function. Releasing the
    # lock any earlier would let a second run read "no gaps" and insert duplicates.
    _lock_questionnaire_gap_writes(db, questionnaire_id)
    question_ids = [q.id for _a, q in eligible]
    existing = {
        qid
        for (qid,) in db.query(EvidenceGap.question_id)
        .filter(
            EvidenceGap.workspace_id == workspace_id,
            EvidenceGap.questionnaire_id == questionnaire_id,
            EvidenceGap.question_id.in_(question_ids),
        )
        .all()
    }
    signal_subjects = {
        qid: _subjects(raw, nested=False)
        for qid, raw in db.query(
            QuestionMappingSignal.question_id, QuestionMappingSignal.subject_labels_json
        )
        .filter(
            QuestionMappingSignal.workspace_id == workspace_id,
            QuestionMappingSignal.question_id.in_(question_ids),
        )
        .all()
    }

    generated = 0
    for answer, question in eligible:
        if question.id in existing:
            continue
        subjects = _subjects(answer.primary_categories_json, nested=True) or signal_subjects.get(
            question.id, []
        )
        db.add(
            EvidenceGap(
                workspace_id=workspace_id,
                questionnaire_id=questionnaire_id,
                question_id=question.id,
                answer_id=answer.id,
                gap_type=GAP_TYPE_MISSING_EVIDENCE,
                reason=_gap_reason(answer),
                proposed_policy_addition=None,
                suggested_evidence_doc_title=(
                    suggested_evidence_title(subjects[0]) if subjects else None
                ),
                confidence=None,
                status="open",
            )
        )
        existing.add(question.id)
        generated += 1
    db.commit()
    return {"generated": generated, "total_insufficient": len(eligible)}


def list_evidence_gaps(
    db: Session,
    workspace_id: int,
    *,
    status: str | None = None,
    questionnaire_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Return evidence gap rows for a workspace, optionally filtered."""
    q = db.query(EvidenceGap).filter(EvidenceGap.workspace_id == workspace_id)
    if status:
        q = q.filter(EvidenceGap.status == status)
    if questionnaire_id:
        q = q.filter(EvidenceGap.questionnaire_id == questionnaire_id)
    q = q.order_by(EvidenceGap.created_at.desc()).offset(offset).limit(limit)
    return [_gap_to_dict(g) for g in q.all()]


def get_evidence_gap(db: Session, gap_id: int, workspace_id: int) -> dict | None:
    """Fetch a single evidence gap by ID (scoped to workspace)."""
    gap = (
        db.query(EvidenceGap)
        .filter(EvidenceGap.id == gap_id, EvidenceGap.workspace_id == workspace_id)
        .first()
    )
    return _gap_to_dict(gap) if gap else None


def update_evidence_gap_status(
    db: Session,
    gap_id: int,
    workspace_id: int,
    new_status: Literal["open", "accepted", "dismissed"],
) -> dict | None:
    """Update the status of a single evidence gap. Returns updated dict or None if not found."""
    if new_status not in GAP_STATUSES:
        raise ValueError(f"Invalid status: {new_status}. Must be one of {GAP_STATUSES}")
    gap = (
        db.query(EvidenceGap)
        .filter(EvidenceGap.id == gap_id, EvidenceGap.workspace_id == workspace_id)
        .first()
    )
    if not gap:
        return None
    gap.status = new_status
    gap.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(gap)
    return _gap_to_dict(gap)


def bulk_update_by_title(
    db: Session,
    workspace_id: int,
    suggested_title: str,
    new_status: Literal["open", "accepted", "dismissed"],
) -> int:
    """Update all open gaps matching a suggested_evidence_doc_title. Returns count updated."""
    if new_status not in GAP_STATUSES:
        raise ValueError(f"Invalid status: {new_status}")
    count = (
        db.query(EvidenceGap)
        .filter(
            EvidenceGap.workspace_id == workspace_id,
            EvidenceGap.suggested_evidence_doc_title == suggested_title,
            EvidenceGap.status == "open",
        )
        .update(
            {"status": new_status, "updated_at": datetime.now(timezone.utc)},
            synchronize_session="fetch",
        )
    )
    db.commit()
    return count


def gap_summary(db: Session, workspace_id: int) -> dict:
    """Aggregate counts by status."""
    rows = (
        db.query(EvidenceGap.status, func.count(EvidenceGap.id))
        .filter(EvidenceGap.workspace_id == workspace_id)
        .group_by(EvidenceGap.status)
        .all()
    )
    counts = {s: 0 for s in GAP_STATUSES}
    for status, cnt in rows:
        counts[status] = cnt
    counts["total"] = sum(counts.values())
    return counts


def _gap_to_dict(gap: EvidenceGap) -> dict:
    return {
        "id": gap.id,
        "workspace_id": gap.workspace_id,
        "questionnaire_id": gap.questionnaire_id,
        "question_id": gap.question_id,
        "answer_id": gap.answer_id,
        "gap_type": gap.gap_type,
        "reason": gap.reason,
        "proposed_policy_addition": gap.proposed_policy_addition,
        "suggested_evidence_doc_title": gap.suggested_evidence_doc_title,
        "confidence": gap.confidence,
        "status": gap.status,
        "created_at": gap.created_at.isoformat() if gap.created_at else None,
        "updated_at": gap.updated_at.isoformat() if gap.updated_at else None,
    }
