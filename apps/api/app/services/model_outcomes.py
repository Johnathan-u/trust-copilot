"""Typed model responses and failures (TC-11-001).

One stable vocabulary for what happened when the answer pipeline asked (or chose not to ask)
the model provider for a draft answer. The same codes are persisted on answers
(``answers.outcome_code``) and failed jobs (``jobs.error_code``) and are rendered to API/UI
clients through :class:`app.core.api_errors.ApiError`.

Rules:

- Every code has a fixed, safe, operator-written message. Provider exception text, response
  bodies, headers, prompts and evidence are never part of the message.
- ``fatal`` failures (credentials missing/invalid, model unavailable, quota exhausted) stop the
  generate job explicitly instead of being recorded as "insufficient evidence" for every
  question.
- ``retryable`` describes whether the same request may succeed later without operator action.
  Bounded retry scheduling itself is owned by TC-10-002; this module only classifies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ModelOutcomeCode(str, Enum):
    """Stable outcome/error codes for model-backed answer generation."""

    GROUNDED = "grounded"
    # Answer-cache hit: the text was reused from an earlier run and its citations were NOT
    # re-validated against the current evidence. Never reported as "grounded" until
    # claim-level citation checks (TC-11-003) and version-scoped caches (TC-08-004) land.
    GROUNDED_UNVERIFIED = "grounded_unverified"
    NO_EVIDENCE = "no_evidence"
    MODEL_ABSTAINED = "model_abstained"
    MODEL_REFUSAL = "model_refusal"
    MODEL_MALFORMED_OUTPUT = "model_malformed_output"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    MODEL_RATE_LIMITED = "model_rate_limited"
    MODEL_QUOTA_EXHAUSTED = "model_quota_exhausted"
    MODEL_SERVER_ERROR = "model_server_error"
    MODEL_REQUEST_REJECTED = "model_request_rejected"
    MODEL_CREDENTIALS_MISSING = "model_credentials_missing"
    MODEL_CREDENTIALS_INVALID = "model_credentials_invalid"
    MODEL_ERROR = "model_error"


@dataclass(frozen=True)
class OutcomeSpec:
    """Catalog entry: safe message and handling flags for one code."""

    code: ModelOutcomeCode
    message: str
    retryable: bool
    fatal: bool
    is_failure: bool
    http_status: int


def _spec(
    code: ModelOutcomeCode,
    message: str,
    *,
    retryable: bool = False,
    fatal: bool = False,
    is_failure: bool = True,
    http_status: int = 502,
) -> OutcomeSpec:
    return OutcomeSpec(code, message, retryable, fatal, is_failure, http_status)


_C = ModelOutcomeCode
OUTCOME_CATALOG: dict[ModelOutcomeCode, OutcomeSpec] = {
    s.code: s
    for s in (
        _spec(
            _C.GROUNDED,
            "Draft answer generated from the supplied evidence. Review the citations before approving.",
            is_failure=False,
            http_status=200,
        ),
        _spec(
            _C.GROUNDED_UNVERIFIED,
            "Draft answer reused from an earlier run. Its citations have not been re-checked "
            "against the current evidence. Verify them before approving.",
            is_failure=False,
            http_status=200,
        ),
        _spec(
            _C.NO_EVIDENCE,
            "No eligible evidence was found for this question, so no model call was made.",
            is_failure=False,
            http_status=200,
        ),
        _spec(
            _C.MODEL_ABSTAINED,
            "The model reviewed the supplied evidence and judged it insufficient to answer.",
            is_failure=False,
            http_status=200,
        ),
        _spec(
            _C.MODEL_REFUSAL,
            "The model declined to answer this question. Answer it manually.",
            http_status=422,
        ),
        _spec(
            _C.MODEL_MALFORMED_OUTPUT,
            "The model returned output that could not be used as an answer.",
            retryable=True,
        ),
        _spec(
            _C.MODEL_UNAVAILABLE,
            "The configured model is not available to this deployment. Check the model setting.",
            fatal=True,
            http_status=503,
        ),
        _spec(
            _C.MODEL_TIMEOUT,
            "The model provider did not respond in time. Try again.",
            retryable=True,
            http_status=504,
        ),
        _spec(
            _C.MODEL_RATE_LIMITED,
            "The model provider is rate limiting requests. Try again later.",
            retryable=True,
            http_status=429,
        ),
        _spec(
            _C.MODEL_QUOTA_EXHAUSTED,
            "The model provider account has no remaining quota. Ask an administrator to check billing.",
            fatal=True,
            http_status=503,
        ),
        _spec(
            _C.MODEL_SERVER_ERROR,
            "The model provider is temporarily unavailable. Try again later.",
            retryable=True,
            http_status=503,
        ),
        _spec(
            _C.MODEL_REQUEST_REJECTED,
            "The model provider rejected the request for this question.",
        ),
        _spec(
            _C.MODEL_CREDENTIALS_MISSING,
            "Model provider credentials are not configured. Set OPENAI_API_KEY for the API and "
            "worker services, then restart.",
            fatal=True,
            http_status=503,
        ),
        _spec(
            _C.MODEL_CREDENTIALS_INVALID,
            "Model provider credentials were rejected. Update OPENAI_API_KEY for the API and "
            "worker services, then restart.",
            fatal=True,
            http_status=503,
        ),
        _spec(
            _C.MODEL_ERROR,
            "The model call failed unexpectedly.",
        ),
    )
}


def outcome_spec(code: ModelOutcomeCode | str) -> OutcomeSpec | None:
    """Return the catalog entry for a code (enum or persisted string), or None if unknown."""
    try:
        return OUTCOME_CATALOG[ModelOutcomeCode(code)]
    except ValueError:
        return None


@dataclass(frozen=True)
class ModelFailure:
    """A classified provider/model failure.

    ``provider_status`` and ``exception_type`` are internal diagnostics for logs and are never
    serialized to API clients.
    """

    code: ModelOutcomeCode
    provider_status: int | None = None
    exception_type: str | None = None

    @property
    def spec(self) -> OutcomeSpec:
        return OUTCOME_CATALOG[self.code]

    @property
    def message(self) -> str:
        return self.spec.message

    @property
    def retryable(self) -> bool:
        return self.spec.retryable

    @property
    def fatal(self) -> bool:
        return self.spec.fatal

    def log_summary(self) -> str:
        """Safe one-line summary for logs (no provider body)."""
        return (
            f"code={self.code.value} provider_status={self.provider_status} "
            f"exception_type={self.exception_type}"
        )


class ModelCallError(ValueError):
    """Raised when a model failure must stop the current operation.

    Subclasses ``ValueError`` so existing callers that treat configuration problems as
    ``ValueError`` keep working. ``str(err)`` is always the safe catalog message.
    """

    def __init__(self, failure: ModelFailure):
        super().__init__(failure.message)
        self.failure = failure

    @property
    def code(self) -> ModelOutcomeCode:
        return self.failure.code

    @property
    def retryable(self) -> bool:
        return self.failure.retryable


def _status_code(exc: BaseException) -> int | None:
    code = getattr(exc, "status_code", None)
    if code is None:
        code = getattr(getattr(exc, "response", None), "status_code", None)
    return code if isinstance(code, int) else None


def _is_instance(exc: BaseException, name: str) -> bool:
    try:
        import openai
    except Exception:  # pragma: no cover - openai is a declared dependency
        return False
    cls = getattr(openai, name, None)
    return isinstance(cls, type) and isinstance(exc, cls)


def classify_provider_exception(exc: BaseException) -> ModelFailure:
    """Map a provider/client exception to a typed failure without reading its body text.

    Decision order: explicit typed error passthrough, timeout, connection, HTTP status, then a
    conservative non-retryable ``model_error`` fallback.
    """
    if isinstance(exc, ModelCallError):
        return exc.failure
    etype = type(exc).__name__
    status = _status_code(exc)

    def failure(code: ModelOutcomeCode) -> ModelFailure:
        return ModelFailure(code=code, provider_status=status, exception_type=etype)

    if _is_instance(exc, "APITimeoutError") or isinstance(exc, TimeoutError):
        return failure(_C.MODEL_TIMEOUT)
    if _is_instance(exc, "APIConnectionError"):
        return failure(_C.MODEL_SERVER_ERROR)
    if status is not None:
        if status in (401, 403):
            return failure(_C.MODEL_CREDENTIALS_INVALID)
        if status == 404:
            return failure(_C.MODEL_UNAVAILABLE)
        if status == 408:
            return failure(_C.MODEL_TIMEOUT)
        if status == 429:
            provider_code = getattr(exc, "code", None)
            if isinstance(provider_code, str) and provider_code == "insufficient_quota":
                return failure(_C.MODEL_QUOTA_EXHAUSTED)
            return failure(_C.MODEL_RATE_LIMITED)
        if status in (400, 413, 422):
            return failure(_C.MODEL_REQUEST_REJECTED)
        if status == 409 or status >= 500:
            return failure(_C.MODEL_SERVER_ERROR)
    if _is_instance(exc, "AuthenticationError") or _is_instance(exc, "PermissionDeniedError"):
        return failure(_C.MODEL_CREDENTIALS_INVALID)
    if _is_instance(exc, "NotFoundError"):
        return failure(_C.MODEL_UNAVAILABLE)
    if _is_instance(exc, "RateLimitError"):
        return failure(_C.MODEL_RATE_LIMITED)
    return failure(_C.MODEL_ERROR)


def is_provider_exception(exc: BaseException) -> bool:
    """True for typed model errors and openai client exceptions (bodies must not leak)."""
    return isinstance(exc, ModelCallError) or _is_instance(exc, "OpenAIError")


def failure_from_exception(exc: BaseException) -> ModelFailure | None:
    """Typed failure for provider-originated exceptions; None for unrelated exceptions."""
    if not is_provider_exception(exc):
        return None
    return classify_provider_exception(exc)


@dataclass(frozen=True)
class CompletionView:
    """Provider-neutral view of the first completion choice."""

    content: str | None
    refusal: str | None
    finish_reason: str | None
    has_choice: bool


def read_completion(response: Any) -> CompletionView:
    """Extract content/refusal/finish_reason defensively (only real ``str`` values count)."""
    try:
        choices = getattr(response, "choices", None)
        choice = choices[0] if choices else None
    except Exception:
        choice = None
    if choice is None:
        return CompletionView(None, None, None, has_choice=False)
    message = getattr(choice, "message", None)
    content = getattr(message, "content", None)
    refusal = getattr(message, "refusal", None)
    finish = getattr(choice, "finish_reason", None)
    return CompletionView(
        content=content if isinstance(content, str) else None,
        refusal=refusal if isinstance(refusal, str) and refusal.strip() else None,
        finish_reason=finish if isinstance(finish, str) else None,
        has_choice=True,
    )


def completion_failure(view: CompletionView) -> ModelOutcomeCode | None:
    """Failure code implied by the response envelope itself, before reading answer text."""
    if not view.has_choice:
        return _C.MODEL_MALFORMED_OUTPUT
    if view.refusal is not None or view.finish_reason == "content_filter":
        return _C.MODEL_REFUSAL
    if not (view.content or "").strip():
        return _C.MODEL_MALFORMED_OUTPUT
    return None
