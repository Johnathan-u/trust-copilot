"""Wave-2 priority API coverage (P13 fragment + P19 fragment).

Full mapping for P13–P21 lives in docs/engineering/WAVE2_AUTOMATED_COVERAGE_P13_P21.md.

This module fills gaps not covered elsewhere:
- P13: /api/members/api-keys (create, list, revoke) — not exercised in phase_a/phase_b.
- P19: GET /api/compliance/gaps — list endpoint (scan-and-notify is in test_notification_fire_points).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session


def _compliance_tables_exist(session: Session) -> bool:
    try:
        session.execute(text("SELECT 1 FROM workspace_controls LIMIT 1"))
        return True
    except Exception:
        return False


# --- P13: API keys (require can_admin) ---


def test_p13_api_keys_list_requires_auth(client: TestClient) -> None:
    r = client.get("/api/members/api-keys")
    assert r.status_code == 401


def test_p13_api_keys_create_forbidden_for_editor(client: TestClient) -> None:
    client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
    r = client.post("/api/members/api-keys", json={"label": "wave2", "role": "editor"})
    assert r.status_code == 403


def test_p13_api_keys_admin_create_list_revoke(client: TestClient) -> None:
    """POST returns raw key once; GET does not; DELETE revokes."""
    client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    create = client.post(
        "/api/members/api-keys",
        json={"label": "wave2-ci-key", "role": "reviewer"},
    )
    assert create.status_code == 200
    body = create.json()
    assert body.get("id") is not None
    assert body.get("role") == "reviewer"
    assert body.get("label") == "wave2-ci-key"
    assert isinstance(body.get("key"), str) and len(body.get("key", "")) > 20
    kid = body["id"]

    listed = client.get("/api/members/api-keys")
    assert listed.status_code == 200
    keys = listed.json().get("api_keys", [])
    row = next((k for k in keys if k["id"] == kid), None)
    assert row is not None
    assert "key" not in row
    assert row.get("role") == "reviewer"

    deleted = client.delete(f"/api/members/api-keys/{kid}")
    assert deleted.status_code == 200
    assert deleted.json().get("ok") is True

    listed2 = client.get("/api/members/api-keys")
    assert listed2.status_code == 200
    ids = {k["id"] for k in listed2.json().get("api_keys", [])}
    assert kid not in ids


def test_p13_api_keys_invalid_role_400(client: TestClient) -> None:
    client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    r = client.post("/api/members/api-keys", json={"label": "bad", "role": "superuser"})
    assert r.status_code == 400


# --- P19: compliance gaps list ---


def test_p19_compliance_gaps_list_requires_auth(client: TestClient) -> None:
    r = client.get("/api/compliance/gaps")
    assert r.status_code == 401


def test_p19_compliance_gaps_list_authenticated(client: TestClient, db_session: Session) -> None:
    """Reviewer can list gaps (require_can_review)."""
    if not _compliance_tables_exist(db_session):
        pytest.skip("Compliance tables missing: run alembic upgrade head on test DB")
    client.post("/api/auth/login", json={"email": "reviewer@trust.local", "password": "r"})
    r = client.get("/api/compliance/gaps")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, dict)
    assert "gaps" in data
    assert "questionnaire_evidence_gaps" in data
    assert isinstance(data["gaps"], list)
    assert isinstance(data["questionnaire_evidence_gaps"], list)
