"""Shared public error envelope (PRODUCT_SPEC ``ApiError`` contract, TC-11-001).

``ApiError`` = ``code`` (stable string), ``message`` (safe, operator-written), ``request_id``,
``retryable`` and optional safe ``field_errors``. Raw exception text and provider payloads are
never placed in ``message``.

HTTP responses keep the legacy FastAPI ``detail`` string for compatibility and add the typed
object under ``error``: ``{"detail": "<message>", "error": {...ApiError...}}``.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.logging_config import request_id_ctx
from app.services.model_outcomes import (
    ModelCallError,
    ModelFailure,
    ModelOutcomeCode,
    outcome_spec,
)

API_ERROR_SCHEMA_VERSION = 1
JOB_FAILED_CODE = "job_failed"
JOB_FAILED_MESSAGE = "The job failed. Try again, or contact support with the request ID."


class FieldError(BaseModel):
    field: str
    code: str
    message: str


class ApiError(BaseModel):
    code: str
    message: str
    request_id: str
    retryable: bool
    field_errors: list[FieldError] | None = None


def current_request_id(request: Request | None = None) -> str:
    """Request ID set by the logging middleware; generated if absent (e.g. worker context)."""
    rid = None
    if request is not None:
        rid = getattr(getattr(request, "state", None), "request_id", None)
    if not rid:
        rid = request_id_ctx.get()
    return str(rid) if rid else str(uuid.uuid4())


def api_error_from_failure(failure: ModelFailure, request_id: str) -> ApiError:
    return ApiError(
        code=failure.code.value,
        message=failure.message,
        request_id=request_id,
        retryable=failure.retryable,
    )


def outcome_payload(code: str | None, request_id: str) -> dict[str, Any] | None:
    """Serialize a persisted answer outcome code; None for legacy/human rows without a code."""
    if not code:
        return None
    spec = outcome_spec(code)
    if spec is None:
        return None
    return ApiError(
        code=spec.code.value,
        message=spec.message,
        request_id=request_id,
        retryable=spec.retryable,
    ).model_dump(exclude_none=True)


def api_error_body(error: ApiError) -> dict[str, Any]:
    return {"detail": error.message, "error": error.model_dump(exclude_none=True)}


def api_error_response(error: ApiError, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=api_error_body(error),
        headers={"X-Request-ID": error.request_id},
    )


def model_failure_response(failure: ModelFailure, request: Request | None = None) -> JSONResponse:
    error = api_error_from_failure(failure, current_request_id(request))
    return api_error_response(error, failure.spec.http_status)


async def model_call_error_handler(request: Request, exc: ModelCallError) -> JSONResponse:
    """FastAPI exception handler: typed model failures never surface provider text."""
    return model_failure_response(exc.failure, request)


def job_error_payload(job: Any, request_id: str) -> dict[str, Any] | None:
    """ApiError for a failed job. Uses the enqueuing request's ID when it was recorded."""
    if getattr(job, "status", None) != "failed":
        return None
    origin_rid = None
    try:
        payload = json.loads(job.payload) if getattr(job, "payload", None) else {}
        origin_rid = payload.get("request_id") if isinstance(payload, dict) else None
    except (TypeError, ValueError):
        origin_rid = None
    rid = str(origin_rid) if origin_rid else request_id
    code = getattr(job, "error_code", None)
    spec = outcome_spec(code) if code else None
    if spec is not None:
        error = ApiError(
            code=spec.code.value, message=spec.message, request_id=rid, retryable=spec.retryable
        )
    else:
        error = ApiError(
            code=JOB_FAILED_CODE, message=JOB_FAILED_MESSAGE, request_id=rid, retryable=False
        )
    return error.model_dump(exclude_none=True)


__all__ = [
    "API_ERROR_SCHEMA_VERSION",
    "ApiError",
    "FieldError",
    "JOB_FAILED_CODE",
    "JOB_FAILED_MESSAGE",
    "ModelOutcomeCode",
    "api_error_body",
    "api_error_from_failure",
    "api_error_response",
    "current_request_id",
    "job_error_payload",
    "model_call_error_handler",
    "model_failure_response",
    "outcome_payload",
]
