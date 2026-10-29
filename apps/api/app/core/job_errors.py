"""TC-10-002: classify job errors and compute bounded retry backoff.

A job failure is classified into a stable, typed ``error_code``:

* **retryable** (transient): ``rate_limited`` (429), ``timeout`` (408/504, client timeouts),
  ``upstream_unavailable`` (other 5xx), ``connection_error`` (network/DNS/refused),
  ``database_unavailable`` (DB connection lost / operational error), ``lease_expired`` (the worker
  lost its job lease before finishing; the attempt is abandoned and retried under the same cap);
* **terminal** (retrying cannot help): ``bad_input``, ``not_found``, ``auth_failed``, ``permission_denied``,
  ``config_error``, ``internal_error``.

Model-provider failures (TC-11-001, ``app.services.model_outcomes``) keep TC-11-001's ``model_*`` code and its
catalog ``retryable`` flag and safe message, so ``jobs.error_code`` has one vocabulary per failure source:
``model_rate_limited`` / ``model_timeout`` / ``model_server_error`` / ``model_malformed_output`` are retried,
fatal and other model codes are terminal.

Unknown exceptions are ``internal_error`` and **terminal**: a blind retry of an unexplained failure could repeat
side effects or burn provider quota (conservative default; see docs/release/tickets/TC-10-002.md).

Classification is duck-typed (status codes, exception class names, lazy optional imports) so this module has
no hard dependency on openai / httpx / botocore and never touches the network.
"""

from __future__ import annotations

import os
import random
import socket
import zipfile
from typing import Any

# ---------------------------------------------------------------------------------------------------------
# Codes
# ---------------------------------------------------------------------------------------------------------

RATE_LIMITED = "rate_limited"
TIMEOUT = "timeout"
UPSTREAM_UNAVAILABLE = "upstream_unavailable"
CONNECTION_ERROR = "connection_error"
DATABASE_UNAVAILABLE = "database_unavailable"
# A worker's lease expired before it finished. Retryable: the attempt is abandoned and the
# side-effect ledger (TC-10-003) makes the next attempt safe. Not an upstream/provider failure.
LEASE_EXPIRED = "lease_expired"

BAD_INPUT = "bad_input"
NOT_FOUND = "not_found"
AUTH_FAILED = "auth_failed"
PERMISSION_DENIED = "permission_denied"
CONFIG_ERROR = "config_error"
INTERNAL_ERROR = "internal_error"

RETRYABLE_CODES = frozenset(
    {
        RATE_LIMITED,
        TIMEOUT,
        UPSTREAM_UNAVAILABLE,
        CONNECTION_ERROR,
        DATABASE_UNAVAILABLE,
        LEASE_EXPIRED,
    }
)
TERMINAL_CODES = frozenset(
    {
        BAD_INPUT,
        NOT_FOUND,
        AUTH_FAILED,
        PERMISSION_DENIED,
        CONFIG_ERROR,
        INTERNAL_ERROR,
    }
)
ALL_CODES = RETRYABLE_CODES | TERMINAL_CODES

# Codes whose provider/storage message may echo a raw upstream body: never expose ``str(exc)`` for these.
# ``lease_expired`` is our own message, not an upstream body.
_UPSTREAM_CODES = (RETRYABLE_CODES - {LEASE_EXPIRED}) | {AUTH_FAILED, PERMISSION_DENIED}


def _model_spec(code: str | None):
    """TC-11-001 catalog entry for a ``model_*`` failure code, else None."""
    if not code:
        return None
    from app.services.model_outcomes import outcome_spec

    spec = outcome_spec(code)
    return spec if spec is not None and spec.is_failure else None


def is_known_code(code: str | None) -> bool:
    return code in ALL_CODES or _model_spec(code) is not None


def is_retryable_code(code: str | None) -> bool:
    if code in RETRYABLE_CODES:
        return True
    spec = _model_spec(code)
    return bool(spec is not None and spec.retryable)


def is_fatal_code(code: str | None) -> bool:
    """Credentials / configuration class: an operator has to act before anything can succeed."""
    if code in (AUTH_FAILED, PERMISSION_DENIED, CONFIG_ERROR):
        return True
    spec = _model_spec(code)
    return bool(spec is not None and spec.fatal)


def _model_failure(exc: BaseException):
    from app.services.model_outcomes import failure_from_exception

    return failure_from_exception(exc)


# ---------------------------------------------------------------------------------------------------------
# Typed exceptions raised by job handlers
# ---------------------------------------------------------------------------------------------------------


class JobError(Exception):
    """A job failure with an explicit classification."""

    retryable = False

    def __init__(self, code: str, message: str = "", *, retry_after: float | None = None) -> None:
        if not is_known_code(code):
            raise ValueError(f"unknown job error code: {code!r}")
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.retry_after = retry_after


