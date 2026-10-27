"""Error-class and bounded-retry seam for Slack and Gmail HTTP calls.

This is not TC-10-002. Attempts are capped (default 3). Rate limits, timeouts,
transport errors, and HTTP 5xx are retryable. Denied, missing-scope, and other
non-retryable failures stop on the first attempt. Exhaustion stays a failure
(``ok`` is false). There is no jitter and no job lease. The default sleeper
does not wait; ``Retry-After`` is recorded for a later policy to use.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import httpx

from app.services.message_providers.errors import (
    ERROR_DENIED,
    ERROR_MISSING_SCOPE,
    ERROR_RATE_LIMITED,
    ERROR_UNKNOWN,
    failure_result,
    safe_message,
)
from app.services.message_providers.outbound_http import MAX_RESPONSE_BYTES, OutboundHttpDenied

DEFAULT_MAX_ATTEMPTS = 3

_SLACK_DENIED = frozenset(
    {
        "invalid_auth",
        "not_authed",
        "account_inactive",
        "token_revoked",
        "token_expired",
        "invalid_token",
        "org_login_required",
        "ekm_access_denied",
        "not_allowed_token_type",
        "no_permission",
        "permission_denied",
    }
)
_SLACK_SCOPE = frozenset({"missing_scope", "insufficient_scope"})
_SLACK_RATE = frozenset({"ratelimited", "rate_limited"})

_GMAIL_SCOPE = frozenset(
    {
        "insufficientPermissions",
        "insufficientAuthenticationScopes",
        "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
    }
)
_GMAIL_RATE = frozenset(
    {
        "rateLimitExceeded",
        "userRateLimitExceeded",
        "quotaExceeded",
        "dailyLimitExceeded",
        "RESOURCE_EXHAUSTED",
    }
)
_GMAIL_DENIED = frozenset(
    {
        "authError",
        "UNAUTHENTICATED",
        "PERMISSION_DENIED",
        "forbidden",
        "domainPolicy",
    }
)


@dataclass
class ProviderCallResult:
    ok: bool
    status_code: int | None
    body: dict
    error_code: str | None
    safe_message: str | None
    retryable: bool
    attempts: int
    provider_error: str | None
    exhausted: bool = False
    retry_after: float | None = None


def _fail(
    *,
    status_code: int | None,
    error_code: str,
    attempts: int,
    provider_error: str | None,
    retryable: bool,
    message: str | None = None,
    retry_after: float | None = None,
    body: dict | None = None,
) -> ProviderCallResult:
    return ProviderCallResult(
        ok=False,
        status_code=status_code,
        body=body or {},
        error_code=error_code,
        safe_message=message or safe_message(error_code),
        retryable=retryable,
        attempts=attempts,
        provider_error=provider_error,
        retry_after=retry_after,
    )


def _parse_retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        seconds = float(raw.strip())
    except ValueError:
        return None
    if seconds < 0:
        return None
    return seconds


def _read_json(response: httpx.Response) -> tuple[dict | None, str | None]:
    content = response.content
    if len(content) > MAX_RESPONSE_BYTES:
        return None, "response_too_large"
    if not content:
        return {}, None
    try:
        parsed = response.json()
    except Exception:
        return None, "invalid_json"
    if not isinstance(parsed, dict):
        return None, "invalid_json"
    return parsed, None


def _gmail_reasons(body: dict) -> list[str]:
    reasons: list[str] = []
    err = body.get("error")
    if isinstance(err, str) and err:
        reasons.append(err)
    if not isinstance(err, dict):
        return reasons
    status = err.get("status")
    if isinstance(status, str) and status:
        reasons.append(status)
    for key in ("errors", "details"):
        items = err.get(key) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                reason = item.get("reason")
                if isinstance(reason, str) and reason:
                    reasons.append(reason)
    return reasons


def _classify_slack(
    status_code: int, body: dict, attempts: int, retry_after: float | None
) -> ProviderCallResult:
    if status_code == 429:
        return _fail(
            status_code=status_code,
            error_code=ERROR_RATE_LIMITED,
            attempts=attempts,
            provider_error="ratelimited",
            retryable=True,
            retry_after=retry_after,
            body=body,
        )
    if status_code >= 500:
        return _fail(
            status_code=status_code,
            error_code=ERROR_UNKNOWN,
            attempts=attempts,
            provider_error=f"http_{status_code}",
            retryable=True,
            body=body,
        )
    if status_code in (401, 403) and body.get("ok") is not True:
        code = body.get("error") if isinstance(body.get("error"), str) else None
        if code in _SLACK_SCOPE:
            error_code = ERROR_MISSING_SCOPE
        elif status_code == 403 and code not in _SLACK_DENIED:
            error_code = ERROR_DENIED if code not in _SLACK_SCOPE else ERROR_MISSING_SCOPE
        else:
            error_code = ERROR_DENIED
        return _fail(
            status_code=status_code,
            error_code=error_code,
            attempts=attempts,
            provider_error=code or ("http_401" if status_code == 401 else "http_403"),
            retryable=False,
            body=body,
        )
    if body.get("ok") is True:
        return ProviderCallResult(
            ok=True,
            status_code=status_code,
            body=body,
            error_code=None,
            safe_message=None,
            retryable=False,
            attempts=attempts,
            provider_error=None,
        )
    code = body.get("error") if isinstance(body.get("error"), str) else None
    if code in _SLACK_DENIED:
        error_code = ERROR_DENIED
        retryable = False
    elif code in _SLACK_SCOPE:
        error_code = ERROR_MISSING_SCOPE
        retryable = False
    elif code in _SLACK_RATE:
        error_code = ERROR_RATE_LIMITED
        retryable = True
    else:
        error_code = ERROR_UNKNOWN
        retryable = False
    return _fail(
        status_code=status_code,
        error_code=error_code,
        attempts=attempts,
        provider_error=code or "unknown",
        retryable=retryable,
        retry_after=retry_after if retryable else None,
        body=body,
    )


def _classify_gmail(
    status_code: int, body: dict, attempts: int, retry_after: float | None
) -> ProviderCallResult:
    reasons = _gmail_reasons(body)
    if status_code == 200 and body and not reasons:
        return ProviderCallResult(
            ok=True,
            status_code=status_code,
            body=body,
            error_code=None,
            safe_message=None,
            retryable=False,
            attempts=attempts,
            provider_error=None,
        )
    provider_error = reasons[0] if reasons else f"http_{status_code}"
    if status_code == 429 or any(r in _GMAIL_RATE for r in reasons):
        return _fail(
            status_code=status_code,
            error_code=ERROR_RATE_LIMITED,
            attempts=attempts,
            provider_error=provider_error,
            retryable=True,
            retry_after=retry_after,
            body=body,
        )
    if status_code >= 500:
        return _fail(
            status_code=status_code,
            error_code=ERROR_UNKNOWN,
            attempts=attempts,
            provider_error=provider_error,
            retryable=True,
            body=body,
        )
    if any(r in _GMAIL_SCOPE for r in reasons):
        return _fail(
            status_code=status_code,
            error_code=ERROR_MISSING_SCOPE,
            attempts=attempts,
            provider_error=next(r for r in reasons if r in _GMAIL_SCOPE),
            retryable=False,
            body=body,
        )
    if status_code in (401, 403) or any(r in _GMAIL_DENIED for r in reasons):
        return _fail(
            status_code=status_code,
            error_code=ERROR_DENIED,
            attempts=attempts,
            provider_error=provider_error,
            retryable=False,
            body=body,
        )
    return _fail(
        status_code=status_code,
        error_code=ERROR_UNKNOWN,
        attempts=attempts,
        provider_error=provider_error,
        retryable=False,
        body=body,
    )


def classify_response(response: httpx.Response, provider: str, attempts: int) -> ProviderCallResult:
    retry_after = _parse_retry_after(response)
    status_code = response.status_code
    if 300 <= status_code < 400:
        return _fail(
            status_code=status_code,
            error_code=ERROR_UNKNOWN,
            attempts=attempts,
            provider_error="redirect_blocked",
            retryable=False,
            message="Redirect was not followed.",
        )
    body, parse_error = _read_json(response)
    if parse_error == "response_too_large":
        return _fail(
            status_code=status_code,
            error_code=ERROR_UNKNOWN,
            attempts=attempts,
            provider_error="response_too_large",
            retryable=False,
            message="The provider response exceeded the size limit.",
        )
    if parse_error == "invalid_json" or body is None:
        retryable = status_code >= 500 or status_code == 429
        return _fail(
            status_code=status_code,
            error_code=ERROR_RATE_LIMITED if status_code == 429 else ERROR_UNKNOWN,
            attempts=attempts,
            provider_error="invalid_json" if status_code < 500 else f"http_{status_code}",
            retryable=retryable,
            retry_after=retry_after if retryable else None,
        )
    if provider == "slack":
        return _classify_slack(status_code, body, attempts, retry_after)
    return _classify_gmail(status_code, body, attempts, retry_after)


def call_result_to_dict(result: ProviderCallResult, provider: str) -> dict:
    if result.ok:
        body = dict(result.body)
        body["ok"] = True
        body["provider"] = provider
        body["provider_mode"] = "http"
        body["retryable"] = False
        body["delivered_to_provider"] = True
        return body
    return failure_result(
        error_code=result.error_code or ERROR_UNKNOWN,
        provider=provider,
        retryable=result.retryable,
        error=result.safe_message,
        attempts=result.attempts,
        provider_error=result.provider_error,
        exhausted=result.exhausted,
    )


class BoundedRetrySeam:
    def __init__(self, max_attempts: int = DEFAULT_MAX_ATTEMPTS, sleeper=None) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.max_attempts = max_attempts
        self._sleeper = sleeper if sleeper is not None else (lambda _attempt, _retry_after: None)

    def execute(self, call, *, provider: str) -> ProviderCallResult:
        last: ProviderCallResult | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = call()
            except OutboundHttpDenied:
                return _fail(
                    status_code=None,
                    error_code=ERROR_DENIED,
                    attempts=attempt,
                    provider_error="outbound_not_allowlisted",
                    retryable=False,
                    message="Outbound call blocked by the message-provider allowlist.",
                )
            except httpx.TimeoutException:
                last = _fail(
                    status_code=None,
                    error_code=ERROR_UNKNOWN,
                    attempts=attempt,
                    provider_error="timeout",
                    retryable=True,
                    message="The provider request timed out.",
                )
            except httpx.TransportError:
                last = _fail(
                    status_code=None,
                    error_code=ERROR_UNKNOWN,
                    attempts=attempt,
                    provider_error="transport",
                    retryable=True,
                    message="The provider request could not be sent.",
                )
            else:
                last = classify_response(response, provider, attempt)
            if last.ok or not last.retryable:
                return last
            if attempt >= self.max_attempts:
                return replace(last, exhausted=True)
            self._sleeper(attempt, last.retry_after)
        assert last is not None
        return replace(last, exhausted=True)
