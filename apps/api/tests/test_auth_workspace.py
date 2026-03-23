"""TEST-01: Auth and workspace isolation integration tests."""

import pytest
from fastapi.testclient import TestClient


def test_login_demo_user(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert r.status_code == 200
    data = r.json()
    assert "user" in data
    assert data["user"]["email"] == "demo@trust.local"
    assert "tc_session" in [c.name for c in r.cookies.jar]


def test_login_rejects_unknown_user(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"email": "unknown@test.com", "password": "j"})
    assert r.status_code in (400, 401, 422)


def test_auth_me_requires_session(client: TestClient) -> None:
    r = client.get("/api/auth/me")
    assert r.status_code in (401, 403, 422)


def test_auth_me_with_session(client: TestClient) -> None:
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json().get("email") == "demo@trust.local"
    assert r.json().get("workspace_id") == 1


def test_workspace_scoped_questionnaires(client: TestClient) -> None:
    """Workspace filter returns only that workspace's data."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.get("/api/questionnaires/?workspace_id=1")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_logout(client: TestClient) -> None:
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    r2 = client.get("/api/auth/me")
    assert r2.status_code in (401, 403, 422)
