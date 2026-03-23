"""TEST-01: Auth and workspace isolation integration tests."""

import pytest
from fastapi.testclient import TestClient


def test_login_demo_user_returns_session(client: TestClient) -> None:
    """Login with demo user returns session cookie."""
    r = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert r.status_code == 200
    data = r.json()
    assert "user" in data
    assert data["user"]["email"] == "demo@trust.local"
    assert "workspace_id" in data
    assert data["workspace_id"] == 1
    assert "tc_session" in [c.name for c in r.cookies.jar]


def test_logout_clears_session(client: TestClient) -> None:
    """Logout clears session cookie; /auth/me then returns 401."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    assert r.json().get("ok") is True
    r2 = client.get("/api/auth/me")
    assert r2.status_code == 401


def test_auth_me_returns_user_when_authenticated(client: TestClient) -> None:
    """GET /auth/me returns user when session cookie is valid."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    data = r.json()
    assert data.get("email") == "demo@trust.local"
    assert data.get("workspace_id") == 1
    assert "display_name" in data


def test_documents_list_scoped_by_workspace(client: TestClient, test_workspace: dict) -> None:
    """Documents list is filtered by workspace_id query param. Requires session."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    workspace_id = test_workspace["id"]
    r = client.get(f"/api/documents/?workspace_id={workspace_id}")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    for doc in r.json():
        assert doc.get("id") is not None
        assert "filename" in doc


def test_questionnaires_list_scoped_by_workspace(client: TestClient, test_workspace: dict) -> None:
    """Questionnaires list is filtered by workspace_id query param. Requires session."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    workspace_id = test_workspace["id"]
    r = client.get(f"/api/questionnaires/?workspace_id={workspace_id}")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    for qnr in r.json():
        assert qnr.get("id") is not None
        assert "filename" in qnr
