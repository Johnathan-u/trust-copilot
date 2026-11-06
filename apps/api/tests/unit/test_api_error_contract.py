"""API error envelope without a database or a provider call."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.core.api_errors import (
    JOB_FAILED_CODE,
    JOB_FAILED_MESSAGE,
    ApiError,
    api_error_body,
    job_error_payload,
)
from app.services.model_outcomes import outcome_spec

pytestmark = pytest.mark.unit


def test_error_body_keeps_the_stable_envelope():
    error = ApiError(
        code="job_failed",
        message="The job failed.",
        request_id="req-quality-1",
        retryable=False,
    )
    body = api_error_body(error)
    assert body["detail"] == "The job failed."
    assert body["error"]["code"] == "job_failed"
    assert body["error"]["request_id"] == "req-quality-1"
    assert body["error"]["retryable"] is False
    assert "field_errors" not in body["error"]


def test_failed_job_payload_is_terminal_and_hides_raw_text():
    raw = "upstream body must not be copied into the client message"
    job = SimpleNamespace(
        status="failed",
        payload=json.dumps({"request_id": "req-quality-2"}),
        error_code=None,
        error=raw,
    )
    body = job_error_payload(job, "fallback-rid")
    assert body is not None
    assert body["code"] == JOB_FAILED_CODE
    assert body["message"] == JOB_FAILED_MESSAGE
    assert body["request_id"] == "req-quality-2"
    assert body["retryable"] is False
    assert raw not in body["message"]


def test_job_payload_is_absent_until_the_job_fails():
    job = SimpleNamespace(status="succeeded", payload="{}", error_code=None, error=None)
    assert job_error_payload(job, "req-quality-3") is None


def test_model_timeout_is_retryable_and_missing_credentials_are_fatal():
    timeout = outcome_spec("model_timeout")
    missing = outcome_spec("model_credentials_missing")
    assert timeout is not None and timeout.retryable is True and timeout.fatal is False
    assert missing is not None and missing.fatal is True and missing.retryable is False
    assert outcome_spec("not-a-real-outcome") is None
