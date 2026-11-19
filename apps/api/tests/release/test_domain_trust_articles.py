"""TC-17-001: workspace on create, versioned publish, acknowledgment, retry.

TC-17-001b: acknowledging a policy that has no published version returns 400
and does not insert or approve a trust_article_versions row.

Gap 1: create stores the session workspace. A null, omitted, or different body
workspace_id is rejected. A public read does not return a null workspace.

Remaining gaps: publishing stores an immutable version and readers see that
version; an acknowledgment is bound to the user, workspace, and version, and
unpublish or a new version revokes it; a create retried with the same
Idempotency-Key returns the same article.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import PolicyAcknowledgment, TrustArticle, TrustArticleVersion, User

_WORKSPACE_DETAIL = "workspace_id must match the current workspace"
_NO_PUBLISHED_POLICY = "Article has no published policy version"


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


def _idempotency_header(name: str) -> dict[str, str]:
    return {"Idempotency-Key": name}


def _acknowledge(client: TestClient, article_id: int, version_id: int):
    return client.post(
        f"/api/trust-articles/{article_id}/acknowledge",
        json={"article_version_id": version_id},
    )


def _login(client: TestClient, email: str, password: str) -> None:
    client.post("/api/auth/logout")
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def _version_count(db: Session, article_id: int) -> int:
    db.expire_all()
    return (
        db.query(TrustArticleVersion)
        .filter(TrustArticleVersion.trust_article_id == article_id)
        .count()
    )


def _next_version_id() -> int:
    """The id the next trust_article_versions insert would receive.

    A member who sends this id must still be refused. On the unfixed path,
    approve_current_draft assigns it and the acknowledge then commits.
    """
    fresh = SessionLocal()
    try:
        row = fresh.execute(
            text("SELECT last_value, is_called FROM trust_article_versions_id_seq")
        ).one()
    finally:
        fresh.rollback()
        fresh.close()
    last = int(row.last_value)
    return last if not row.is_called else last + 1


def _legacy_policy(db: Session, slug: str, *, published_version_id: int | None) -> int:
    article = TrustArticle(
        workspace_id=1,
        slug=slug,
        title="Legacy policy",
        content="draft that must not become a version",
        published=1,
        is_policy=True,
        published_version_id=published_version_id,
    )
    db.add(article)
    db.commit()
    db.refresh(article)
    return int(article.id)


def _delete_idempotency(db: Session, *keys: str) -> None:
    for key in keys:
        db.execute(
            text("DELETE FROM idempotency_keys WHERE idempotency_key LIKE :prefix"),
            {"prefix": f"%{key}"},
        )
    db.commit()


def test_readers_see_the_published_version_not_the_draft(
    client: TestClient, db_session: Session
) -> None:
    """A draft edit does not change the public article. The version row stays put."""
    _login_admin(client)
    slug = _slug("versioned")
    try:
        created = client.post(
            "/api/trust-articles/",
            json={
                "slug": slug,
                "title": "Approved title",
                "content": "approved text",
                "workspace_id": 1,
                "published": 1,
            },
        )
        assert created.status_code == 200, created.text
        body = created.json()
        article_id = body["id"]
        assert body["published_version"] == 1
        version_id = body["published_version_id"]
        assert isinstance(version_id, int)

        drafted = client.patch(
            f"/api/trust-articles/{article_id}",
            json={"title": "Draft title", "content": "draft text"},
        )
        assert drafted.status_code == 200, drafted.text
        assert drafted.json()["title"] == "Draft title"
        assert drafted.json()["content"] == "draft text"
        assert drafted.json()["published_version_id"] == version_id
        assert drafted.json()["published_title"] == "Approved title"
        assert drafted.json()["published_content"] == "approved text"

        client.post("/api/auth/logout")
        public = client.get(f"/api/trust-articles/{article_id}")
        assert public.status_code == 200, public.text
        assert public.json()["title"] == "Approved title"
        assert public.json()["content"] == "approved text"
        assert public.json()["published_version"] == 1
        named = client.get(f"/api/trust-articles/{article_id}?workspace_id=1")
        assert named.status_code == 200, named.text
        assert named.json()["content"] == "approved text"

        listed = client.get("/api/trust-articles?workspace_id=1&published_only=true")
        assert listed.status_code == 200, listed.text
        match = [item for item in listed.json() if item["id"] == article_id]
        assert len(match) == 1
        assert match[0]["content"] == "approved text"
        assert match[0]["title"] == "Approved title"

        stored = db_session.execute(
            text("SELECT title, content FROM trust_article_versions WHERE id = :id"),
            {"id": version_id},
        ).one()
        assert stored == ("Approved title", "approved text")
        db_session.rollback()
        with pytest.raises(Exception):
            db_session.execute(
                text("UPDATE trust_article_versions SET title = 'rewritten' WHERE id = :id"),
                {"id": version_id},
            )
            db_session.commit()
        db_session.rollback()
        fresh = SessionLocal()
        try:
            again = fresh.execute(
                text("SELECT title, content FROM trust_article_versions WHERE id = :id"),
                {"id": version_id},
            ).one()
        finally:
            fresh.close()
        assert again == ("Approved title", "approved text")
    finally:
        _delete_slugs(db_session, slug)


def test_new_version_and_unpublish_revoke_the_acknowledgment(
    client: TestClient, db_session: Session
) -> None:
    """An acknowledgment matches one published version. A new version or unpublish revokes it."""
    _login_admin(client)
    slug = _slug("ack-version")
    try:
        created = client.post(
            "/api/trust-articles/",
            json={
                "slug": slug,
                "title": "Policy v1",
                "content": "version one",
                "workspace_id": 1,
                "is_policy": True,
            },
        )
        assert created.status_code == 200, created.text
        article_id = created.json()["id"]
        first_version = created.json()["published_version_id"]

        first = _acknowledge(client, article_id, first_version)
        assert first.status_code == 200, first.text
        assert first.json()["ok"] is True
        assert first.json()["article_version_id"] == first_version
        assert first.json()["workspace_id"] == 1
        first_at = first.json()["acknowledged_at"]

        again = _acknowledge(client, article_id, first_version)
        assert again.status_code == 200, again.text
        assert again.json()["acknowledged_at"] == first_at

        listed = client.get("/api/trust-articles/policy-acknowledgments")
        assert article_id in listed.json()["acknowledged_article_ids"]

        revised = client.patch(
            f"/api/trust-articles/{article_id}",
            json={"content": "version two", "published": 1},
        )
        assert revised.status_code == 200, revised.text
        second_version = revised.json()["published_version_id"]
        assert second_version != first_version
        assert revised.json()["published_version"] == 2
        assert revised.json()["published_content"] == "version two"

        client.post("/api/auth/logout")
        public = client.get(f"/api/trust-articles/{article_id}?workspace_id=1")
        assert public.status_code == 200, public.text
        assert public.json()["content"] == "version two"
        assert public.json()["published_version_id"] == second_version

        _login_admin(client)
        after_edit = client.get("/api/trust-articles/policy-acknowledgments")
        assert article_id not in after_edit.json()["acknowledged_article_ids"]

        stale = _acknowledge(client, article_id, first_version)
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"] == "article_version_id is not the published version"
        second = _acknowledge(client, article_id, second_version)
        assert second.status_code == 200, second.text
        assert second.json()["article_version_id"] == second_version
        assert second.json()["acknowledged_at"] != first_at
        rebound = client.get("/api/trust-articles/policy-acknowledgments")
        assert article_id in rebound.json()["acknowledged_article_ids"]

        db_session.expire_all()
        rows = (
            db_session.query(PolicyAcknowledgment)
            .filter(PolicyAcknowledgment.trust_article_id == article_id)
            .order_by(PolicyAcknowledgment.id)
            .all()
        )
        assert [row.article_version_id for row in rows] == [first_version, second_version]
        assert rows[0].revoked_at is not None
        assert rows[1].revoked_at is None
        assert rows[0].workspace_id == 1
        assert rows[1].workspace_id == 1
        user = db_session.query(User).filter(User.email == "admin@trust.local").one()
        assert rows[0].user_id == user.id
        assert rows[1].user_id == user.id

        withdrawn = client.patch(f"/api/trust-articles/{article_id}", json={"published": 0})
        assert withdrawn.status_code == 200, withdrawn.text
        assert withdrawn.json()["published"] == 0
        client.post("/api/auth/logout")
        hidden = client.get(f"/api/trust-articles/{article_id}")
        assert hidden.status_code == 404, hidden.text

        _login_admin(client)
        after_unpublish = client.get("/api/trust-articles/policy-acknowledgments")
        assert article_id not in after_unpublish.json()["acknowledged_article_ids"]
        refused = _acknowledge(client, article_id, second_version)
        assert refused.status_code == 400, refused.text

        restored = client.patch(f"/api/trust-articles/{article_id}", json={"published": 1})
        assert restored.status_code == 200, restored.text
        assert restored.json()["published_version_id"] == second_version
        still = client.get("/api/trust-articles/policy-acknowledgments")
        assert article_id not in still.json()["acknowledged_article_ids"]
        third = _acknowledge(client, article_id, second_version)
        assert third.status_code == 200, third.text
        assert third.json()["article_version_id"] == second_version
        assert third.json()["acknowledged_at"] != second.json()["acknowledged_at"]
    finally:
        db_session.rollback()
        _delete_slugs(db_session, slug)


def test_retried_create_returns_the_same_article(client: TestClient, db_session: Session) -> None:
    """The same Idempotency-Key returns the first article and does not insert another."""
    _login_admin(client)
    slug = _slug("retry-create")
    key = f"tc17001-{uuid.uuid4().hex[:12]}"
    headers = _idempotency_header(key)
    body = {
        "slug": slug,
        "title": "Retry title",
        "content": "retry body",
        "workspace_id": 1,
        "category": "security",
    }
    try:
        first = client.post("/api/trust-articles/", json=body, headers=headers)
        assert first.status_code == 200, first.text
        second = client.post("/api/trust-articles/", json=body, headers=headers)
        assert second.status_code == 200, second.text
        assert second.json() == first.json()
        assert len(_rows(db_session, slug)) == 1
        article_id = first.json()["id"]

        fresh = SessionLocal()
        try:
            stored = fresh.execute(
                text(
                    """
                    SELECT slug, title, content, published
                    FROM trust_articles WHERE id = :id
                    """
                ),
                {"id": article_id},
            ).one()
            version = fresh.execute(
                text(
                    """
                    SELECT version_number, title, content
                    FROM trust_article_versions
                    WHERE trust_article_id = :id
                    """
                ),
                {"id": article_id},
            ).one()
        finally:
            fresh.close()
        assert stored == (slug, "Retry title", "retry body", 1)
        assert version == (1, "Retry title", "retry body")

        other = dict(body)
        other["title"] = "Different title"
        conflict = client.post("/api/trust-articles/", json=other, headers=headers)
        assert conflict.status_code == 422, conflict.text
        assert "different request body" in conflict.json()["detail"]
        assert len(_rows(db_session, slug)) == 1

        duplicate = client.post("/api/trust-articles/", json=body)
        assert duplicate.status_code == 400, duplicate.text
        assert len(_rows(db_session, slug)) == 1

        invalid = client.post(
            "/api/trust-articles/",
            json={**body, "slug": _slug("bad-key")},
            headers=_idempotency_header("has space"),
        )
        assert invalid.status_code == 422, invalid.text
    finally:
        _delete_idempotency(db_session, key)
        _delete_slugs(db_session, slug)


def test_publish_failure_rolls_back_and_retry_inserts_one(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A version write that fails leaves no article. The same key can be retried once."""
    from app.api.routes import trust_articles as routes
    from app.services.trust_article_versions import approve_current_draft

    _login_admin(client)
    slug = _slug("partial")
    key = f"tc17001-fail-{uuid.uuid4().hex[:12]}"
    headers = _idempotency_header(key)

    def boom(*_args, **_kwargs):
        raise RuntimeError("synthetic version failure")

    monkeypatch.setattr(routes, "approve_current_draft", boom)
    try:
        with pytest.raises(RuntimeError, match="synthetic version failure"):
            client.post(
                "/api/trust-articles/",
                json={
                    "slug": slug,
                    "title": "Partial",
                    "content": "should roll back",
                    "workspace_id": 1,
                },
                headers=headers,
            )
        assert _rows(db_session, slug) == []
        monkeypatch.setattr(routes, "approve_current_draft", approve_current_draft)
        payload = {
            "slug": slug,
            "title": "Partial",
            "content": "should roll back",
            "workspace_id": 1,
        }
        retried = client.post("/api/trust-articles/", json=payload, headers=headers)
        assert retried.status_code == 200, retried.text
        assert len(_rows(db_session, slug)) == 1
        replay = client.post("/api/trust-articles/", json=payload, headers=headers)
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == retried.json()["id"]
    finally:
        _delete_idempotency(db_session, key)
        _delete_slugs(db_session, slug)


