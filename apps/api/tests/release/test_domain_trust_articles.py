"""TC-17-001 gap 1: a trust article always belongs to the caller's workspace.

Create stores the session workspace. A null body workspace_id, an omitted one,
or a workspace_id other than the session's is rejected. Update cannot move the
row or clear its workspace. A public read does not return a published row whose
workspace is null, and a public read that names a workspace does not return
another workspace's article.
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import TrustArticle

_WORKSPACE_DETAIL = "workspace_id must match the current workspace"


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _login_admin(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@trust.local", "password": "a"},
    )
    assert response.status_code == 200, response.text


def _delete_slugs(db: Session, *slugs: str) -> None:
    db.query(TrustArticle).filter(TrustArticle.slug.in_(slugs)).delete(synchronize_session=False)
    db.commit()


def _rows(db: Session, slug: str) -> list[TrustArticle]:
    db.expire_all()
    return db.query(TrustArticle).filter(TrustArticle.slug == slug).all()


def test_create_rejects_null_workspace(client: TestClient, db_session: Session) -> None:
    """POST with workspace_id null does not insert a row."""
    _login_admin(client)
    slug = _slug("null-ws")
    try:
        response = client.post(
            "/api/trust-articles/",
            json={
                "slug": slug,
                "title": "Null workspace",
                "content": "secret",
                "workspace_id": None,
            },
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"] == _WORKSPACE_DETAIL
        assert _rows(db_session, slug) == []
    finally:
        _delete_slugs(db_session, slug)


def test_create_rejects_omitted_workspace(client: TestClient, db_session: Session) -> None:
    """POST that leaves workspace_id out does not store a null workspace."""
    _login_admin(client)
    slug = _slug("omit-ws")
    try:
        response = client.post(
            "/api/trust-articles/",
            json={"slug": slug, "title": "Omitted workspace", "content": "secret"},
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"] == _WORKSPACE_DETAIL
        assert _rows(db_session, slug) == []
    finally:
        _delete_slugs(db_session, slug)


def test_create_rejects_other_workspace(client: TestClient, db_session: Session) -> None:
    """A body workspace_id other than the session workspace is rejected."""
    _login_admin(client)
    slug = _slug("other-ws")
    try:
        response = client.post(
            "/api/trust-articles/",
            json={"slug": slug, "title": "Other workspace", "content": "secret", "workspace_id": 2},
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"] == _WORKSPACE_DETAIL
        assert _rows(db_session, slug) == []
    finally:
        _delete_slugs(db_session, slug)


def test_unauthenticated_read_hides_null_workspace_published(
    client: TestClient, db_session: Session
) -> None:
    """A published row with a null workspace is not returned without a session."""
    slug = _slug("null-published")
    article = TrustArticle(
        workspace_id=None,
        slug=slug,
        title="Null workspace published",
        content="null-workspace-secret",
        published=1,
    )
    db_session.add(article)
    db_session.commit()
    db_session.refresh(article)
    article_id = article.id
    try:
        by_id = client.get(f"/api/trust-articles/{article_id}")
        assert by_id.status_code == 404, by_id.text
        assert "null-workspace-secret" not in by_id.text

        listed = client.get("/api/trust-articles?workspace_id=1&published_only=true")
        assert listed.status_code == 200, listed.text
        assert all(item["id"] != article_id for item in listed.json())
        assert "null-workspace-secret" not in listed.text
    finally:
        db_session.query(TrustArticle).filter(TrustArticle.id == article_id).delete(
            synchronize_session=False
        )
        db_session.commit()


def test_public_get_named_workspace_does_not_return_another(
    client: TestClient, db_session: Session
) -> None:
    """A public read that names a workspace returns only that workspace's article."""
    slug = _slug("ws2-public")
    article = TrustArticle(
        workspace_id=2,
        slug=slug,
        title="Workspace two published",
        content="workspace-two-secret",
        published=1,
    )
    db_session.add(article)
    db_session.commit()
    db_session.refresh(article)
    article_id = article.id
    try:
        wrong = client.get(f"/api/trust-articles/{article_id}?workspace_id=1")
        assert wrong.status_code == 404, wrong.text
        assert "workspace-two-secret" not in wrong.text

        named = client.get(f"/api/trust-articles/{article_id}?workspace_id=2")
        assert named.status_code == 200, named.text
        assert named.json()["workspace_id"] == 2
        assert named.json()["slug"] == slug

        # Direct id lookup of a published in-workspace article stays public.
        direct = client.get(f"/api/trust-articles/{article_id}")
        assert direct.status_code == 200, direct.text
        assert direct.json()["id"] == article_id
    finally:
        db_session.query(TrustArticle).filter(TrustArticle.id == article_id).delete(
            synchronize_session=False
        )
        db_session.commit()


