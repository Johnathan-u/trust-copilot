"""Approved trust-article versions.

A publish writes one immutable row. A later edit of the article changes the
draft only. Readers keep the published snapshot until a new publish. Unpublish
and a new version revoke acknowledgments of the previous version.
"""

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.policy_acknowledgment import PolicyAcknowledgment
from app.models.trust_article import TrustArticle, TrustArticleVersion


def _draft_key(article: TrustArticle) -> tuple:
    return (
        article.slug,
        article.title,
        article.content or "",
        article.category,
        bool(article.is_policy),
    )


def _version_key(version: TrustArticleVersion) -> tuple:
    return (
        version.slug,
        version.title,
        version.content or "",
        version.category,
        bool(version.is_policy),
    )


def revoke_acknowledgments(
    db: Session, article_id: int, *, keep_version_id: int | None = None
) -> None:
    """Mark current acknowledgments revoked. The kept version stays in force."""
    now = datetime.now(timezone.utc)
    query = db.query(PolicyAcknowledgment).filter(
        PolicyAcknowledgment.trust_article_id == article_id,
        PolicyAcknowledgment.revoked_at.is_(None),
    )
    if keep_version_id is not None:
        query = query.filter(PolicyAcknowledgment.article_version_id != keep_version_id)
    for row in query.all():
        row.revoked_at = now


def approve_current_draft(db: Session, article: TrustArticle) -> TrustArticleVersion:
    """Publish the current draft.

    The same text reuses the existing version. Different text inserts the next
    version and revokes acknowledgments of every other version. The caller commits.
    """
    if article.workspace_id is None:
        raise ValueError("cannot publish a trust article without a workspace")
    if article.id is None:
        db.flush()
    current = None
    if article.published_version_id is not None:
        current = db.get(TrustArticleVersion, article.published_version_id)
    if current is not None and _version_key(current) == _draft_key(article):
        article.published = 1
        return current
    latest = (
        db.query(func.max(TrustArticleVersion.version_number))
        .filter(TrustArticleVersion.trust_article_id == article.id)
        .scalar()
    )
    version = TrustArticleVersion(
        trust_article_id=article.id,
        workspace_id=article.workspace_id,
        version_number=int(latest or 0) + 1,
        slug=article.slug,
        title=article.title,
        content=article.content or "",
        category=article.category,
        is_policy=bool(article.is_policy),
    )
    db.add(version)
    db.flush()
    article.published = 1
    article.published_version_id = version.id
    revoke_acknowledgments(db, article.id, keep_version_id=version.id)
    return version
