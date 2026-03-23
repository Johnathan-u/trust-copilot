"""Export and generate-answers job enqueue logic. Keeps routes thin."""

import json
import logging

from sqlalchemy.orm import Session

from app.models import Job, JobStatus, Questionnaire
from app.services.answer_generation import (
    is_allowed_model,
    is_allowed_response_style,
    resolve_model,
    resolve_response_style,
)

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
    job = Job(
        workspace_id=workspace_id,
        kind="export",
        status=JobStatus.QUEUED.value,
        payload=json.dumps({
            "questionnaire_id": questionnaire_id,
            "workspace_id": workspace_id,
            "format": format,
        }),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
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
    if response_style_override is not None and not is_allowed_response_style(response_style_override):
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
    job = Job(
        workspace_id=workspace_id,
        kind="generate_answers",
        status=JobStatus.QUEUED.value,
        payload=json.dumps(payload),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    _logger.info(
        "GENERATE_ANSWERS: job persisted job_id=%s questionnaire_id=%s workspace_id=%s",
        job.id,
        questionnaire_id,
        workspace_id,
    )
    return job
