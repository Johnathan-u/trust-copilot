"""Wave-3 priority API coverage gaps (P23, P25, P27, P29).

Primary suites live in the files listed in docs/engineering/WAVE3_AUTOMATED_COVERAGE_P23_P29.md.
This module adds focused checks not already asserted elsewhere.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.password import hash_password
from app.models import User, WorkspaceMember


@pytest.fixture
def vendor_admin_ws1(db_session: Session):
    """Use a scoped admin and restore user/member state after the test."""
    user_count = db_session.query(User).count()
    member_count = db_session.query(WorkspaceMember).count()
    user = User(
        email=f"vendor-admin-{uuid.uuid4().hex}@example.com",
        password_hash=hash_password("a"),
        display_name="Synthetic Vendor Admin",
    )
    db_session.add(user)
    db_session.flush()
    user_id = user.id
    db_session.add(WorkspaceMember(workspace_id=1, user_id=user_id, role="admin"))
    db_session.commit()
    try:
        yield user
    finally:
        db_session.rollback()
        db_session.query(WorkspaceMember).filter_by(user_id=user_id).delete(
            synchronize_session=False
        )
        db_session.query(User).filter_by(id=user_id).delete(synchronize_session=False)
        db_session.commit()
        assert db_session.query(User).count() == user_count
        assert db_session.query(WorkspaceMember).count() == member_count


def test_p23_dashboard_cards_requires_session(client: TestClient) -> None:
    client.post("/api/auth/logout")
    r = client.get("/api/dashboard/cards")
    assert r.status_code == 401


def test_p23_dashboard_allowed_routes_requires_session(client: TestClient) -> None:
    client.post("/api/auth/logout")
    r = client.get("/api/dashboard/cards/allowed-routes")
    assert r.status_code == 401


def test_p25_ai_governance_settings_requires_session(client: TestClient) -> None:
    client.post("/api/auth/logout")
    r = client.get("/api/ai-governance/settings")
    assert r.status_code == 401


def test_p27_vendor_request_empty_email_422(client: TestClient, vendor_admin_ws1: User) -> None:
    client.post("/api/auth/login", json={"email": vendor_admin_ws1.email, "password": "a"})
    r = client.post("/api/vendor-requests/", json={"vendor_email": "   "})
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "vendor_email"]


def test_p27_vendor_requests_reviewer_can_list(client: TestClient) -> None:
    """Vendor list uses require_can_review."""
    client.post("/api/auth/login", json={"email": "reviewer@trust.local", "password": "r"})
    r = client.get("/api/vendor-requests")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_p29_editor_cannot_delete_trust_article(client: TestClient) -> None:
    slug = f"wave3-del-{uuid.uuid4().hex[:8]}"
    client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    create = client.post(
        "/api/trust-articles/",
        json={"slug": slug, "title": "Wave3", "content": "", "workspace_id": 1},
    )
    assert create.status_code in (200, 201)
    aid = create.json()["id"]

    client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
    r = client.delete(f"/api/trust-articles/{aid}")
    assert r.status_code == 403

    client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    client.delete(f"/api/trust-articles/{aid}")
