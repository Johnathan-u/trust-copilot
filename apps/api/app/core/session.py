"""Session handling with signed cookies (AUTH-02, SESS-01)."""

import base64
import hmac
import json
import time

from app.core.config import get_settings

# Default absolute session lifetime (7 days)
SESSION_MAX_AGE = 86400 * 7


import logging as _logging
import os as _os

_session_logger = _logging.getLogger(__name__)
_DEV_SECRET = "change_me_dev_secret"


def _get_session_secret() -> str:
    """Get session secret for signing.

    In production (APP_ENV=production) the secret MUST be set explicitly;
    startup will fail fast if it is missing or still the dev default.
    In dev/test a fallback is allowed with a warning.
    """
    try:
        s = get_settings().session_secret
        if isinstance(s, bytes):
            s = s.decode("utf-8", "replace")
        if s and isinstance(s, str) and s != _DEV_SECRET:
            return s
    except Exception:
        s = None

    app_env = _os.getenv("APP_ENV", "development").lower()
    if app_env == "production":
        raise RuntimeError(
            "SESSION_SECRET is missing or using the default dev value. "
            "Set a strong random SESSION_SECRET for production."
        )
    _session_logger.warning(
        "SESSION_SECRET not set or using dev default — acceptable only in dev/test. "
        "Set a strong random value before deploying."
    )
    return _DEV_SECRET


def sign_token(payload: dict) -> str:
    """Create signed token."""
    try:
        data = base64.urlsafe_b64encode(json.dumps(payload, default=str).encode()).decode()
    except (TypeError, ValueError):
        data = base64.urlsafe_b64encode(json.dumps({k: str(v) for k, v in payload.items()}).encode()).decode()
    secret = _get_session_secret()
    sig = hmac.new(
        secret.encode("utf-8", "replace"),
        data.encode("utf-8"),
        "sha256",
    ).hexdigest()
    return f"{data}.{sig}"


def sign_session(
    user_id: int,
    email: str,
    workspace_id: int = 1,
    role: str = "editor",
    session_id: str | None = None,
    max_age_seconds: int | None = None,
) -> str:
    """Create session token. ENT-202: max_age_seconds sets exp claim (per-workspace policy)."""
    payload = {
        "user_id": user_id,
        "email": email,
        "workspace_id": workspace_id,
        "role": role,
    }
    if session_id:
        payload["session_id"] = session_id
    if max_age_seconds is not None:
        payload["exp"] = int(time.time()) + max_age_seconds
    return sign_token(payload)


def verify_token(token: str) -> dict | None:
    """Verify and decode token, return payload or None. Rejects expired tokens (SESS-201)."""
    try:
        if not token or "." not in token:
            return None
        data, sig = token.rsplit(".", 1)
        secret = _get_session_secret()
        expected = hmac.new(
            secret.encode("utf-8", "replace"),
            data.encode("utf-8"),
            "sha256",
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(data).decode())
        exp = payload.get("exp")
        if exp is not None and int(exp) < time.time():
            return None  # Expired
        return payload
    except Exception:
        return None