class RetryableJobError(JobError):
    retryable = True

    def __init__(self, code: str, message: str = "", *, retry_after: float | None = None):
        if not is_retryable_code(code):
            raise ValueError(f"not a retryable code: {code!r}")
        super().__init__(code, message, retry_after=retry_after)


class TerminalJobError(JobError):
    retryable = False

    def __init__(self, code: str, message: str = "", *, retry_after: float | None = None):
        if not is_known_code(code) or is_retryable_code(code):
            raise ValueError(f"not a terminal code: {code!r}")
        super().__init__(code, message, retry_after=None)


class JobConfigError(TerminalJobError, ValueError):
    """Missing/invalid server configuration (e.g. no OPENAI_API_KEY). Still a ``ValueError`` for callers that
    caught the previous ``ValueError``."""

    def __init__(self, message: str):
        super().__init__(CONFIG_ERROR, message)


def job_error_from(exc: BaseException, message: str | None = None) -> JobError:
    """Wrap ``exc`` in a typed ``JobError`` carrying its classification (use ``raise ... from exc``)."""
    code = classify(exc)
    msg = message or safe_error_message(exc, code)
    if is_retryable_code(code):
        return RetryableJobError(code, msg, retry_after=retry_after_seconds(exc))
    return TerminalJobError(code, msg)


# ---------------------------------------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------------------------------------


def _status_code(exc: BaseException) -> int | None:
    for obj in (exc, getattr(exc, "response", None)):
        if obj is None:
            continue
        for attr in ("status_code", "status"):
            val = getattr(obj, attr, None)
            if isinstance(val, int) and 100 <= val <= 599:
                return val
    # botocore ClientError: exc.response = {"ResponseMetadata": {"HTTPStatusCode": 503}, "Error": {...}}
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        val = (resp.get("ResponseMetadata") or {}).get("HTTPStatusCode")
        if isinstance(val, int):
            return val
    return None


def _code_for_status(status: int) -> str | None:
    if status == 429:
        return RATE_LIMITED
    if status in (408, 504):
        return TIMEOUT
    if status >= 500:
        return UPSTREAM_UNAVAILABLE
    if status == 401:
        return AUTH_FAILED
    if status == 403:
        return PERMISSION_DENIED
    if status == 404:
        return NOT_FOUND
    if 400 <= status < 500:
        return BAD_INPUT
    return None


_BOTO_ERROR_CODES = {
    "SlowDown": RATE_LIMITED,
    "Throttling": RATE_LIMITED,
    "ThrottlingException": RATE_LIMITED,
    "RequestLimitExceeded": RATE_LIMITED,
    "RequestTimeout": TIMEOUT,
    "RequestTimeoutException": TIMEOUT,
    "ServiceUnavailable": UPSTREAM_UNAVAILABLE,
    "InternalError": UPSTREAM_UNAVAILABLE,
    "NoSuchKey": NOT_FOUND,
    "NoSuchBucket": CONFIG_ERROR,
    "AccessDenied": PERMISSION_DENIED,
    "InvalidAccessKeyId": AUTH_FAILED,
    "SignatureDoesNotMatch": AUTH_FAILED,
    "ExpiredToken": AUTH_FAILED,
}

# Exception class names (matched along the MRO) -> code. Covers openai, httpx, botocore/urllib3, sqlalchemy
# without importing them. Order matters: the first match on the most-derived class wins.
_NAME_CODES = {
    # openai
    "RateLimitError": RATE_LIMITED,
    "APITimeoutError": TIMEOUT,
    "APIConnectionError": CONNECTION_ERROR,
    "AuthenticationError": AUTH_FAILED,
    "PermissionDeniedError": PERMISSION_DENIED,
    "BadRequestError": BAD_INPUT,
    "UnprocessableEntityError": BAD_INPUT,
    "NotFoundError": NOT_FOUND,
    "InternalServerError": UPSTREAM_UNAVAILABLE,
    # httpx
    "TimeoutException": TIMEOUT,
    "ConnectError": CONNECTION_ERROR,
    "NetworkError": CONNECTION_ERROR,
    "RemoteProtocolError": CONNECTION_ERROR,
    # botocore / urllib3
    "ConnectTimeoutError": TIMEOUT,
    "ReadTimeoutError": TIMEOUT,
    "EndpointConnectionError": CONNECTION_ERROR,
    "ConnectionClosedError": CONNECTION_ERROR,
    "NoCredentialsError": CONFIG_ERROR,
    "PartialCredentialsError": CONFIG_ERROR,
    # sqlalchemy / DBAPI
    "OperationalError": DATABASE_UNAVAILABLE,
    "DisconnectionError": DATABASE_UNAVAILABLE,
    "InterfaceError": DATABASE_UNAVAILABLE,
}


def classify(exc: BaseException) -> str:
    """Return the ``error_code`` for an exception (never raises)."""
    try:
        return _classify(exc)
    except Exception:  # pragma: no cover - classification must never mask the real failure
        return INTERNAL_ERROR


