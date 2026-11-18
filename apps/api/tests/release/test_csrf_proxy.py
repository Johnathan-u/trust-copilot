"""TC-07-004: a present Origin is final, and forwarded headers need a trusted proxy.

These checks call ``is_csrf_safe`` directly. ``CSRFMiddleware`` skips the check when
``TRUST_COPILOT_TESTING=1``, which is how the suite runs, so an HTTP client would not
exercise the production path. The middleware passes the direct peer and
``TRUSTED_PROXY_IPS`` into this function.

``_check`` drops keyword arguments the function does not accept. Before this ticket the
function had no peer argument, so the same file fails on the insecure result instead of
on an unexpected keyword. After the fix the peer arguments are accepted and passed.

The CORS checks read the lists installed on ``CORSMiddleware`` in ``app.main`` and send
a preflight through Starlette's middleware. A wildcard list allows ``QUERY`` and any
request header. The explicit list does not.
"""

import ast
import inspect
from pathlib import Path

import anyio
import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.core.csrf import is_csrf_safe

ALLOWED = ["https://app.example.com"]
REPO_ROOT = Path(__file__).resolve().parents[4]
CADDY_PRODUCTION = REPO_ROOT / "infra" / "caddy" / "Caddyfile.production"
MAIN_PY = REPO_ROOT / "apps" / "api" / "app" / "main.py"

# Declared route methods, plus OPTIONS for the preflight. No route declares HEAD,
# QUERY, or TRACE. Starlette treats allow_methods=["*"] as every method in
# ALL_METHODS, which includes QUERY and HEAD.
CORS_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
# Headers the web app sets on fetch, plus Authorization, which the Next proxy
# forwards and which bearer clients send. No X-Requested-With, X-* client header,
# or CSRF header is set. Cookie, Origin, and Referer are not preflight headers.
CORS_HEADERS = [
    "Accept",
    "Authorization",
    "Cache-Control",
    "Content-Type",
    "Idempotency-Key",
    "Pragma",
]
ALLOWED_ORIGIN = "https://app.example.com"

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


def _literal_list(tree: ast.Module, node: ast.AST) -> list[str]:
    if isinstance(node, ast.List):
        return [ast.literal_eval(item) for item in node.elts]
    if isinstance(node, ast.Name):
        for stmt in tree.body:
            target = None
            value = None
            if isinstance(stmt, ast.Assign):
                target = stmt.targets[0] if len(stmt.targets) == 1 else None
                value = stmt.value
            elif isinstance(stmt, ast.AnnAssign):
                target = stmt.target
                value = stmt.value
            if isinstance(target, ast.Name) and target.id == node.id and value is not None:
                return [ast.literal_eval(item) for item in value.elts]
    raise AssertionError(ast.dump(node))


def _cors_from_main() -> tuple[list[str], list[str], bool]:
    """Return the methods, headers, and credentials flag installed in ``app.main``."""
    tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
    found: tuple[list[str], list[str], bool] | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "add_middleware":
            continue
        middleware = node.args[0]
        if not isinstance(middleware, ast.Name) or middleware.id != "CORSMiddleware":
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords}
        found = (
            _literal_list(tree, kwargs["allow_methods"]),
            _literal_list(tree, kwargs["allow_headers"]),
            ast.literal_eval(kwargs["allow_credentials"]),
        )
    if found is None:
        raise AssertionError("CORSMiddleware is not installed in app.main")
    return found


async def _ping(request):  # noqa: ARG001
    return PlainTextResponse("ok")


def _preflight(origin: str, method: str, request_headers: str) -> httpx.Response:
    methods, headers, credentials = _cors_from_main()
    app = Starlette(
        routes=[Route("/api/ping", _ping)],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=[ALLOWED_ORIGIN],
                allow_credentials=credentials,
                allow_methods=methods,
                allow_headers=headers,
            )
        ],
    )
    transport = httpx.ASGITransport(app=app)

    async def _send() -> httpx.Response:
        async with httpx.AsyncClient(transport=transport, base_url="http://cors.test") as client:
            return await client.options(
                "/api/ping",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": method,
                    "Access-Control-Request-Headers": request_headers,
                },
            )

    return anyio.run(_send)