def test_normal_create_and_read_unchanged(client: TestClient, db_session: Session) -> None:
    """A matching workspace_id still creates a published article the caller can read."""
    _login_admin(client)
    slug = _slug("normal")
    try:
        created = client.post(
            "/api/trust-articles/",
            json={
                "slug": slug,
                "title": "Normal article",
                "content": "Visible body",
                "workspace_id": 1,
            },
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["slug"] == slug
        assert body["title"] == "Normal article"
        assert body["workspace_id"] == 1
        assert body["published"] == 1
        article_id = body["id"]

        owned = client.get(f"/api/trust-articles/{article_id}")
        assert owned.status_code == 200, owned.text
        assert owned.json()["workspace_id"] == 1

        client.post("/api/auth/logout")
        public = client.get(f"/api/trust-articles/{article_id}")
        assert public.status_code == 200, public.text
        assert public.json()["slug"] == slug
        named = client.get(f"/api/trust-articles/{article_id}?workspace_id=1")
        assert named.status_code == 200, named.text
        assert named.json()["content"] == "Visible body"
    finally:
        _delete_slugs(db_session, slug)


def test_update_cannot_move_or_clear_workspace(client: TestClient, db_session: Session) -> None:
    """PATCH cannot point an article at another workspace or at null."""
    _login_admin(client)
    slug = _slug("stay")
    try:
        created = client.post(
            "/api/trust-articles/",
            json={"slug": slug, "title": "Stay", "content": "Body", "workspace_id": 1},
        )
        assert created.status_code == 200, created.text
        article_id = created.json()["id"]

        moved = client.patch(f"/api/trust-articles/{article_id}", json={"workspace_id": 2})
        assert moved.status_code == 400, moved.text
        assert moved.json()["detail"] == _WORKSPACE_DETAIL

        cleared = client.patch(f"/api/trust-articles/{article_id}", json={"workspace_id": None})
        assert cleared.status_code == 400, cleared.text
        assert cleared.json()["detail"] == _WORKSPACE_DETAIL

        kept = client.get(f"/api/trust-articles/{article_id}")
        assert kept.status_code == 200, kept.text
        assert kept.json()["workspace_id"] == 1
        assert kept.json()["title"] == "Stay"

        same = client.patch(
            f"/api/trust-articles/{article_id}",
            json={"title": "Stay renamed", "workspace_id": 1},
        )
        assert same.status_code == 200, same.text
        assert same.json()["title"] == "Stay renamed"
        assert same.json()["workspace_id"] == 1
    finally:
        _delete_slugs(db_session, slug)


def test_null_workspace_row_cannot_be_updated_or_deleted(
    client: TestClient, db_session: Session
) -> None:
    """An existing null-workspace row is outside the caller's workspace."""
    slug = _slug("null-row")
    article = TrustArticle(
        workspace_id=None,
        slug=slug,
        title="Orphan",
        content="orphan-secret",
        published=1,
    )
    db_session.add(article)
    db_session.commit()
    db_session.refresh(article)
    article_id = article.id
    try:
        _login_admin(client)
        patched = client.patch(f"/api/trust-articles/{article_id}", json={"title": "Adopted"})
        assert patched.status_code == 403, patched.text
        removed = client.delete(f"/api/trust-articles/{article_id}")
        assert removed.status_code == 403, removed.text

        db_session.expire_all()
        stored = db_session.get(TrustArticle, article_id)
        assert stored is not None
        assert stored.workspace_id is None
        assert stored.title == "Orphan"
    finally:
        db_session.query(TrustArticle).filter(TrustArticle.id == article_id).delete(
            synchronize_session=False
        )
        db_session.commit()
