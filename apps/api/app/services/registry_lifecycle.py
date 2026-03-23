"""Shared delete-preview, delete, restore, and metadata update helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Answer,
    Document,
    ExportRecord,
    Question,
    Questionnaire,
    TrustRequest,
    TrustRequestNote,
)
from app.services.registry_metadata import (
    FRAMEWORK_LABELS,
    SUBJECT_AREA_LABELS,
    build_display_id,
    normalize_labels,
    to_json,
)

RegistryKind = Literal["document", "trust_request", "questionnaire"]


@dataclass
class PreviewResult:
    entity_id: int
    display_id: str
    can_delete: bool
    recommended_action: str
    warnings: list[str]
    dependencies: dict[str, int | str]  # int = count, "unavailable" = unmodeled
    unmodeled_warning: str | None = None


def _deps_for_document(db: Session, workspace_id: int, entity_id: int) -> tuple[dict[str, int | str], bool]:
    linked_questionnaires = int(
        db.query(func.count(Questionnaire.id))
        .filter(
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.document_id == entity_id,
            Questionnaire.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )
    generated_answers = int(
        db.query(func.count(Answer.id))
        .join(Question, Question.id == Answer.question_id)
        .join(Questionnaire, Questionnaire.id == Question.questionnaire_id)
        .filter(
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.document_id == entity_id,
            Questionnaire.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )
    deps: dict[str, int | str] = {
        "generated_answers": generated_answers,
        "questionnaires": linked_questionnaires,
    }
    unmodeled = ["linked_controls", "mappings", "trust_requests"]
    for k in unmodeled:
        deps[k] = "unavailable"
    return deps, True  # has unmodeled


def _deps_for_trust_request(db: Session, entity_id: int) -> tuple[dict[str, int | str], bool]:
    workflow = int(
        db.query(func.count(TrustRequestNote.id))
        .filter(TrustRequestNote.trust_request_id == entity_id)
        .scalar()
        or 0
    )
    deps: dict[str, int | str] = {
        "workflow_state": workflow,
    }
    for k in ["linked_questionnaires", "evidence", "exports_or_generated_responses"]:
        deps[k] = "unavailable"
    return deps, True


def _deps_for_questionnaire(db: Session, workspace_id: int, entity_id: int) -> tuple[dict[str, int | str], bool]:
    question_ids_subq = db.query(Question.id).filter(Question.questionnaire_id == entity_id)
    deps: dict[str, int | str] = {
        "generated_answers": int(
            db.query(func.count(Answer.id)).filter(Answer.question_id.in_(question_ids_subq)).scalar() or 0
        ),
        "mappings": int(db.query(func.count(Question.id)).filter(Question.questionnaire_id == entity_id).scalar() or 0),
        "exports": int(
            db.query(func.count(ExportRecord.id))
            .filter(
                ExportRecord.workspace_id == workspace_id,
                ExportRecord.questionnaire_id == entity_id,
            )
            .scalar()
            or 0
        ),
    }
    deps["linked_trust_requests"] = "unavailable"
    return deps, True


def build_delete_preview(kind: RegistryKind, db: Session, workspace_id: int, entity_id: int) -> PreviewResult:
    if kind == "document":
        deps, has_unmodeled = _deps_for_document(db, workspace_id, entity_id)
        display = build_display_id(kind, entity_id)
    elif kind == "trust_request":
        deps, has_unmodeled = _deps_for_trust_request(db, entity_id)
        display = build_display_id(kind, entity_id)
    else:
        deps, has_unmodeled = _deps_for_questionnaire(db, workspace_id, entity_id)
        display = build_display_id(kind, entity_id)

    warnings: list[str] = []
    for key, val in deps.items():
        if isinstance(val, int) and val > 0:
            warnings.append(f"{val} {key.replace('_', ' ')} linked")

    unmodeled_warning = (
        "Some dependency types are not yet modeled and could not be inspected."
        if has_unmodeled and any(v == "unavailable" for v in deps.values())
        else None
    )
    return PreviewResult(
        entity_id=entity_id,
        display_id=display,
        can_delete=True,
        recommended_action="archive",
        warnings=warnings,
        dependencies=deps,
        unmodeled_warning=unmodeled_warning,
    )


def update_metadata_json_fields(obj, frameworks: list[str], subject_areas: list[str]) -> None:
    obj.frameworks_json = to_json(normalize_labels(frameworks, allowed=FRAMEWORK_LABELS))
    obj.subject_areas_json = to_json(normalize_labels(subject_areas, allowed=SUBJECT_AREA_LABELS))


def soft_delete_record(obj, user_id: int | None) -> None:
    obj.deleted_at = datetime.now(timezone.utc)
    obj.deleted_by = user_id


def restore_record(obj) -> None:
    obj.deleted_at = None
    obj.deleted_by = None
