"""Structured logging for indexing, retrieval, and answer-generation pipeline. Correlation: job_id, workspace_id, document_id, questionnaire_id."""

import logging
import time
from typing import Any

logger = logging.getLogger("trustcopilot.pipeline")


def _fields(
    event: str,
    *,
    job_id: int | None = None,
    workspace_id: int | None = None,
    document_id: int | None = None,
    questionnaire_id: int | None = None,
    duration_ms: float | None = None,
    error: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {"event": event}
    if job_id is not None:
        out["job_id"] = job_id
    if workspace_id is not None:
        out["workspace_id"] = workspace_id
    if document_id is not None:
        out["document_id"] = document_id
    if questionnaire_id is not None:
        out["questionnaire_id"] = questionnaire_id
    if duration_ms is not None:
        out["duration_ms"] = round(duration_ms, 2)
    if error is not None:
        out["error"] = error[:500]
    out.update(extra)
    return out


def log_job_start(kind: str, job_id: int, workspace_id: int, **extra: Any) -> None:
    logger.info("pipeline job_start %s", _fields("job_start", job_id=job_id, workspace_id=workspace_id, kind=kind, **extra))


def log_job_success(kind: str, job_id: int, workspace_id: int, duration_ms: float, **extra: Any) -> None:
    logger.info("pipeline job_success %s", _fields("job_success", job_id=job_id, workspace_id=workspace_id, duration_ms=duration_ms, kind=kind, **extra))


def log_job_failure(kind: str, job_id: int, workspace_id: int, error: str, duration_ms: float | None = None, **extra: Any) -> None:
    logger.warning("pipeline job_failure %s", _fields("job_failure", job_id=job_id, workspace_id=workspace_id, error=error, duration_ms=duration_ms, kind=kind, **extra))


def log_index_start(document_id: int, workspace_id: int, job_id: int | None = None) -> None:
    logger.info("pipeline index_start %s", _fields("index_start", document_id=document_id, workspace_id=workspace_id, job_id=job_id))


def log_index_success(document_id: int, workspace_id: int, chunk_count: int, duration_ms: float, job_id: int | None = None) -> None:
    logger.info("pipeline index_success %s", _fields("index_success", document_id=document_id, workspace_id=workspace_id, duration_ms=duration_ms, chunk_count=chunk_count, job_id=job_id))


def log_index_failure(document_id: int, workspace_id: int, error: str, duration_ms: float | None = None, job_id: int | None = None) -> None:
    logger.warning("pipeline index_failure %s", _fields("index_failure", document_id=document_id, workspace_id=workspace_id, error=error, duration_ms=duration_ms, job_id=job_id))


def log_retrieval_start(workspace_id: int, **extra: Any) -> None:
    logger.info("pipeline retrieval_start %s", _fields("retrieval_start", workspace_id=workspace_id, **extra))


def log_retrieval_success(workspace_id: int, result_count: int, duration_ms: float, **extra: Any) -> None:
    logger.info("pipeline retrieval_success %s", _fields("retrieval_success", workspace_id=workspace_id, duration_ms=duration_ms, result_count=result_count, **extra))


def log_retrieval_failure(workspace_id: int, error: str, duration_ms: float | None = None, **extra: Any) -> None:
    logger.warning("pipeline retrieval_failure %s", _fields("retrieval_failure", workspace_id=workspace_id, error=error, duration_ms=duration_ms, **extra))


def log_answer_gen_start(workspace_id: int, questionnaire_id: int, job_id: int | None = None, **extra: Any) -> None:
    logger.info("pipeline answer_gen_start %s", _fields("answer_gen_start", workspace_id=workspace_id, questionnaire_id=questionnaire_id, job_id=job_id, **extra))


def log_answer_gen_success(workspace_id: int, questionnaire_id: int, answer_count: int, duration_ms: float, job_id: int | None = None, **extra: Any) -> None:
    logger.info("pipeline answer_gen_success %s", _fields("answer_gen_success", workspace_id=workspace_id, questionnaire_id=questionnaire_id, duration_ms=duration_ms, answer_count=answer_count, job_id=job_id, **extra))


def log_answer_gen_failure(workspace_id: int, questionnaire_id: int, error: str, duration_ms: float | None = None, job_id: int | None = None, **extra: Any) -> None:
    logger.warning("pipeline answer_gen_failure %s", _fields("answer_gen_failure", workspace_id=workspace_id, questionnaire_id=questionnaire_id, error=error, duration_ms=duration_ms, job_id=job_id, **extra))
