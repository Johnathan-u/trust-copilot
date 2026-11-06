"""Job error classification without a database or a provider call.

The unknown-exception case is the known regression: an unexplained failure must
stay ``internal_error`` and must not become retryable.
"""

from __future__ import annotations

import random

import pytest

from app.core.job_errors import (
    BAD_INPUT,
    INTERNAL_ERROR,
    TIMEOUT,
    JobError,
    backoff_delay,
    classify,
    is_retryable_code,
    safe_error_message,
)

pytestmark = pytest.mark.unit


class TimeoutException(Exception):
    """Name matches the httpx/openai timeout entry in the classifier table."""


def test_timeout_class_name_is_retryable():
    code = classify(TimeoutException("slow"))
    assert code == TIMEOUT
    assert is_retryable_code(code) is True


def test_value_error_is_bad_input_and_not_retryable():
    code = classify(ValueError("bad field"))
    assert code == BAD_INPUT
    assert is_retryable_code(code) is False


def test_unknown_exception_is_terminal():
    """Known regression: unexplained failures must not be retried."""
    code = classify(RuntimeError("unexplained failure"))
    assert code == INTERNAL_ERROR, "unknown failures must stay terminal"
    assert is_retryable_code(code) is False


def test_upstream_message_drops_the_raw_body():
    class TimeoutException(Exception):
        pass

    TimeoutException.__module__ = "httpx"
    exc = TimeoutException("raw upstream body must stay internal")
    message = safe_error_message(exc, TIMEOUT)
    assert "raw upstream body" not in message
    assert "TimeoutException" in message


def test_unknown_job_code_is_rejected():
    with pytest.raises(ValueError, match="unknown job error code"):
        JobError("not-a-real-code")


def test_backoff_delay_stays_inside_the_cap():
    for attempt in range(1, 8):
        delay = backoff_delay(
            attempt,
            base=15,
            cap=30,
            retry_after=10_000,
            rng=random.Random(attempt),
        )
        assert 0 <= delay <= 30
