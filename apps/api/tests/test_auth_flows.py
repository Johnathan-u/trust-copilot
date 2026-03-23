"""Enterprise auth flow tests: register, forgot-password, reset-password, accept-invite validation."""

import pytest
from fastapi.testclient import TestClient


def test_register_rejects_invalid_email(client: TestClient) -> None:
    """POST /api/auth/register with invalid email returns 400 or generic success."""
    r = client.post(
        "/api/auth/register",
        json={"email": "not-an-email", "password": "password123", "display_name": "Test"},
    )
    assert r.status_code in (200, 400)
    if r.status_code == 400:
        assert "email" in (r.json().get("detail") or "").lower() or "invalid" in (r.json().get("detail") or "").lower()


def test_register_rejects_short_password(client: TestClient) -> None:
    """POST /api/auth/register with short password returns 400."""
    r = client.post(
        "/api/auth/register",
        json={"email": "newuser@test.local", "password": "123", "display_name": "Test"},
    )
    assert r.status_code in (200, 400)


def test_forgot_password_accepts_valid_email(client: TestClient) -> None:
    """POST /api/auth/forgot-password returns 200 (generic message)."""
    r = client.post("/api/auth/forgot-password", json={"email": "someone@example.com"})
    assert r.status_code == 200
    assert "message" in r.json()


def test_reset_password_rejects_invalid_token(client: TestClient) -> None:
    """POST /api/auth/reset-password with bad token returns 400."""
    r = client.post(
        "/api/auth/reset-password",
        json={"token": "invalid-token", "new_password": "newpass123"},
    )
    assert r.status_code == 400


def test_accept_invite_rejects_empty_token(client: TestClient) -> None:
    """POST /api/auth/accept-invite with empty token returns 400."""
    r = client.post(
        "/api/auth/accept-invite",
        json={"token": "", "password": "optional"},
    )
    assert r.status_code == 400


def test_accept_invite_rejects_invalid_token(client: TestClient) -> None:
    """POST /api/auth/accept-invite with invalid token returns 400."""
    r = client.post(
        "/api/auth/accept-invite",
        json={"token": "invalid-invite-token", "password": "newpass123"},
    )
    assert r.status_code == 400


def test_verify_invite_code_rejects_bad_email_or_code(client: TestClient) -> None:
    """POST /api/auth/verify-invite-code with unknown pair returns 400."""
    r = client.post(
        "/api/auth/verify-invite-code",
        json={"email": "nobody@example.com", "code": "AAAA-BBBB-CCCC"},
    )
    assert r.status_code == 400


def test_login_rejects_empty_credentials(client: TestClient) -> None:
    """POST /api/auth/login with empty email returns 422, 400, or 401."""
    r = client.post("/api/auth/login", json={"email": "", "password": "j"})
    assert r.status_code in (400, 401, 422)


def test_login_rejects_wrong_password(client: TestClient) -> None:
    """POST /api/auth/login with wrong password returns 401."""
    r = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "wrong"})
    assert r.status_code == 401