def test_acknowledgment_version_foreign_key_rejects_a_missing_version(
    client: TestClient, db_session: Session
) -> None:
    """An acknowledgment cannot point at a version that does not exist."""
    from sqlalchemy.exc import IntegrityError

    _login_admin(client)
    user = db_session.query(User).filter(User.email == "admin@trust.local").one()
    slug = _slug("fk-ack")
    try:
        created = client.post(
            "/api/trust-articles/",
            json={
                "slug": slug,
                "title": "FK policy",
                "content": "body",
                "workspace_id": 1,
                "is_policy": True,
            },
        )
        assert created.status_code == 200, created.text
        article_id = created.json()["id"]
        db_session.add(
            PolicyAcknowledgment(
                user_id=user.id,
                trust_article_id=article_id,
                article_version_id=2_000_000_000,
                workspace_id=1,
                acknowledged_at=db_session.execute(text("SELECT now()")).scalar(),
            )
        )
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()
        assert (
            db_session.query(PolicyAcknowledgment)
            .filter(PolicyAcknowledgment.trust_article_id == article_id)
            .count()
            == 0
        )
    finally:
        db_session.rollback()
        _delete_slugs(db_session, slug)


def test_revoke_acknowledgments_revokes_a_null_version_id(
    client: TestClient, db_session: Session
) -> None:
    """A null version id is not the version being kept, so it is revoked."""
    from datetime import datetime, timezone

    from app.services.trust_article_versions import revoke_acknowledgments

    _login_admin(client)
    slug = _slug("null-version-revoke")
    try:
        created = client.post(
            "/api/trust-articles/",
            json={
                "slug": slug,
                "title": "Null version",
                "content": "body",
                "workspace_id": 1,
                "is_policy": True,
            },
        )
        assert created.status_code == 200, created.text
        article_id = created.json()["id"]
        version_id = created.json()["published_version_id"]
        user = db_session.query(User).filter(User.email == "admin@trust.local").one()
        ack = PolicyAcknowledgment(
            user_id=user.id,
            trust_article_id=article_id,
            article_version_id=None,
            workspace_id=1,
            acknowledged_at=datetime.now(timezone.utc),
        )
        db_session.add(ack)
        db_session.flush()
        revoke_acknowledgments(db_session, article_id, keep_version_id=version_id)
        db_session.flush()
        db_session.refresh(ack)
        assert ack.revoked_at is not None
    finally:
        db_session.rollback()
        _delete_slugs(db_session, slug)


