"""Tests for CSRF trusted-origin validation (SEC-201). Ensures allowed/disallowed origins behave correctly."""

import pytest

from app.core.csrf import is_csrf_safe


def test_csrf_safe_ipv6_loopback_origin_allowed() -> None:
    """Browsers may send Origin http://[::1]:3000; must match DEFAULT_ALLOWED_ORIGINS."""
    allowed = [
        "http://localhost:3000",
        "http://[::1]:3000",
    ]
    assert is_csrf_safe(
        "POST",
        origin="http://[::1]:3000",
        referer=None,
        has_session_cookie=True,
        allowed_origins=allowed,
    ) is True


def test_csrf_safe_allowed_origin_with_custom_port() -> None:
    """Origin matching an allowed list (e.g. FRONTEND_URL on port 3003) is accepted."""
    allowed = ["http://localhost:3003", "https://app.example.com"]
    assert is_csrf_safe(
        "POST",
        origin="http://localhost:3003",
        referer=None,
        has_session_cookie=True,
        allowed_origins=allowed,
    ) is True
    assert is_csrf_safe(
        "POST",
        origin="http://localhost:3003/",
        referer=None,
        has_session_cookie=True,
        allowed_origins=allowed,
    ) is True


def test_csrf_safe_referer_allowed() -> None:
    """Referer origin matching allowed list is accepted when Origin is missing."""
    allowed = ["http://localhost:3003"]
    assert is_csrf_safe(
        "POST",
        origin=None,
        referer="http://localhost:3003/login",
        has_session_cookie=True,
        allowed_origins=allowed,
    ) is True


def test_csrf_safe_disallowed_origin_rejected() -> None:
    """Origin not in allowed list is rejected (no cookie = not checked; with cookie = rejected)."""
    allowed = ["http://localhost:3000"]
    assert is_csrf_safe(
        "POST",
        origin="http://localhost:3003",
        referer=None,
        has_session_cookie=True,
        allowed_origins=allowed,
    ) is False
    assert is_csrf_safe(
        "POST",
        origin="https://evil.example.com",
        referer=None,
        has_session_cookie=True,
        allowed_origins=allowed,
    ) is False


def test_csrf_safe_get_ignored() -> None:
    """GET is not state-changing; no origin check."""
    assert is_csrf_safe(
        "GET",
        origin=None,
        referer=None,
        has_session_cookie=True,
        allowed_origins=["http://localhost:3000"],
    ) is True


def test_csrf_safe_no_cookie_ignored() -> None:
    """No session cookie means no CSRF origin check."""
    assert is_csrf_safe(
        "POST",
        origin="http://evil.example.com",
        referer=None,
        has_session_cookie=False,
        allowed_origins=["http://localhost:3000"],
    ) is True


def test_csrf_safe_x_forwarded_host_matches_trusted() -> None:
    """Behind Caddy/nginx: X-Forwarded-Host + Proto can match trusted list (browser Host preserved)."""
    allowed = ["http://localhost:3000"]
    assert is_csrf_safe(
        "POST",
        origin=None,
        referer=None,
        has_session_cookie=True,
        allowed_origins=allowed,
        request_host="api",
        x_forwarded_host="localhost:3000",
        x_forwarded_proto="http",
    ) is True


def test_csrf_safe_x_forwarded_host_not_trusted_rejected() -> None:
    assert is_csrf_safe(
        "POST",
        origin=None,
        referer=None,
        has_session_cookie=True,
        allowed_origins=["http://localhost:3000"],
        request_host="api",
        x_forwarded_host="evil.example.com",
        x_forwarded_proto="http",
    ) is False
