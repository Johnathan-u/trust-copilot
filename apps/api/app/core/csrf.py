"""CSRF protection for cookie-based auth (SEC-201). State-changing requests with session cookie require Origin or Referer to match allowed origins.

Allowed origins are supplied by the caller (from app.core.config trusted_origins). Do not rely on DEFAULT_ALLOWED_ORIGINS in production; the middleware passes settings.trusted_origins.
"""

from urllib.parse import urlparse

# Fallback only when allowed_origins is not passed (e.g. tests). Production uses config.trusted_origins.
DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost",
    "http://localhost:3000",
    "http://127.0.0.1",
    "http://127.0.0.1:3000",
    "http://[::1]",
    "http://[::1]:3000",
]


def _normalize_origin(origin: str | None) -> str | None:
    if not origin or not origin.strip():
        return None
    o = origin.strip().lower()
    if not o.startswith("http://") and not o.startswith("https://"):
        return None
    return o.rstrip("/")


def _origin_from_referer(referer: str | None) -> str | None:
    if not referer or not referer.strip():
        return None
    try:
        parsed = urlparse(referer.strip())
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}".lower()
    except Exception:
        pass
    return None


def is_csrf_safe(
    method: str,
    origin: str | None,
    referer: str | None,
    has_session_cookie: bool,
    allowed_origins: list[str] | None = None,
    request_host: str | None = None,
    x_forwarded_host: str | None = None,
    x_forwarded_proto: str | None = None,
) -> bool:
    """Return True if request is safe (no CSRF risk or origin/referer allowed)."""
    state_changing = method.upper() in ("POST", "PUT", "PATCH", "DELETE")
    if not state_changing or not has_session_cookie:
        return True
    origins = allowed_origins or DEFAULT_ALLOWED_ORIGINS
    normalized_allowed = {_normalize_origin(o) for o in origins if _normalize_origin(o)}
    req_origin = _normalize_origin(origin)
    if req_origin and req_origin in normalized_allowed:
        return True
    req_ref_origin = _origin_from_referer(referer)
    if req_ref_origin and req_ref_origin in normalized_allowed:
        return True
    # Caddy/nginx: upstream Host may be "api:8000" while browser hit https://app.example.com.
    # Only accept when the synthetic origin is explicitly in the same trusted list as Origin checks.
    xfh = (x_forwarded_host or "").strip()
    if xfh and ".." not in xfh:
        proto = (x_forwarded_proto or "http").split(",")[0].strip().lower()
        if proto not in ("http", "https"):
            proto = "http"
        host_part = xfh.split(",")[0].strip()
        if host_part and "/" not in host_part and "\\" not in host_part:
            syn = _normalize_origin(f"{proto}://{host_part}")
            if syn and syn in normalized_allowed:
                return True
    # Dev/proxy: when Next.js or same-host proxy forwards without Origin/Referer, allow if host is local or test
    if request_host and not origin and not referer:
        if request_host in ("localhost", "127.0.0.1", "::1", "::ffff:127.0.0.1", "testserver"):
            return True
    return False