def test_first_upgrade_binds_a_legacy_acknowledgment_without_revoking_it() -> None:
    """A first upgrade, with no downgrade archive, binds a legacy acknowledgment to version 1."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    from sqlalchemy import create_engine

    from app.core.database import engine as app_engine

    api_dir = Path(__file__).resolve().parents[2]
    env = {
        **os.environ,
        "DATABASE_URL": os.environ["DATABASE_URL"],
        "TRUST_COPILOT_TESTING": "1",
    }
    archives = (
        "tc17001_version_archive",
        "tc17001_article_pub_archive",
        "tc17001_ack_binding_archive",
        "tc17001_ack_row_archive",
    )
    slug = _slug("legacy-ack")
    article_id: int | None = None

    def alembic(*args: str) -> None:
        app_engine.dispose()
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=api_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr[-2000:]

    try:
        alembic("downgrade", "tc04005a_member_revoked_at")
        raw = create_engine(env["DATABASE_URL"])
        with raw.begin() as conn:
            for name in archives:
                conn.execute(text(f"DROP TABLE IF EXISTS {name}"))
            user_id = conn.execute(
                text("SELECT id FROM users WHERE email = 'admin@trust.local'")
            ).scalar()
            assert user_id
            article_id = conn.execute(
                text(
                    """
                    INSERT INTO trust_articles (
                        workspace_id, slug, title, content, published, is_policy
                    )
                    VALUES (1, :slug, 'Legacy policy', 'legacy body', 1, true)
                    RETURNING id
                    """
                ),
                {"slug": slug},
            ).scalar()
            ack_id = conn.execute(
                text(
                    """
                    INSERT INTO policy_acknowledgments (user_id, trust_article_id, acknowledged_at)
                    VALUES (:user_id, :article_id, now())
                    RETURNING id
                    """
                ),
                {"user_id": user_id, "article_id": article_id},
            ).scalar()
        raw.dispose()
        alembic("upgrade", "head")
        raw = create_engine(env["DATABASE_URL"])
        with raw.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT p.article_version_id, p.workspace_id, p.revoked_at,
                           v.version_number, t.published_version_id
                    FROM policy_acknowledgments p
                    JOIN trust_articles t ON t.id = p.trust_article_id
                    JOIN trust_article_versions v ON v.id = p.article_version_id
                    WHERE p.id = :id
                    """
                ),
                {"id": ack_id},
            ).one()
        raw.dispose()
        assert row.version_number == 1
        assert row.revoked_at is None
        assert row.workspace_id == 1
        assert row.article_version_id == row.published_version_id
    finally:
        alembic("upgrade", "head")
        raw = create_engine(env["DATABASE_URL"])
        with raw.begin() as conn:
            if article_id is not None:
                conn.execute(text("DELETE FROM trust_articles WHERE id = :id"), {"id": article_id})
            conn.execute(text("DELETE FROM trust_articles WHERE slug = :slug"), {"slug": slug})
        raw.dispose()


