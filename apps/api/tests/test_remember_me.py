"""Tests for remember-me cookie persistence behaviour.

When remember_me=False (default), the session cookie must NOT have max-age
so the browser treats it as a session cookie deleted on close.

When remember_me=True, the cookie MUST have max-age for cross-restart persistence.
"""

import pytest
from fastapi.testclient import TestClient


def _login(client: TestClient, remember_me: bool):
    return client.post(
        "/api/auth/login",
        json={"email": "demo@trust.local", "password": "j", "remember_me": remember_me},
    )


def _session_cookie(response):
    for cookie in response.cookies.jar:
        if cookie.name == "tc_session":
            return cookie
    return None


def test_login_without_remember_me_is_session_cookie(client: TestClient) -> None:
    """Without remember_me the cookie has no max-age (session-only)."""
    r = _login(client, remember_me=False)
    assert r.status_code == 200
    cookie = _session_cookie(r)
    assert cookie is not None
    assert cookie.expires is None, "Session cookie should have no expires/max-age"


def test_login_with_remember_me_is_persistent_cookie(client: TestClient) -> None:
    """With remember_me the cookie has max-age (persists across restarts)."""
    r = _login(client, remember_me=True)
    assert r.status_code == 200
    cookie = _session_cookie(r)
    assert cookie is not None
    assert cookie.expires is not None, "Persistent cookie must have expires/max-age"


def test_both_paths_return_valid_session(client: TestClient) -> None:
    """Both remember_me variants return a working session."""
    for remember in (False, True):
        r = _login(client, remember_me=remember)
        assert r.status_code == 200
        me = client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == "demo@trust.local"
        client.post("/api/auth/logout")


def test_remember_me_does_not_affect_auth_security(client: TestClient) -> None:
    """Bad password fails regardless of remember_me flag."""
    r = client.post(
        "/api/auth/login",
        json={"email": "demo@trust.local", "password": "wrong", "remember_me": True},
    )
    assert r.status_code == 401


def test_default_login_omits_remember_me_field(client: TestClient) -> None:
    """Omitting remember_me defaults to session cookie (no max-age)."""
    r = client.post(
        "/api/auth/login",
        json={"email": "demo@trust.local", "password": "j"},
    )
    assert r.status_code == 200
    cookie = _session_cookie(r)
    assert cookie is not None
    assert cookie.expires is None
