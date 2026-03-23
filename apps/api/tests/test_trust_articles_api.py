"""TC-V-B1: Trust articles API verification. GET/POST/PATCH/DELETE with workspace scoping and require_can_admin for write."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.password import hash_password
from app.models import User, WorkspaceMember


def _unique_slug(prefix: str = "article") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def admin_user(db_session: Session) -> User:
    """Create an admin user in workspace 1."""
    email = "admin-tc@trust.local"
    user = db_session.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            email=email,
            password_hash=hash_password("a"),
            display_name="Admin TC",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    mem = (
        db_session.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == 1)
        .first()
    )
    if not mem:
        mem = WorkspaceMember(workspace_id=1, user_id=user.id, role="admin")
        db_session.add(mem)
        db_session.commit()
    else:
        mem.role = "admin"
        db_session.commit()
    return user


def test_list_trust_articles_no_auth(client: TestClient) -> None:
    """GET /api/trust-articles without auth returns 401 unless published_only + workspace_id."""
    r = client.get("/api/trust-articles")
    assert r.status_code == 401

    r2 = client.get("/api/trust-articles?workspace_id=1")
    assert r2.status_code == 401

    r3 = client.get("/api/trust-articles?workspace_id=1&published_only=true")
    assert r3.status_code == 200
    assert isinstance(r3.json(), list)


def test_create_trust_article_requires_auth(client: TestClient) -> None:
    """POST /api/trust-articles without auth returns 401."""
    r = client.post(
        "/api/trust-articles/",
        json={"slug": "test-slug", "title": "Test", "content": "Body", "workspace_id": 1},
    )
    assert r.status_code == 401


def test_create_trust_article_requires_admin(
    client: TestClient, admin_user: User, db_session: Session
) -> None:
    """Editor cannot create; admin can."""
    from app.models import WorkspaceMember

    # Editor user cannot create
    client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
    r = client.post(
        "/api/trust-articles/",
        json={"slug": _unique_slug("editor-blocked"), "title": "X", "content": "", "workspace_id": 1},
    )
    assert r.status_code == 403

    # Admin can create
    slug = _unique_slug("tc-v-b1")
    client.post("/api/auth/login", json={"email": "admin-tc@trust.local", "password": "a"})
    r2 = client.post(
        "/api/trust-articles/",
        json={"slug": slug, "title": "TC-V-B1", "content": "Content", "workspace_id": 1},
    )
    assert r2.status_code in (200, 201)
    data = r2.json()
    assert data["slug"] == slug
    assert data["title"] == "TC-V-B1"
    assert data["workspace_id"] == 1
    assert data.get("id") is not None
    assert "created_at" in data


def test_get_trust_article_by_id(client: TestClient, admin_user: User) -> None:
    """GET /api/trust-articles/{id} returns article; no auth required."""
    slug = _unique_slug("get-by-id")
    client.post("/api/auth/login", json={"email": "admin-tc@trust.local", "password": "a"})
    create = client.post(
        "/api/trust-articles/",
        json={"slug": slug, "title": "Get By Id", "content": "C", "workspace_id": 1},
    )
    assert create.status_code in (200, 201)
    aid = create.json()["id"]

    # Get without auth (list/get are public)
    r = client.get(f"/api/trust-articles/{aid}")
    assert r.status_code == 200
    assert r.json()["slug"] == slug

    r404 = client.get("/api/trust-articles/999999")
    assert r404.status_code == 404


def test_duplicate_slug_rejected(client: TestClient, admin_user: User) -> None:
    """Creating another article with same slug returns 400."""
    slug = _unique_slug("unique")
    client.post("/api/auth/login", json={"email": "admin-tc@trust.local", "password": "a"})
    client.post(
        "/api/trust-articles/",
        json={"slug": slug, "title": "First", "content": "", "workspace_id": 1},
    )
    r2 = client.post(
        "/api/trust-articles/",
        json={"slug": slug, "title": "Second", "content": "", "workspace_id": 1},
    )
    assert r2.status_code == 400
    assert "already exists" in (r2.json().get("detail") or "").lower()


def test_patch_and_delete_trust_article(client: TestClient, admin_user: User) -> None:
    """Admin can PATCH and DELETE; response shapes are correct."""
    slug = _unique_slug("patch-delete")
    client.post("/api/auth/login", json={"email": "admin-tc@trust.local", "password": "a"})
    create = client.post(
        "/api/trust-articles/",
        json={"slug": slug, "title": "Original", "content": "X", "workspace_id": 1},
    )
    assert create.status_code in (200, 201)
    aid = create.json()["id"]

    r = client.patch(
        f"/api/trust-articles/{aid}",
        json={"title": "Updated", "content": "Y"},
    )
    assert r.status_code == 200
    assert r.json()["title"] == "Updated"
    assert r.json()["content"] == "Y"

    r2 = client.delete(f"/api/trust-articles/{aid}")
    assert r2.status_code == 200
    assert r2.json().get("ok") is True

    get_after = client.get(f"/api/trust-articles/{aid}")
    assert get_after.status_code == 404


def test_patch_duplicate_slug_rejected(client: TestClient, admin_user: User) -> None:
    """PATCH to existing slug of another article returns 400."""
    slug_a = _unique_slug("slug-a")
    slug_b = _unique_slug("slug-b")
    client.post("/api/auth/login", json={"email": "admin-tc@trust.local", "password": "a"})
    client.post(
        "/api/trust-articles/",
        json={"slug": slug_a, "title": "A", "content": "", "workspace_id": 1},
    )
    create2 = client.post(
        "/api/trust-articles/",
        json={"slug": slug_b, "title": "B", "content": "", "workspace_id": 1},
    )
    assert create2.status_code in (200, 201)
    bid = create2.json()["id"]

    r = client.patch(f"/api/trust-articles/{bid}", json={"slug": slug_a})
    assert r.status_code == 400
    assert "already exists" in (r.json().get("detail") or "").lower()


def test_list_trust_articles_policy_only(client: TestClient, admin_user: User) -> None:
    """GET /api/trust-articles?policy_only=true returns only articles with is_policy (TC-R-B5)."""
    slug = _unique_slug("policy-art")
    client.post("/api/auth/login", json={"email": "admin-tc@trust.local", "password": "a"})
    client.post(
        "/api/trust-articles/",
        json={"slug": slug, "title": "Policy Article", "content": "Policy text", "workspace_id": 1, "is_policy": True},
    )
    r = client.get("/api/trust-articles?workspace_id=1&policy_only=true")
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    assert all(item.get("is_policy") for item in items)
    slugs = [a["slug"] for a in items]
    assert slug in slugs


def test_acknowledge_policy_requires_auth(client: TestClient, admin_user: User) -> None:
    """POST /api/trust-articles/{id}/acknowledge requires auth (TC-R-B5)."""
    slug = _unique_slug("ack-pol")
    client.post("/api/auth/login", json={"email": "admin-tc@trust.local", "password": "a"})
    create = client.post(
        "/api/trust-articles/",
        json={"slug": slug, "title": "Ack Policy", "content": "C", "workspace_id": 1, "is_policy": True},
    )
    assert create.status_code in (200, 201)
    aid = create.json()["id"]

    client.post("/api/auth/logout")
    r = client.post(f"/api/trust-articles/{aid}/acknowledge")
    assert r.status_code == 401

    client.post("/api/auth/login", json={"email": "admin-tc@trust.local", "password": "a"})
    r2 = client.post(f"/api/trust-articles/{aid}/acknowledge")
    assert r2.status_code == 200
    assert r2.json().get("ok") is True
    assert "acknowledged_at" in r2.json()


def test_acknowledge_policy_rejects_non_policy(client: TestClient, admin_user: User) -> None:
    """POST acknowledge on article with is_policy=False returns 400 (TC-R-B5)."""
    slug = _unique_slug("non-pol")
    client.post("/api/auth/login", json={"email": "admin-tc@trust.local", "password": "a"})
    create = client.post(
        "/api/trust-articles/",
        json={"slug": slug, "title": "Not Policy", "content": "C", "workspace_id": 1, "is_policy": False},
    )
    assert create.status_code in (200, 201)
    aid = create.json()["id"]

    r = client.post(f"/api/trust-articles/{aid}/acknowledge")
    assert r.status_code == 400
    assert "not marked as a policy" in (r.json().get("detail") or "").lower()


def test_policy_acknowledgments_list(client: TestClient, admin_user: User) -> None:
    """GET /api/trust-articles/policy-acknowledgments requires auth; returns acknowledged_article_ids (TC-R-B5)."""
    r_anon = client.get("/api/trust-articles/policy-acknowledgments")
    assert r_anon.status_code == 401

    client.post("/api/auth/login", json={"email": "admin-tc@trust.local", "password": "a"})
    r = client.get("/api/trust-articles/policy-acknowledgments")
    assert r.status_code == 200
    data = r.json()
    assert "acknowledged_article_ids" in data
    assert isinstance(data["acknowledged_article_ids"], list)