def test_member_acknowledge_without_published_version_returns_400(
    client: TestClient, db_session: Session
) -> None:
    """A non-admin member cannot publish a policy by acknowledging it.

    The id sent is the one approve_current_draft would assign. The response
    is 400, published_version_id stays null, and no version row is inserted.
    """
    slug = _slug("ack-no-version")
    article_id = _legacy_policy(db_session, slug, published_version_id=None)
    try:
        _login(client, "editor@trust.local", "e")
        denied = client.patch(f"/api/trust-articles/{article_id}", json={"published": 1})
        assert denied.status_code == 403, denied.text

        predicted = _next_version_id()
        refused = _acknowledge(client, article_id, predicted)
        assert refused.status_code == 400, refused.text
        assert refused.json()["detail"] == _NO_PUBLISHED_POLICY

        db_session.expire_all()
        stored = db_session.get(TrustArticle, article_id)
        assert stored is not None
        assert stored.published_version_id is None
        assert _version_count(db_session, article_id) == 0
        assert (
            db_session.query(PolicyAcknowledgment)
            .filter(PolicyAcknowledgment.trust_article_id == article_id)
            .count()
            == 0
        )
    finally:
        db_session.rollback()
        _delete_slugs(db_session, slug)


def test_member_acknowledge_missing_version_row_leaves_published_id(
    client: TestClient, db_session: Session
) -> None:
    """A published_version_id that points at no row is not replaced by a publish."""
    slug = _slug("ack-dangling")
    dangling_id = 2_000_000_001
    article_id = _legacy_policy(db_session, slug, published_version_id=dangling_id)
    try:
        _login(client, "editor@trust.local", "e")
        refused = _acknowledge(client, article_id, _next_version_id())
        assert refused.status_code == 400, refused.text
        assert refused.json()["detail"] == _NO_PUBLISHED_POLICY

        db_session.expire_all()
        stored = db_session.get(TrustArticle, article_id)
        assert stored is not None
        assert stored.published_version_id == dangling_id
        assert _version_count(db_session, article_id) == 0
    finally:
        db_session.rollback()
        _delete_slugs(db_session, slug)


