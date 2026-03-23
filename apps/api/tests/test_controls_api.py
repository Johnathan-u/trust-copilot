"""TC-R-B2, TC-R-B3: Controls and evidence linking API tests."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.password import hash_password
from app.models import TrustArticle, User, WorkspaceMember


def _unique_slug(prefix: str = "ev") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def admin_user(db_session: Session) -> User:
    """Admin user in workspace 1 for controls CRUD."""
    email = "admin-ctrl@trust.local"
    user = db_session.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, password_hash=hash_password("a"), display_name="Admin Ctrl")
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


def test_list_controls_requires_auth(client: TestClient) -> None:
    """GET /api/controls without auth returns 401."""
    r = client.get("/api/controls")
    assert r.status_code == 401


def test_list_controls_with_session(client: TestClient) -> None:
    """GET /api/controls with auth returns list; optional workspace_id and framework."""
    client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    r = client.get("/api/controls")
    assert r.status_code == 200
    assert isinstance(r.json(), list)

    r2 = client.get("/api/controls?workspace_id=1")
    assert r2.status_code == 200
    assert isinstance(r2.json(), list)

    r3 = client.get("/api/controls?framework=SOC%202")
    assert r3.status_code == 200
    assert isinstance(r3.json(), list)


def test_create_control_requires_admin(client: TestClient, admin_user: User) -> None:
    """POST /api/controls requires admin; editor gets 403."""
    client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
    r = client.post(
        "/api/controls/",
        json={"framework": "SOC 2", "control_id": "CC6.1", "name": "Logical access", "status": "in_review"},
    )
    assert r.status_code == 403

    client.post("/api/auth/login", json={"email": admin_user.email, "password": "a"})
    r2 = client.post(
        "/api/controls/",
        json={"framework": "SOC 2", "control_id": "CC6.1", "name": "Logical access", "status": "in_review"},
    )
    assert r2.status_code in (200, 201)
    data = r2.json()
    assert data["framework"] == "SOC 2"
    assert data["control_id"] == "CC6.1"
    assert data["status"] == "in_review"
    assert data.get("id") is not None
    assert data.get("workspace_id") == 1


def test_patch_and_delete_control(client: TestClient, admin_user: User) -> None:
    """Admin can PATCH and DELETE a control."""
    client.post("/api/auth/login", json={"email": admin_user.email, "password": "a"})
    create = client.post(
        "/api/controls/",
        json={"framework": "ISO 27001", "control_id": "A.9.1", "name": "Access control", "status": "in_review"},
    )
    assert create.status_code in (200, 201)
    cid = create.json()["id"]

    r = client.patch(f"/api/controls/{cid}", json={"status": "implemented", "name": "Updated"})
    assert r.status_code == 200
    assert r.json()["status"] == "implemented"
    assert r.json()["name"] == "Updated"

    r2 = client.delete(f"/api/controls/{cid}")
    assert r2.status_code == 200
    assert r2.json().get("ok") is True

    r3 = client.get("/api/controls")
    assert r3.status_code == 200
    ids = [x["id"] for x in r3.json()]
    assert cid not in ids


def test_list_control_evidence(client: TestClient, admin_user: User, db_session: Session) -> None:
    """GET /api/controls/{id}/evidence returns linked evidence; requires auth."""
    client.post("/api/auth/login", json={"email": admin_user.email, "password": "a"})
    create = client.post(
        "/api/controls/",
        json={"framework": "SOC 2", "control_id": "CC7.1", "status": "in_review"},
    )
    assert create.status_code in (200, 201)
    cid = create.json()["id"]

    r = client.get(f"/api/controls/{cid}/evidence")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert r.json() == []


def test_attach_and_detach_evidence(client: TestClient, admin_user: User, db_session: Session) -> None:
    """POST attach and DELETE detach evidence; requires admin."""
    # Create a trust article to link (unique slug to avoid collision across runs)
    slug = _unique_slug("evidence-art")
    art = TrustArticle(workspace_id=1, slug=slug, title="Evidence Art", content="X", published=1)
    db_session.add(art)
    db_session.commit()
    db_session.refresh(art)

    client.post("/api/auth/login", json={"email": admin_user.email, "password": "a"})
    create = client.post(
        "/api/controls/",
        json={"framework": "SOC 2", "control_id": "CC8.1", "status": "in_review"},
    )
    assert create.status_code in (200, 201)
    cid = create.json()["id"]

    attach = client.post(
        f"/api/controls/{cid}/evidence",
        json={"trust_article_id": art.id},
    )
    assert attach.status_code in (200, 201)
    ev_data = attach.json()
    assert ev_data["control_id"] == cid
    assert ev_data["trust_article_id"] == art.id
    ev_id = ev_data["id"]

    list_ev = client.get(f"/api/controls/{cid}/evidence")
    assert list_ev.status_code == 200
    items = list_ev.json()
    assert len(items) >= 1
    assert any(e["id"] == ev_id for e in items)

    detach = client.delete(f"/api/controls/{cid}/evidence/{ev_id}")
    assert detach.status_code == 200
    assert detach.json().get("ok") is True

    list_after = client.get(f"/api/controls/{cid}/evidence")
    assert list_after.status_code == 200
    assert not any(e["id"] == ev_id for e in list_after.json())