def _classify(exc: BaseException) -> str:
    if isinstance(exc, JobError):
        return exc.code
    model_failure = _model_failure(exc)
    if model_failure is not None:  # TC-11-001 typed model failure or openai client exception
        return model_failure.code.value
    names = [c.__name__ for c in type(exc).__mro__]
    # botocore ClientError: prefer the service error code, then the HTTP status.
    if "ClientError" in names and isinstance(getattr(exc, "response", None), dict):
        err_code = (exc.response.get("Error") or {}).get("Code")
        if err_code in _BOTO_ERROR_CODES:
            return _BOTO_ERROR_CODES[err_code]
        status = _status_code(exc)
        if status is not None:
            return _code_for_status(status) or INTERNAL_ERROR
        return INTERNAL_ERROR
    for name in names:
        if name in _NAME_CODES:
            return _NAME_CODES[name]
    status = _status_code(exc)
    if status is not None:
        mapped = _code_for_status(status)
        if mapped:
            return mapped
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return TIMEOUT
    if isinstance(exc, ConnectionError):
        return CONNECTION_ERROR
    if isinstance(exc, (zipfile.BadZipFile, UnicodeDecodeError)):
        return BAD_INPUT
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return BAD_INPUT
    return INTERNAL_ERROR


def retry_after_seconds(exc: BaseException) -> float | None:
    """Retry-After (seconds) from an exception's HTTP response headers, if present and numeric."""
    if isinstance(exc, JobError):
        return exc.retry_after
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None) if resp is not None else None
    if headers is None:
        return None
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
    except Exception:
        return None
    if raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    return val if val >= 0 else None


_UPSTREAM_MODULES = ("openai", "httpx", "botocore", "boto3", "urllib3", "requests", "s3transfer")


def _is_upstream_exception(exc: BaseException) -> bool:
    """Raised by a provider / storage / HTTP client library (its message may embed the remote body)."""
    return any((c.__module__ or "").split(".")[0] in _UPSTREAM_MODULES for c in type(exc).__mro__)


def safe_error_message(exc: BaseException, code: str | None = None) -> str:
    """User-visible message. Provider/storage failures expose class name and status only, never the raw body."""
    code = code or classify(exc)
    if isinstance(exc, JobError):
        return exc.message[:1000]
    model_failure = _model_failure(exc)
    if model_failure is not None:  # TC-11-001 catalog message; never the provider body
        return model_failure.message
    if code in _UPSTREAM_CODES or _is_upstream_exception(exc):
        status = _status_code(exc)
        suffix = f" (HTTP {status})" if status is not None else ""
        return f"{type(exc).__name__}{suffix}"
    return (str(exc) or type(exc).__name__)[:1000]


# ---------------------------------------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------------------------------------

# Hard ceiling on total attempts regardless of a job's max_attempts (bounded retries).
MAX_ATTEMPTS_CEILING = 10
DEFAULT_RETRY_BASE_SECONDS = 15.0
DEFAULT_RETRY_MAX_SECONDS = 600.0


def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        val = float(os.environ.get(name, "") or default)
    except ValueError:
        val = default
    return min(max(val, lo), hi)


def retry_base_seconds() -> float:
    return _env_float("JOB_RETRY_BASE_SECONDS", DEFAULT_RETRY_BASE_SECONDS, 0.0, 3600.0)


def retry_max_seconds() -> float:
    return _env_float("JOB_RETRY_MAX_SECONDS", DEFAULT_RETRY_MAX_SECONDS, 0.0, 86400.0)


def effective_max_attempts(max_attempts: int | None) -> int:
    """Attempts allowed for a job: its ``max_attempts`` (default 3), clamped to [1, MAX_ATTEMPTS_CEILING]."""
    n = 3 if max_attempts is None else int(max_attempts)
    return min(max(n, 1), MAX_ATTEMPTS_CEILING)


def backoff_delay(
    attempt: int,
    *,
    base: float,
    cap: float,
    retry_after: float | None = None,
    rng: random.Random | Any | None = None,
) -> float:
    """Delay before the next attempt after ``attempt`` (1-based) failed.

    Exponential ``base * 2**(attempt-1)`` capped at ``cap``, with "equal jitter" (uniform in [d/2, d]) so
    concurrent failures do not retry in lockstep. A provider ``Retry-After`` raises the floor but is itself
    clamped to ``cap``: the delay is always within [0, cap].
    """
    rng = rng or random
    attempt = max(int(attempt), 1)
    cap = max(float(cap), 0.0)
    d = min(cap, max(float(base), 0.0) * (2 ** min(attempt - 1, 32)))
    delay = rng.uniform(d / 2.0, d) if d > 0 else 0.0
    if retry_after is not None and retry_after > 0:
        delay = max(delay, min(float(retry_after), cap))
    return min(delay, cap)
