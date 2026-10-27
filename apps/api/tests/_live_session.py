"""Helpers for the manual live-API scripts in this directory (not collected by pytest).

TC-07-001: these scripts previously embedded a real signing secret and a personal e-mail
address. The signing secret must now be supplied by the operator at run time, and only for
a LOCAL development stack, e.g.:

    TC_SESSION_SECRET=<value of SESSION_SECRET in your local .env> python tests/fetch_ds5.py

Never point these scripts at a shared or production deployment.
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import sys
import time

DEFAULT_LIVE_EMAIL = "admin@example.test"  # synthetic; override with TC_LIVE_EMAIL


def live_api() -> str:
    return os.environ.get("TC_API", "http://localhost:8000")


def live_session_secret() -> str:
    secret = os.environ.get("TC_SESSION_SECRET", "")
    if not secret:
        sys.exit(
            "TC_SESSION_SECRET is not set. Export the SESSION_SECRET of your LOCAL stack "
            "(never a shared/production value) and re-run."
        )
    return secret


def forge_session_cookie(
    workspace_id: int = 1, user_id: int = 1, role: str = "admin", ttl_seconds: int = 3600
) -> str:
    """Build a short-lived tc_session cookie for a local stack (same format as app.core.session)."""
    payload = {
        "user_id": user_id,
        "email": os.environ.get("TC_LIVE_EMAIL", DEFAULT_LIVE_EMAIL),
        "workspace_id": workspace_id,
        "role": role,
        "exp": int(time.time()) + ttl_seconds,
    }
    data = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    sig = hmac.new(
        live_session_secret().encode("utf-8"), data.encode("utf-8"), "sha256"
    ).hexdigest()
    return f"{data}.{sig}"
