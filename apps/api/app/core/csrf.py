"""CSRF protection for cookie-based auth (SEC-201).

State-changing requests with a session cookie require an allowed Origin or Referer.
Allowed origins come from the caller (settings.trusted_origins in production).
Do not rely on DEFAULT_ALLOWED_ORIGINS in production.

A present Origin that is not allowed is final (TC-07-004), including the literal
``null``. Referer and X-Forwarded-Host/Proto are used only when Origin is absent.
Those forwarded headers count only when the direct peer is listed in
TRUSTED_PROXY_IPS (IPs or CIDRs). An empty list trusts none of them.

The localhost/testserver host fallback is dev and test only. ``CSRFMiddleware``
passes ``production=is_production_env()``. This function does not read APP_ENV.
"""

import ipaddress
from urllib.parse import urlparse

# Fallback only when allowed_origins is not passed (e.g. tests). Production uses config.trusted_origins.
DEFAULT_ALLOWED_ORIGINS = [
    "https://localhost",
    "https://localhost:3000",
    "https://127.0.0.1",
    "https://127.0.0.1:3000",
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


def _origin_header_present(origin: str | None) -> bool:
    """True when Origin was sent with a non-blank value. A blank header is absent."""
    return bool(origin and origin.strip())


def _origin_from_forwarded(
    x_forwarded_host: str | None, x_forwarded_proto: str | None
) -> str | None:
    """Build an origin from the first X-Forwarded-Host and X-Forwarded-Proto values."""
    xfh = (x_forwarded_host or "").strip()
    if not xfh or ".." in xfh:
        return None
    proto = (x_forwarded_proto or "http").split(",")[0].strip().lower()
    if proto not in ("http", "https"):
        proto = "http"
    host_part = xfh.split(",")[0].strip()
    if not host_part or "/" in host_part or "\\" in host_part:
        return None
    return _normalize_origin(f"{proto}://{host_part}")


def peer_is_trusted_proxy(client_ip: str | None, trusted_proxy_ips: str | None) -> bool:
    """Return True when ``client_ip`` is a direct peer listed in ``trusted_proxy_ips``.

    The list is comma-separated IP addresses or CIDRs, the same shape as
    ``TRUSTED_PROXY_IPS``. Empty, unset, and malformed entries do not match.
    An IPv4-mapped IPv6 peer matches the IPv4 address or network.
    """
    if client_ip is None or trusted_proxy_ips is None:
        return False
    peer_text = client_ip.strip()
    raw = trusted_proxy_ips.strip()
    if not peer_text or not raw:
        return False
    try:
        peer = ipaddress.ip_address(peer_text)
    except ValueError:
        return False
    mapped = getattr(peer, "ipv4_mapped", None)
    if mapped is not None:
        peer = mapped
    for token in raw.split(","):
        item = token.strip()
        if not item:
            continue
        try:
            if "/" in item:
                network = ipaddress.ip_network(item, strict=False)
            else:
                addr = ipaddress.ip_address(item)
                addr_mapped = getattr(addr, "ipv4_mapped", None)
                if addr_mapped is not None:
                    addr = addr_mapped
                network = ipaddress.ip_network(f"{addr}/{addr.max_prefixlen}")
        except ValueError:
            continue
        if peer.version == network.version and peer in network:
            return True
    return False


def is_csrf_safe(
    method: str,
    origin: str | None,
    referer: str | None,
    has_session_cookie: bool,
    allowed_origins: list[str] | None = None,
    request_host: str | None = None,
    x_forwarded_host: str | None = None,
    x_forwarded_proto: str | None = None,
    client_ip: str | None = None,
    trusted_proxy_ips: str | None = None,
    production: bool = False,
) -> bool:
    """Return True if request is safe (no CSRF risk or origin/referer allowed).

    ``trusted_proxy_ips`` is the ``TRUSTED_PROXY_IPS`` value. ``None`` and ``""``
    trust no forwarded host or proto. The function does not read the environment.

    ``production`` is the caller's ``is_production_env()`` result. When true, a
    missing Origin and Referer is not allowed just because the request host is
    localhost or ``testserver``. An allowed Origin, an allowed Referer, or a
    trusted-proxy forwarded origin still passes.
    """
    state_changing = method.upper() in ("POST", "PUT", "PATCH", "DELETE")
    if not state_changing or not has_session_cookie:
        return True
    origins = allowed_origins or DEFAULT_ALLOWED_ORIGINS
    normalized_allowed = {_normalize_origin(o) for o in origins if _normalize_origin(o)}
    # A present Origin is the browser's claim. A hostile or opaque value, including
    # the literal "null", is rejected before Referer or forwarded headers.
    if _origin_header_present(origin):
        req_origin = _normalize_origin(origin)
        return bool(req_origin and req_origin in normalized_allowed)
    req_ref_origin = _origin_from_referer(referer)
    if req_ref_origin and req_ref_origin in normalized_allowed:
        return True
    # Caddy/nginx: upstream Host may be "api:8000" while the browser hit the public
    # origin. Accept the synthetic origin only from a configured proxy, and only when
    # it is in the same list as an Origin check.
    if peer_is_trusted_proxy(client_ip, trusted_proxy_ips):
        syn = _origin_from_forwarded(x_forwarded_host, x_forwarded_proto)
        if syn and syn in normalized_allowed:
            return True
    # Dev and test only. The host comes from the Host header, so a production
    # process can be addressed as localhost or testserver. That is not an allow.
    # Production still accepts an allowed Origin, Referer, or trusted-proxy origin.
    if (
        not production
        and request_host
        and not origin
        and not referer
        and request_host in ("localhost", "127.0.0.1", "::1", "::ffff:127.0.0.1", "testserver")
    ):
        return True
    return False
