"""TC-07-004: a present Origin is final, and forwarded headers need a trusted proxy.

These checks call ``is_csrf_safe`` directly. ``CSRFMiddleware`` skips the check when
``TRUST_COPILOT_TESTING=1``, which is how the suite runs, so an HTTP client would not
exercise the production path. The middleware passes the direct peer and
``TRUSTED_PROXY_IPS`` into this function.

``_check`` drops keyword arguments the function does not accept. Before this ticket the
function had no peer argument, so the same file fails on the insecure result instead of
on an unexpected keyword. After the fix the peer arguments are accepted and passed.
"""

import inspect
from pathlib import Path

from app.core.csrf import is_csrf_safe

ALLOWED = ["https://app.example.com"]
REPO_ROOT = Path(__file__).resolve().parents[4]
CADDY_PRODUCTION = REPO_ROOT / "infra" / "caddy" / "Caddyfile.production"

# A peer that is inside the configured proxy network, and one that is not.
PROXY_IP = "10.0.0.8"
OUTSIDER_IP = "203.0.113.10"
PROXY_CIDR = "10.0.0.0/8"


def _check(**overrides: object) -> bool:
    params = {
        "method": "POST",
        "origin": None,
        "referer": None,
        "has_session_cookie": True,
        "allowed_origins": ALLOWED,
        "request_host": "api",
        "x_forwarded_host": None,
        "x_forwarded_proto": None,
        "client_ip": OUTSIDER_IP,
        "trusted_proxy_ips": "",
    }
    params.update(overrides)
    accepted = set(inspect.signature(is_csrf_safe).parameters)
    return is_csrf_safe(**{key: value for key, value in params.items() if key in accepted})


def test_hostile_origin_with_matching_referer_is_rejected() -> None:
    """A hostile Origin stops the check. A Referer of an allowed origin cannot rescue it."""
    assert (
        _check(
            origin="https://evil.example.com",
            referer="https://app.example.com/dashboard",
            request_host="localhost",
            client_ip=PROXY_IP,
            trusted_proxy_ips=PROXY_IP,
            x_forwarded_host="app.example.com",
            x_forwarded_proto="https",
        )
        is False
    )


def test_hostile_origin_with_allowed_forwarded_host_is_rejected() -> None:
    """A trusted proxy's X-Forwarded-Host cannot override a hostile Origin."""
    assert (
        _check(
            origin="https://evil.example.com",
            referer=None,
            client_ip=PROXY_IP,
            trusted_proxy_ips=PROXY_CIDR,
            x_forwarded_host="app.example.com",
            x_forwarded_proto="https",
        )
        is False
    )


def test_origin_null_is_rejected_before_fallbacks() -> None:
    """The literal Origin value ``null`` (any case) is present and is not an allowed origin."""
    for origin in ("null", "NULL", " Null "):
        assert (
            _check(
                origin=origin,
                referer="https://app.example.com/dashboard",
                request_host="testserver",
                client_ip=PROXY_IP,
                trusted_proxy_ips=PROXY_IP,
                x_forwarded_host="app.example.com",
                x_forwarded_proto="https",
            )
            is False
        ), origin


def test_forwarded_headers_from_untrusted_peer_are_ignored() -> None:
    """X-Forwarded-Host/Proto are ignored unless the direct peer is a configured proxy."""
    forwarded = {
        "origin": None,
        "referer": None,
        "x_forwarded_host": "app.example.com",
        "x_forwarded_proto": "https",
    }
    assert _check(**forwarded, client_ip=OUTSIDER_IP, trusted_proxy_ips="") is False
    assert _check(**forwarded, client_ip=PROXY_IP, trusted_proxy_ips=None) is False
    assert _check(**forwarded, client_ip=OUTSIDER_IP, trusted_proxy_ips=PROXY_CIDR) is False
    assert _check(**forwarded, client_ip=PROXY_IP, trusted_proxy_ips="not-an-ip") is False
    assert _check(**forwarded, client_ip=None, trusted_proxy_ips=PROXY_CIDR) is False


def test_forwarded_headers_from_trusted_proxy_are_honoured() -> None:
    """A configured proxy may supply the public origin when Origin and Referer are absent."""
    forwarded = {
        "origin": None,
        "referer": None,
        "request_host": "api",
        "x_forwarded_host": "app.example.com",
        "x_forwarded_proto": "https",
    }
    assert _check(**forwarded, client_ip=PROXY_IP, trusted_proxy_ips=PROXY_IP) is True
    assert _check(**forwarded, client_ip=PROXY_IP, trusted_proxy_ips=PROXY_CIDR) is True
    assert _check(**forwarded, client_ip="::ffff:10.0.0.8", trusted_proxy_ips=PROXY_CIDR) is True
    # The first forwarded host is the one that counts. An allowed later value does not.
    hostile_first = {**forwarded, "x_forwarded_host": "evil.example.com, app.example.com"}
    assert _check(**hostile_first, client_ip=PROXY_IP, trusted_proxy_ips=PROXY_IP) is False


def test_allowed_origin_still_passes() -> None:
    """An allowed Origin passes, including a trailing slash, even when other headers are hostile."""
    assert (
        _check(
            origin="https://app.example.com",
            referer="https://evil.example.com/phish",
            x_forwarded_host="evil.example.com",
            x_forwarded_proto="https",
            client_ip=OUTSIDER_IP,
            trusted_proxy_ips="",
        )
        is True
    )
    assert _check(origin="https://app.example.com/") is True


def test_same_origin_cases_still_pass() -> None:
    """Legitimate requests that omit Origin still pass on the remaining narrow paths."""
    assert (
        _check(
            origin=None,
            referer="https://app.example.com/settings",
            client_ip=OUTSIDER_IP,
            trusted_proxy_ips="",
        )
        is True
    )
    # A blank Origin is not a value, so the Referer fallback still applies.
    assert _check(origin="  ", referer="https://app.example.com/settings") is True
    for host in ("localhost", "127.0.0.1", "::1", "::ffff:127.0.0.1", "testserver"):
        assert (
            _check(
                origin=None,
                referer=None,
                request_host=host,
                x_forwarded_host="evil.example.com",
                x_forwarded_proto="https",
                client_ip=OUTSIDER_IP,
                trusted_proxy_ips="",
            )
            is True
        ), host


def test_non_csrf_requests_still_pass() -> None:
    """GET and a cookieless POST are outside the check, even with a hostile Origin."""
    assert _check(method="GET", origin="https://evil.example.com") is True
    assert _check(origin="null", has_session_cookie=False) is True


def test_production_caddy_overwrites_forwarded_host_and_proto() -> None:
    """Each API upstream replaces client X-Forwarded-Host and X-Forwarded-Proto."""
    text = CADDY_PRODUCTION.read_text(encoding="utf-8")
    blocks = text.split("reverse_proxy api:8000")
    assert len(blocks) > 1
    for block in blocks[1:]:
        body = block.split("reverse_proxy ", 1)[0]
        assert "header_up -X-Forwarded-Host" in body
        assert "header_up X-Forwarded-Host {http.request.host}" in body
        assert "header_up -X-Forwarded-Proto" in body
        assert "header_up X-Forwarded-Proto {http.request.scheme}" in body
        assert "header_up +X-Forwarded-Host" not in body
        assert "header_up +X-Forwarded-Proto" not in body
