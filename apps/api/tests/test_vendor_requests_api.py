"""TC-R-B6: Vendor requests (Requests page) API tests.

Covers the full outbound request lifecycle:
  create → list → status update → edge cases
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.password import hash_password
from app.models import User, WorkspaceMember
from app.models.vendor_request import VENDOR_REQUEST_STATUSES


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


def _login_admin(client: TestClient, admin_user: User) -> None:
    client.post("/api/auth/login", json={"email": admin_user.email, "password": "a"})


# ── Auth ──────────────────────────────────────────────────────────────────

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
    """POST /api/vendor-requests requires admin; editor gets 403."""
    client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
    r = client.post(
        "/api/vendor-requests/",
        json={"vendor_email": "vendor@example.com"},
    )
    assert r.status_code == 403


# ── Create ────────────────────────────────────────────────────────────────

def test_create_returns_pending_status_and_link(client: TestClient, admin_user: User) -> None:
    """POST creates request with status=pending, link_token, and share_url."""
    _login_admin(client, admin_user)
    r = client.post(
        "/api/vendor-requests/",
        json={"vendor_email": "vendor@example.com"},
    )
    assert r.status_code in (200, 201)
    data = r.json()
    assert data["vendor_email"] == "vendor@example.com"
    assert data["status"] == "pending"
    assert data.get("id") is not None
    assert data.get("workspace_id") == 1
    assert data.get("link_token") is not None
    assert len(data["link_token"]) > 20
    assert data.get("share_url") is not None
    assert data["share_url"].startswith("/vendor-response?token=")
    assert data["link_token"] in data["share_url"]


def test_create_with_questionnaire_id(client: TestClient, admin_user: User) -> None:
    """POST can include optional questionnaire_id."""
    _login_admin(client, admin_user)
    r = client.post(
        "/api/vendor-requests/",
        json={"vendor_email": "v2@example.com", "questionnaire_id": 1},
    )
    assert r.status_code in (200, 201)
    data = r.json()
    assert data["vendor_email"] == "v2@example.com"
    assert data.get("questionnaire_id") == 1


def test_create_with_message(client: TestClient, admin_user: User) -> None:
    """POST can include optional message."""
    _login_admin(client, admin_user)
    r = client.post(
        "/api/vendor-requests/",
        json={
            "vendor_email": "msg@example.com",
            "message": "Please complete the attached questionnaire by EOW.",
        },
    )
    assert r.status_code in (200, 201)
    data = r.json()
    assert data["message"] == "Please complete the attached questionnaire by EOW."
    assert data["status"] == "pending"


def test_create_without_email_fails(client: TestClient, admin_user: User) -> None:
    """POST without vendor_email returns 400 or 422."""
    _login_admin(client, admin_user)
    r = client.post("/api/vendor-requests/", json={"vendor_email": ""})
    assert r.status_code in (400, 422)


def test_create_normalizes_email(client: TestClient, admin_user: User) -> None:
    """Email is lowercased and trimmed."""
    _login_admin(client, admin_user)
    r = client.post(
        "/api/vendor-requests/",
        json={"vendor_email": "  Vendor@EXAMPLE.COM  "},
    )
    assert r.status_code in (200, 201)
    assert r.json()["vendor_email"] == "vendor@example.com"


def test_each_create_gets_unique_token(client: TestClient, admin_user: User) -> None:
    """Two creates produce different link_tokens."""
    _login_admin(client, admin_user)
    r1 = client.post("/api/vendor-requests/", json={"vendor_email": "a@b.com"})
    r2 = client.post("/api/vendor-requests/", json={"vendor_email": "c@d.com"})
    assert r1.json()["link_token"] != r2.json()["link_token"]


# ── List ──────────────────────────────────────────────────────────────────

def test_list_returns_created_requests(client: TestClient, admin_user: User) -> None:
    """Created requests appear in list, ordered newest first."""
    _login_admin(client, admin_user)
    client.post("/api/vendor-requests/", json={"vendor_email": "first@list.com"})
    client.post("/api/vendor-requests/", json={"vendor_email": "second@list.com"})
    r = client.get("/api/vendor-requests")
    assert r.status_code == 200
    items = r.json()
    assert len(items) >= 2
    emails = [i["vendor_email"] for i in items]
    assert "first@list.com" in emails
    assert "second@list.com" in emails


def test_list_does_not_expose_share_url(client: TestClient, admin_user: User) -> None:
    """List endpoint returns link_token but not share_url (only create does)."""
    _login_admin(client, admin_user)
    client.post("/api/vendor-requests/", json={"vendor_email": "nourl@test.com"})
    r = client.get("/api/vendor-requests")
    for item in r.json():
        if item["vendor_email"] == "nourl@test.com":
            assert "link_token" in item
            assert "share_url" not in item
            break


def test_list_response_shape(client: TestClient, admin_user: User) -> None:
    """Each list item has the expected keys for the frontend table."""
    _login_admin(client, admin_user)
    client.post("/api/vendor-requests/", json={"vendor_email": "shape@test.com"})
    r = client.get("/api/vendor-requests")
    items = r.json()
    assert len(items) >= 1
    item = items[0]
    expected_keys = {"id", "workspace_id", "vendor_email", "questionnaire_id", "message", "status", "link_token", "created_at"}
    assert expected_keys <= set(item.keys())


# ── Status update ─────────────────────────────────────────────────────────

def test_update_status_to_in_progress(client: TestClient, admin_user: User) -> None:
    """PATCH transitions pending → in_progress."""
    _login_admin(client, admin_user)
    create = client.post("/api/vendor-requests/", json={"vendor_email": "prog@test.com"})
    req_id = create.json()["id"]
    r = client.patch(f"/api/vendor-requests/{req_id}", json={"status": "in_progress"})
    assert r.status_code == 200
    assert r.json()["status"] == "in_progress"


def test_update_status_to_completed(client: TestClient, admin_user: User) -> None:
    """PATCH transitions pending → completed."""
    _login_admin(client, admin_user)
    create = client.post("/api/vendor-requests/", json={"vendor_email": "done@test.com"})
    req_id = create.json()["id"]
    r = client.patch(f"/api/vendor-requests/{req_id}", json={"status": "completed"})
    assert r.status_code == 200
    assert r.json()["status"] == "completed"


def test_update_status_invalid_rejected(client: TestClient, admin_user: User) -> None:
    """PATCH with invalid status returns 400."""
    _login_admin(client, admin_user)
    create = client.post("/api/vendor-requests/", json={"vendor_email": "inv@test.com"})
    req_id = create.json()["id"]
    r = client.patch(f"/api/vendor-requests/{req_id}", json={"status": "deleted"})
    assert r.status_code == 400


def test_update_nonexistent_request_404(client: TestClient, admin_user: User) -> None:
    """PATCH on missing ID returns 404."""
    _login_admin(client, admin_user)
    r = client.patch("/api/vendor-requests/999999", json={"status": "completed"})
    assert r.status_code == 404


def test_update_requires_admin(client: TestClient, admin_user: User) -> None:
    """PATCH with non-admin session returns 403."""
    _login_admin(client, admin_user)
    create = client.post("/api/vendor-requests/", json={"vendor_email": "auth@test.com"})
    req_id = create.json()["id"]
    client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
    r = client.patch(f"/api/vendor-requests/{req_id}", json={"status": "completed"})
    assert r.status_code == 403


def test_status_persists_across_list(client: TestClient, admin_user: User) -> None:
    """Status change via PATCH is reflected in subsequent GET list."""
    _login_admin(client, admin_user)
    create = client.post("/api/vendor-requests/", json={"vendor_email": "persist@test.com"})
    req_id = create.json()["id"]
    client.patch(f"/api/vendor-requests/{req_id}", json={"status": "completed"})
    r = client.get("/api/vendor-requests")
    hit = next((i for i in r.json() if i["id"] == req_id), None)
    assert hit is not None
    assert hit["status"] == "completed"


# ── Full lifecycle ────────────────────────────────────────────────────────

def test_full_lifecycle_create_update_list(client: TestClient, admin_user: User) -> None:
    """End-to-end: create → verify pending → update in_progress → update completed → list confirms."""
    _login_admin(client, admin_user)

    cr = client.post(
        "/api/vendor-requests/",
        json={"vendor_email": "lifecycle@vendor.com", "message": "Please review"},
    )
    assert cr.status_code in (200, 201)
    data = cr.json()
    req_id = data["id"]
    assert data["status"] == "pending"
    assert data["share_url"].startswith("/vendor-response?token=")

    r1 = client.patch(f"/api/vendor-requests/{req_id}", json={"status": "in_progress"})
    assert r1.json()["status"] == "in_progress"

    r2 = client.patch(f"/api/vendor-requests/{req_id}", json={"status": "completed"})
    assert r2.json()["status"] == "completed"

    listing = client.get("/api/vendor-requests")
    hit = next((i for i in listing.json() if i["id"] == req_id), None)
    assert hit is not None
    assert hit["status"] == "completed"
    assert hit["vendor_email"] == "lifecycle@vendor.com"
    assert hit["message"] == "Please review"
    assert hit["link_token"] is not None


# ── Model statuses match spec ────────────────────────────────────────────

def test_model_statuses_match_spec() -> None:
    """VENDOR_REQUEST_STATUSES = pending, in_progress, completed."""
    assert set(VENDOR_REQUEST_STATUSES) == {"pending", "in_progress", "completed"}
