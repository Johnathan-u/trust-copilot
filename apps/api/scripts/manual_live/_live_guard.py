"""Safety guard shared by the manual live-stack scripts in this directory (TC-02-001).

These scripts talk to a *running* Trust Copilot stack. They are deliberately kept
outside ``tests/`` so pytest never imports them. The guard enforces:

* Target must be a local stack: loopback (localhost/127.0.0.1/::1) or a docker-compose
  service name (``api``, ``caddy``, ``web``). Any other host is refused - there is no
  override, so these scripts can never be pointed at staging or production.
* No checked-in credentials: forging a session cookie requires ``TC_SESSION_SECRET``
  in the environment (the local stack's own SESSION_SECRET). There is no default.
* Identities are synthetic (``*@trust.local`` demo accounts).
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import sys
import time
from urllib.parse import urlparse

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "api", "caddy", "web"})
DEFAULT_API = "http://localhost:8000"
SYNTHETIC_ADMIN_EMAIL = "admin@trust.local"


class UnsafeTargetError(SystemExit):
    """Raised (as SystemExit) when a script is pointed at a non-local target."""


def require_local_url(url: str, *, purpose: str = "TC_API") -> str:
    host = (urlparse(url).hostname or "").lower()
    if host not in LOCAL_HOSTS:
        raise UnsafeTargetError(
            f"refusing to run: {purpose}={url!r} is not a local stack host "
            f"(allowed: {', '.join(sorted(LOCAL_HOSTS))})"
        )
    return url.rstrip("/")


def api_base() -> str:
    return require_local_url(os.environ.get("TC_API", DEFAULT_API))


def require_session_secret() -> str:
    secret = os.environ.get("TC_SESSION_SECRET", "")
    if not secret:
        raise SystemExit(
            "refusing to run: set TC_SESSION_SECRET to the SESSION_SECRET of your *local* stack. "
            "No secret is checked in."
        )
    return secret


def forge_session_cookie(
    workspace_id: int, *, user_id: int = 1, role: str = "admin", ttl_seconds: int = 3600
) -> str:
    """Build a short-lived tc_session cookie for a local stack (TC_SESSION_SECRET, synthetic identity).

    TC-07-001: the cookie carries an ``exp`` claim so a copied cookie stops working.
    """
    secret = require_session_secret()
    email = os.environ.get("TC_SESSION_EMAIL", SYNTHETIC_ADMIN_EMAIL)
    if not email.endswith("@trust.local"):
        raise SystemExit(
            "refusing to run: TC_SESSION_EMAIL must be a synthetic *@trust.local identity"
        )
    payload = {
        "user_id": user_id,
        "email": email,
        "workspace_id": workspace_id,
        "role": role,
        "exp": int(time.time()) + ttl_seconds,
    }
    data = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    sig = hmac.new(secret.encode("utf-8"), data.encode("utf-8"), "sha256").hexdigest()
    return f"{data}.{sig}"


def require_data_file(env_var: str) -> str:
    path = os.environ.get(env_var, "")
    if not path or not os.path.exists(path):
        print(f"set {env_var} to the local path of the dataset file", file=sys.stderr)
        raise SystemExit(2)
    return path
