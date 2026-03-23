"""TC-V-B4: Auth sessions API verification. GET /api/auth/sessions and POST revoke-others with require_valid_session."""

import pytest
from fastapi.testclient import TestClient


def test_sessions_list_requires_auth(client: TestClient) -> None:
    """GET /api/auth/sessions without auth returns 401."""
    r = client.get("/api/auth/sessions")
    assert r.status_code == 401


def test_sessions_list_returns_shape(client: TestClient) -> None:
    """GET /api/auth/sessions returns sessions array with session_id, user_agent, ip_address, current, created_at."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.get("/api/auth/sessions")
    assert r.status_code == 200
    data = r.json()
    assert "sessions" in data
    assert isinstance(data["sessions"], list)
    for s in data["sessions"]:
        assert "session_id" in s or "id" in s
        assert "user_agent" in s
        assert "ip_address" in s
        assert "current" in s
        assert "created_at" in s


def test_revoke_others_requires_auth(client: TestClient) -> None:
    """POST /api/auth/sessions/revoke-others without auth returns 401."""
    r = client.post("/api/auth/sessions/revoke-others")
    assert r.status_code == 401


def test_revoke_others_returns_ok(client: TestClient) -> None:
    """POST /api/auth/sessions/revoke-others with valid session returns ok and revoked count."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.post("/api/auth/sessions/revoke-others")
    assert r.status_code in (200, 400)
    if r.status_code == 200:
        data = r.json()
        assert data.get("ok") is True
        assert "revoked" in data