def test_member_acknowledge_current_version_returns_200(
    client: TestClient, db_session: Session
) -> None:
    """A member acknowledge of the current published version still returns 200."""
    _login_admin(client)
    slug = _slug("ack-current")
    try:
        created = client.post(
            "/api/trust-articles/",
            json={
                "slug": slug,
                "title": "Current policy",
                "content": "published text",
                "workspace_id": 1,
                "is_policy": True,
            },
        )
        assert created.status_code == 200, created.text
        article_id = created.json()["id"]
        version_id = created.json()["published_version_id"]
        assert isinstance(version_id, int)
        assert _version_count(db_session, article_id) == 1

        _login(client, "editor@trust.local", "e")
        acknowledged = _acknowledge(client, article_id, version_id)
        assert acknowledged.status_code == 200, acknowledged.text
        body = acknowledged.json()
        assert body["ok"] is True
        assert body["article_version_id"] == version_id
        assert body["workspace_id"] == 1

        db_session.expire_all()
        stored = db_session.get(TrustArticle, article_id)
        assert stored is not None
        assert stored.published_version_id == version_id
        assert _version_count(db_session, article_id) == 1
    finally:
        db_session.rollback()
        _delete_slugs(db_session, slug)


def test_admin_publish_still_approves_the_current_draft(
    client: TestClient, db_session: Session
) -> None:
    """An administrator publish still stores version 1 of the current draft."""
    _login_admin(client)
    slug = _slug("admin-publish")
    try:
        created = client.post(
            "/api/trust-articles/",
            json={
                "slug": slug,
                "title": "Draft policy",
                "content": "not yet approved",
                "workspace_id": 1,
                "published": 0,
                "is_policy": True,
            },
        )
        assert created.status_code == 200, created.text
        article_id = created.json()["id"]
        assert created.json()["published"] == 0
        assert created.json()["published_version_id"] is None
        assert _version_count(db_session, article_id) == 0

        published = client.patch(f"/api/trust-articles/{article_id}", json={"published": 1})
        assert published.status_code == 200, published.text
        body = published.json()
        assert body["published"] == 1
        assert body["published_version"] == 1
        version_id = body["published_version_id"]
        assert isinstance(version_id, int)
        assert body["published_title"] == "Draft policy"
        assert body["published_content"] == "not yet approved"

        db_session.expire_all()
        stored = db_session.get(TrustArticle, article_id)
        assert stored is not None
        assert stored.published_version_id == version_id
        assert _version_count(db_session, article_id) == 1
    finally:
        db_session.rollback()
        _delete_slugs(db_session, slug)
