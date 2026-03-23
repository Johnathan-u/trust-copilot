"""TC-R-B6: Vendor requests API tests."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.password import hash_password
from app.models import User, WorkspaceMember


@pytest.fixture
def admin_user(db_session: Session) -> User:
    """Admin user in workspace 1 for vendor request create."""
    email = "admin-vendor@trust.local"
    user = db_session.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, password_hash=hash_password("a"), display_name="Admin Vendor")
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    mem = db_session.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == 1
    ).first()
    if not mem:
        db_session.add(WorkspaceMember(workspace_id=1, user_id=user.id, role="admin"))
        db_session.commit()
    else:
        mem.role = "admin"
        db_session.commit()
    return user


def test_list_vendor_requests_requires_auth(client: TestClient) -> None:
    """GET /api/vendor-requests without auth returns 401."""
    r = client.get("/api/vendor-requests")
    assert r.status_code == 401


def test_list_vendor_requests_with_session(client: TestClient) -> None:
    """GET /api/vendor-requests with auth returns list."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.get("/api/vendor-requests")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_create_vendor_request_requires_admin(client: TestClient, admin_user: User) -> None:
    """POST /api/vendor-requests requires admin; returns share_url/link_token."""
    client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
    r = client.post(
        "/api/vendor-requests/",
        json={"vendor_email": "vendor@example.com"},
    )
    assert r.status_code == 403

    client.post("/api/auth/login", json={"email": admin_user.email, "password": "a"})
    r2 = client.post(
        "/api/vendor-requests/",
        json={"vendor_email": "vendor@example.com"},
    )
    assert r2.status_code in (200, 201)
    data = r2.json()
    assert data["vendor_email"] == "vendor@example.com"
    assert data["status"] == "sent"
    assert data.get("id") is not None
    assert data.get("workspace_id") == 1
    assert data.get("link_token") or data.get("share_url")


def test_create_vendor_request_with_questionnaire(client: TestClient, admin_user: User) -> None:
    """POST can include optional questionnaire_id."""
    client.post("/api/auth/login", json={"email": admin_user.email, "password": "a"})
    r = client.post(
        "/api/vendor-requests/",
        json={"vendor_email": "v2@example.com", "questionnaire_id": 1},
    )
    assert r.status_code in (200, 201)
    data = r.json()
    assert data["vendor_email"] == "v2@example.com"
    assert data.get("questionnaire_id") == 1
