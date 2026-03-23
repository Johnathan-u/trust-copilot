"""TC-V-B5: Questionnaires and exports list APIs. Respect workspace_id and return fields needed for sidebar."""

import pytest
from fastapi.testclient import TestClient


def test_questionnaires_list_requires_auth(client: TestClient) -> None:
    """GET /api/questionnaires/ without auth returns 401."""
    r = client.get("/api/questionnaires/?workspace_id=1")
    assert r.status_code == 401


def test_questionnaires_list_returns_shape(client: TestClient) -> None:
    """GET /api/questionnaires/?workspace_id=... returns list with id, filename, status, parse_metadata (or created_at)."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.get("/api/questionnaires/?workspace_id=1")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    for item in data:
        assert "id" in item
        assert "filename" in item
        assert "status" in item


def test_exports_records_list_requires_auth(client: TestClient) -> None:
    """GET /api/exports/records without auth returns 401."""
    r = client.get("/api/exports/records?workspace_id=1")
    assert r.status_code == 401


def test_exports_records_list_returns_shape(client: TestClient) -> None:
    """GET /api/exports/records?workspace_id=... returns list with id, filename, created_at, questionnaire_id."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.get("/api/exports/records?workspace_id=1")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    for item in data:
        assert "id" in item
        assert "filename" in item
        assert "created_at" in item
        assert "questionnaire_id" in item
