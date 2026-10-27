"""Typed message-provider failures.

Success is ``ok: true`` only when the provider accepted the call.
Denied, missing-scope, rate-limited, unknown, not-implemented, and
unsupported results are never ``ok``.
"""

from __future__ import annotations

DEV_STUB_MODE = "dev-stub"
HTTP_MODE = "http"
DEV_STUB_LABEL = "development-stub"

ERROR_DENIED = "denied"
ERROR_MISSING_SCOPE = "missing_scope"
ERROR_RATE_LIMITED = "rate_limited"
ERROR_UNKNOWN = "unknown"
ERROR_NOT_IMPLEMENTED = "not_implemented"
ERROR_UNSUPPORTED = "unsupported"
ERROR_DEV_STUB_FORBIDDEN = "dev_stub_forbidden"

_SAFE_MESSAGES = {
    ERROR_DENIED: "The provider denied the request.",
    ERROR_MISSING_SCOPE: "The provider token is missing a required scope.",
    ERROR_RATE_LIMITED: "The provider rate limit was reached.",
    ERROR_UNKNOWN: "The provider request failed.",
    ERROR_NOT_IMPLEMENTED: "This provider method is not implemented.",
    ERROR_UNSUPPORTED: "This provider method is unsupported.",
    ERROR_DEV_STUB_FORBIDDEN: "Development stub cannot report delivery in production.",
}


def safe_message(error_code: str) -> str:
    return _SAFE_MESSAGES.get(error_code, _SAFE_MESSAGES[ERROR_UNKNOWN])


def failure_result(
    *,
    error_code: str,
    provider: str,
    retryable: bool,
    provider_mode: str = HTTP_MODE,
    error: str | None = None,
    attempts: int | None = None,
    provider_error: str | None = None,
    exhausted: bool = False,
) -> dict:
    """Return a failure dict. ``ok`` is always false."""
    body: dict = {
        "ok": False,
        "error_code": error_code,
        "error": error or safe_message(error_code),
        "retryable": bool(retryable),
        "provider": provider,
        "provider_mode": provider_mode,
        "delivered_to_provider": False,
    }
    if attempts is not None:
        body["attempts"] = attempts
    if provider_error:
        body["provider_error"] = provider_error
    if exhausted:
        body["exhausted"] = True
    return body


def not_implemented_result(provider: str, method: str, ticket: str) -> dict:
    return failure_result(
        error_code=ERROR_NOT_IMPLEMENTED,
        provider=provider,
        retryable=False,
        error=f"{method} is not implemented ({ticket}).",
        provider_error="not_implemented",
    )


def dev_stub_forbidden_result(provider: str) -> dict:
    return failure_result(
        error_code=ERROR_DEV_STUB_FORBIDDEN,
        provider=provider,
        retryable=False,
        provider_mode=DEV_STUB_MODE,
        provider_error="dev_stub_forbidden",
    )


def is_provider_failure(result: object) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("ok") is False:
        return True
    return bool(result.get("error_code"))


def public_error_detail(result: object, fallback: str) -> str:
    if not isinstance(result, dict):
        return fallback
    text = result.get("error")
    if not isinstance(text, str) or not text.strip():
        return fallback
    return text.strip()[:300]
