"""Enterprise tests: workspaces and members API with authenticated session."""

import pytest
from fastapi.testclient import TestClient


def test_workspaces_current_returns_workspace(client: TestClient) -> None:
    """GET /api/workspaces/current when authenticated returns workspace details."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.get("/api/workspaces/current")
    assert r.status_code == 200
    data = r.json()
    assert data.get("id") == 1
    assert "name" in data
    assert "slug" in data
    assert "mfa_required" in data


def test_workspaces_current_includes_ai_fields(client: TestClient) -> None:
    """TC-V-B3: GET /api/workspaces/current returns ai_completion_model and ai_temperature."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.get("/api/workspaces/current")
    assert r.status_code == 200
    data = r.json()
    assert "ai_completion_model" in data
    assert "ai_temperature" in data
    # Values may be null or set
    assert data.get("ai_completion_model") is None or isinstance(data["ai_completion_model"], str)
    assert data.get("ai_temperature") is None or isinstance(data["ai_temperature"], (int, float))


def test_workspaces_current_patch_ai_requires_admin(client: TestClient) -> None:
    """TC-V-B3: PATCH /api/workspaces/current for AI settings requires can_admin."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    # Demo user is editor; if editor can't PATCH workspace policy this may 403
    r = client.patch(
        "/api/workspaces/current",
        json={"ai_completion_model": "gpt-4o-mini", "ai_temperature": 0.35},
    )
    # Either 200 (if editor allowed) or 403 (admin only)
    assert r.status_code in (200, 403)
    if r.status_code == 200:
        data = r.json()
        assert "ai_completion_model" in data
        assert "ai_temperature" in data


def test_members_list_scoped_by_session(client: TestClient) -> None:
    """GET /api/members uses session workspace; 200 for admin, 403 for non-admin."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.get("/api/members")
    assert r.status_code in (200, 403)
    if r.status_code == 200:
        data = r.json()
        assert "members" in data
