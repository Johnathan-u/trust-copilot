"""Export and generate-answers job enqueue logic. Keeps routes thin."""

import logging

from sqlalchemy.orm import Session

from app.models import Job, Questionnaire
from app.services.answer_generation import (
    is_allowed_model,
    is_allowed_response_style,
    resolve_model,
    resolve_response_style,
)
from app.services.job_effects import enqueue_job, job_idempotency_key

_logger = logging.getLogger(__name__)


def enqueue_export_job(
    db: Session,
    workspace_id: int,
    questionnaire_id: int,
    format: str = "xlsx",
) -> Job:
    """Create and enqueue an export job. Caller must have verified workspace access and questionnaire exists."""
    if format not in ("xlsx", "docx"):
        raise ValueError("format must be xlsx or docx")
    qnr = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id == questionnaire_id,
            Questionnaire.workspace_id == workspace_id,
        )
        .first()
    )
    if not qnr:
        raise ValueError("Questionnaire not found")
    # TC-10-003: an identical export that is still QUEUED is reused instead of duplicated.
    job, _created = enqueue_job(
        db,
        workspace_id=workspace_id,
        kind="export",
        payload={
            "questionnaire_id": questionnaire_id,
            "workspace_id": workspace_id,
            "format": format,
        },
        idempotency_key=job_idempotency_key("export", workspace_id, questionnaire_id, format),
    )
    _logger.info(
        "EXPORT: job created job_id=%s kind=export questionnaire_id=%s workspace_id=%s",
        job.id,
        questionnaire_id,
        workspace_id,
    )
    return job


def enqueue_generate_answers_job(
    db: Session,
    workspace_id: int,
    questionnaire_id: int,
    model_override: str | None = None,
    response_style_override: str | None = None,
) -> Job:
    """Create and enqueue a generate_answers job. Validates model/response_style if provided."""
    if model_override is not None and not is_allowed_model(model_override):
        raise ValueError("Unsupported model")
    if response_style_override is not None and not is_allowed_response_style(
        response_style_override
    ):
        raise ValueError("Unsupported response style")
    qnr = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id == questionnaire_id,
            Questionnaire.workspace_id == workspace_id,
        )
        .first()
    )
    if not qnr:
        raise ValueError("Questionnaire not found")
    payload = {"questionnaire_id": questionnaire_id, "workspace_id": workspace_id}
    if model_override is not None:
        payload["model"] = resolve_model(model_override)
    if response_style_override is not None:
        payload["response_style"] = resolve_response_style(response_style_override)
    # TC-10-003: an identical generation that is still QUEUED is reused instead of duplicated.
    job, _created = enqueue_job(
        db,
        workspace_id=workspace_id,
        kind="generate_answers",
        payload=payload,
        idempotency_key=job_idempotency_key(
            "generate_answers",
            workspace_id,
            questionnaire_id,
            payload.get("model"),
            payload.get("response_style"),
        ),
    )
    _logger.info(
        "GENERATE_ANSWERS: job persisted job_id=%s questionnaire_id=%s workspace_id=%s",
        job.id,
        questionnaire_id,
        workspace_id,
    )
    return job
