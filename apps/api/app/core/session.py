"""Session handling with signed cookies (AUTH-02, SESS-01)."""

import base64
import hmac
import json
import time

from app.core.config import get_settings

# Default absolute session lifetime (7 days)
SESSION_MAX_AGE = 86400 * 7


import logging as _logging  # noqa: E402
import os as _os  # noqa: E402
import secrets as _secrets  # noqa: E402
import threading as _threading  # noqa: E402

_session_logger = _logging.getLogger(__name__)

# TC-07-001: there is deliberately NO hard-coded fallback signing key.
# Outside production, an unset SESSION_SECRET falls back to a random per-process value
# (sessions do not survive a restart and are not shared between processes).
_EPHEMERAL_SECRET: str | None = None
_EPHEMERAL_LOCK = _threading.Lock()

# Minimum length enforced in production (also enforced at startup in app.main / app.core.config_contract).
MIN_PRODUCTION_SECRET_LENGTH = 32

# Values that are obviously not secrets (copied from examples / docs / tests).
_PLACEHOLDER_SECRETS = frozenset(
    {
        "placeholder",
        "changeme",
        "change-me",
        "change_me",
        "secret",
        "test-secret",
        "dev-secret",
        "your-secret-here",
        "replace-me",
        "session-secret",
        "development",
        "default",
    }
)


def is_weak_secret(value: str | None, min_length: int = MIN_PRODUCTION_SECRET_LENGTH) -> bool:
    """True when ``value`` is unset, a known placeholder, too short, or trivially low-entropy."""
    if not value or not isinstance(value, str):
        return True
    v = value.strip()
    if v.lower() in _PLACEHOLDER_SECRETS or "placeholder" in v.lower():
        return True
    if len(v) < min_length:
        return True
    if len(set(v)) < 8:  # e.g. "aaaaaaaa..." or "abababab..."
        return True
    return False


def _ephemeral_secret() -> str:
    global _EPHEMERAL_SECRET
    with _EPHEMERAL_LOCK:
        if _EPHEMERAL_SECRET is None:
            _EPHEMERAL_SECRET = _secrets.token_urlsafe(48)
            _session_logger.warning(
                "SESSION_SECRET is not set; using a random per-process signing key (dev/test only). "
                "Sessions and encrypted values will not survive a restart. Set SESSION_SECRET in .env."
            )
        return _EPHEMERAL_SECRET


def _get_session_secret() -> str:
    """Return the signing secret for session cookies, OAuth state and derived encryption keys.

    In production (APP_ENV=production) SESSION_SECRET MUST be set to a strong value
    (>= 32 chars, not a placeholder); otherwise RuntimeError is raised (fail closed).
    Outside production an unset value falls back to a random per-process key.
    """
    try:
        s = get_settings().session_secret
        if isinstance(s, bytes):
            s = s.decode("utf-8", "replace")
    except Exception:
        s = None

    app_env = _os.getenv("APP_ENV", "development").strip().lower()
    if app_env == "production":
        if is_weak_secret(s):
            raise RuntimeError(
                "SESSION_SECRET is missing, a placeholder, or weaker than required for production. "
                "Set a cryptographically random SESSION_SECRET of at least 32 characters."
            )
        return s  # type: ignore[return-value]
    if s and isinstance(s, str):
        return s
    return _ephemeral_secret()


def get_session_secret() -> str:
    """Public accessor used by every consumer of the signing secret (no module should read the env var directly)."""
    return _get_session_secret()


def sign_token(payload: dict) -> str:
    """Create signed token."""
    try:
        data = base64.urlsafe_b64encode(json.dumps(payload, default=str).encode()).decode()
    except (TypeError, ValueError):
        data = base64.urlsafe_b64encode(
            json.dumps({k: str(v) for k, v in payload.items()}).encode()
        ).decode()
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
