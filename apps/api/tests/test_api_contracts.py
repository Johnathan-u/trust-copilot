"""Enterprise API contract tests: health, readiness, auth discovery, unauthenticated access."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def test_healthz_returns_ok(client: TestClient) -> None:
    """GET /healthz returns 200 and status ok."""
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_readyz_returns_ready(client: TestClient) -> None:
    """GET /readyz returns 200 and status ready (S3 mocked for test env)."""
    with patch("app.main.StorageClient") as MockStorage:
        MockStorage.return_value.ping.return_value = None
        r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json().get("status") == "ready"


def test_oauth_providers_returns_shape(client: TestClient) -> None:
    """GET /api/auth/oauth/providers returns dict with google, github, microsoft, sso, idme booleans."""
    r = client.get("/api/auth/oauth/providers")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("google"), bool)
    assert isinstance(data.get("github"), bool)
    assert isinstance(data.get("microsoft"), bool)
    assert isinstance(data.get("sso"), bool)
    assert isinstance(data.get("idme"), bool)


def test_oauth_google_returns_404_when_not_configured(client: TestClient) -> None:
    """GET /api/auth/oauth/google returns 404 when OAUTH_GOOGLE_CLIENT_ID is not set."""
    with patch("app.api.routes.auth.get_settings") as m:
        s = m.return_value
        s.oauth_google_client_id = None
        s.oauth_google_client_secret = None
        r = client.get("/api/auth/oauth/google", follow_redirects=False)
    assert r.status_code == 404


def test_oauth_google_redirects_when_configured(client: TestClient) -> None:
    """GET /api/auth/oauth/google returns 302 to Google with signed state when configured."""
    with patch("app.api.routes.auth.get_settings") as m:
        s = m.return_value
        s.oauth_google_client_id = "test-client-id"
        s.oauth_google_client_secret = "test-secret"
        s.app_base_url = "http://localhost:3000"
        s.session_secret = "test-secret"
        r = client.get("/api/auth/oauth/google", follow_redirects=False)
    assert r.status_code == 302
    location = r.headers.get("location", "")
    assert "accounts.google.com" in location
    assert "state=" in location
    # Signed state contains a dot (payload.sig)
    state_part = [p for p in location.split("?")[-1].split("&") if p.startswith("state=")]
    assert len(state_part) == 1
    assert "." in state_part[0]
    assert "oauth_state" in [c.name for c in r.cookies.jar]


def test_me_requires_auth_returns_401(client: TestClient) -> None:
    """GET /api/auth/me without session returns 401."""
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_switch_workspace_requires_auth_returns_401(client: TestClient) -> None:
    """POST /api/auth/switch-workspace without session returns 401."""
    r = client.post("/api/auth/switch-workspace", json={"workspace_id": 1})
    assert r.status_code == 401


def test_documents_list_requires_auth(client: TestClient) -> None:
    """GET /api/documents/ without session returns 401."""
    r = client.get("/api/documents/?workspace_id=1")
    assert r.status_code == 401


def test_questionnaires_list_requires_auth(client: TestClient) -> None:
    """GET /api/questionnaires/ without session returns 401."""
    r = client.get("/api/questionnaires/?workspace_id=1")
    assert r.status_code == 401


def test_workspaces_current_requires_auth(client: TestClient) -> None:
    """GET /api/workspaces/current without session returns 401."""
    r = client.get("/api/workspaces/current")
    assert r.status_code == 401


def test_members_list_requires_auth(client: TestClient) -> None:
    """GET /api/members without session returns 401."""
    r = client.get("/api/members")
    assert r.status_code == 401
