"""Workspace-scoped AI pipeline statistics for admin governance dashboard."""

from __future__ import annotations

import json

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Answer, Document, Question, Questionnaire
from app.models.ai_mapping import QuestionMappingPreference
from app.models.question_mapping_signal import QuestionMappingSignal
from app.models.tag import DocumentTag, Tag


def get_workspace_ai_pipeline_stats(db: Session, workspace_id: int) -> dict:
    """Aggregates for questionnaires, answers, mappings, evidence gaps (per workspace)."""
    qnr_total = (
        db.query(func.count(Questionnaire.id))
        .filter(
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )

    q_total = (
        db.query(func.count(Question.id))
        .join(Questionnaire, Questionnaire.id == Question.questionnaire_id)
        .filter(
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )

    ans_total = (
        db.query(func.count(Answer.id))
        .join(Question, Question.id == Answer.question_id)
        .join(Questionnaire, Questionnaire.id == Question.questionnaire_id)
        .filter(
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )

    status_rows = (
        db.query(QuestionMappingPreference.status, func.count(QuestionMappingPreference.id))
        .filter(QuestionMappingPreference.workspace_id == workspace_id)
        .group_by(QuestionMappingPreference.status)
        .all()
    )
    mappings_by_status = {str(s): int(c) for s, c in status_rows}

    unmapped_control = (
        db.query(func.count(QuestionMappingPreference.id))
        .filter(
            QuestionMappingPreference.workspace_id == workspace_id,
            QuestionMappingPreference.preferred_control_id.is_(None),
        )
        .scalar()
        or 0
    )

    suggested_not_approved = (
        db.query(func.count(QuestionMappingPreference.id))
        .filter(
            QuestionMappingPreference.workspace_id == workspace_id,
            QuestionMappingPreference.status == "suggested",
        )
        .scalar()
        or 0
    )

    doc_total = (
        db.query(func.count(Document.id))
        .filter(
            Document.workspace_id == workspace_id,
            Document.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )

    indexed_docs = (
        db.query(func.count(Document.id))
        .filter(
            Document.workspace_id == workspace_id,
            Document.deleted_at.is_(None),
            Document.status == "indexed",
        )
        .scalar()
        or 0
    )

    docs_with_subject_tag = (
        db.query(func.count(func.distinct(DocumentTag.document_id)))
        .join(Tag, Tag.id == DocumentTag.tag_id)
        .join(Document, Document.id == DocumentTag.document_id)
        .filter(
            Document.workspace_id == workspace_id,
            Document.deleted_at.is_(None),
            Tag.category == "topic",
        )
        .scalar()
        or 0
    )

    qnrs_missing_evidence_scope = 0
    for row in (
        db.query(Questionnaire.answer_evidence_document_ids_json)
        .filter(
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_(None),
        )
        .all()
    ):
        raw = row[0]
        if not raw:
            qnrs_missing_evidence_scope += 1
            continue
        try:
            ids = json.loads(raw)
            if not isinstance(ids, list) or len(ids) == 0:
                qnrs_missing_evidence_scope += 1
        except Exception:
            qnrs_missing_evidence_scope += 1

    # Answer outcome breakdown
    answer_status_rows = (
        db.query(Answer.status, func.count(Answer.id))
        .join(Question, Question.id == Answer.question_id)
        .join(Questionnaire, Questionnaire.id == Question.questionnaire_id)
        .filter(Questionnaire.workspace_id == workspace_id, Questionnaire.deleted_at.is_(None))
        .group_by(Answer.status)
        .all()
    )
    answers_by_status = {str(s): int(c) for s, c in answer_status_rows}

    # Classification signal coverage
    questions_with_signal = (
        db.query(func.count(func.distinct(QuestionMappingSignal.question_id)))
        .filter(
            QuestionMappingSignal.workspace_id == workspace_id,
            QuestionMappingSignal.mapping_quality == "llm_structured",
        )
        .scalar() or 0
    )

    return {
        "workspace_id": workspace_id,
        "questionnaires_total": int(qnr_total),
        "questions_total": int(q_total),
        "answers_total": int(ans_total),
        "answers_by_status": answers_by_status,
        "questions_with_classification": int(questions_with_signal),
        "mappings_by_status": mappings_by_status,
        "mappings_without_control": int(unmapped_control),
        "mappings_suggested_pending": int(suggested_not_approved),
        "documents_total": int(doc_total),
        "documents_indexed": int(indexed_docs),
        "documents_with_subject_tag": int(docs_with_subject_tag),
        "documents_missing_subject_tag": max(0, int(doc_total) - int(docs_with_subject_tag)),
        "questionnaires_without_explicit_answer_evidence": int(qnrs_missing_evidence_scope),
    }