def test_cors_lists_match_the_routes_and_client_headers() -> None:
    """The installed lists are the route methods and the headers clients send."""
    methods, headers, credentials = _cors_from_main()
    assert methods == CORS_METHODS
    assert headers == CORS_HEADERS
    assert credentials is True
    assert "*" not in methods
    assert "*" not in headers


def test_cors_preflight_allows_origin_method_and_header() -> None:
    """An allowed origin, a used method, and a client header pass the preflight."""
    response = _preflight(
        ALLOWED_ORIGIN,
        "POST",
        "content-type, idempotency-key, authorization",
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    allow_methods = {
        item.strip() for item in response.headers["access-control-allow-methods"].split(",")
    }
    assert "POST" in allow_methods
    allow_headers = {
        item.strip().lower() for item in response.headers["access-control-allow-headers"].split(",")
    }
    assert {"content-type", "idempotency-key", "authorization"} <= allow_headers


def test_cors_preflight_rejects_disallowed_method() -> None:
    """QUERY is inside Starlette's ``*`` expansion and outside the route methods."""
    response = _preflight(ALLOWED_ORIGIN, "QUERY", "content-type")
    assert response.status_code == 400
    assert "method" in response.text
    allowed = {item.strip() for item in response.headers["access-control-allow-methods"].split(",")}
    assert "QUERY" not in allowed


def test_cors_preflight_rejects_disallowed_header() -> None:
    """A header the web app and API clients do not send is not allowed."""
    response = _preflight(ALLOWED_ORIGIN, "POST", "x-not-a-client-header")
    assert response.status_code == 400
    assert "headers" in response.text


def test_cors_preflight_disallowed_origin_has_no_acao() -> None:
    """An origin outside the allow-list gets no Access-Control-Allow-Origin header."""
    response = _preflight("https://evil.example.com", "POST", "content-type")
    assert "access-control-allow-origin" not in response.headers


def test_production_localhost_fallback_is_rejected() -> None:
    """In production, Host localhost or testserver does not replace Origin or Referer.

    The host is the request Host header. A production process can receive
    ``localhost`` or ``testserver`` from a direct peer, so the fallback is not
    test-only. Dev and test still allow it (``production`` omitted or false).
    """
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
                production=True,
            )
            is False
        ), host
    assert (
        _check(
            origin=None,
            referer=None,
            request_host="localhost",
            client_ip=OUTSIDER_IP,
            trusted_proxy_ips="",
            production=False,
        )
        is True
    )


def test_production_still_accepts_origin_referer_and_trusted_proxy() -> None:
    """Closing the host fallback leaves the three allow paths #300 already has."""
    assert (
        _check(
            origin="https://app.example.com",
            request_host="localhost",
            production=True,
        )
        is True
    )
    assert (
        _check(
            origin=None,
            referer="https://app.example.com/settings",
            request_host="testserver",
            production=True,
        )
        is True
    )
    assert (
        _check(
            origin=None,
            referer=None,
            request_host="api",
            x_forwarded_host="app.example.com",
            x_forwarded_proto="https",
            client_ip=PROXY_IP,
            trusted_proxy_ips=PROXY_IP,
            production=True,
        )
        is True
    )


def test_csrf_middleware_passes_is_production_env() -> None:
    """The middleware detects production with ``is_production_env()``, not a new check."""
    text = MAIN_PY.read_text(encoding="utf-8")
    body = text.split("class CSRFMiddleware", 1)[1].split("class GlobalRateLimitMiddleware", 1)[0]
    assert "production=is_production_env()" in body
