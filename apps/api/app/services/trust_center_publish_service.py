"""Auto-publish from approved controls to Trust Center (P1-64)."""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.trust_article import TrustArticle
from app.models.workspace_control import WorkspaceControl
from app.models.framework_control import FrameworkControl

logger = logging.getLogger(__name__)


def auto_publish_approved_controls(db: Session, workspace_id: int) -> dict:
    """Create or update Trust Center articles for approved controls."""
    controls = (
        db.query(WorkspaceControl, FrameworkControl.control_key)
        .outerjoin(FrameworkControl, WorkspaceControl.framework_control_id == FrameworkControl.id)
        .filter(
            WorkspaceControl.workspace_id == workspace_id,
            WorkspaceControl.status.in_(["implemented", "passed", "verified"]),
        )
        .all()
    )

    created = 0
    updated = 0
    skipped = 0
    seen_slugs: set[str] = set()

    for ctrl, ctrl_key in controls:
        label = ctrl_key or ctrl.custom_name or f"wc-{ctrl.id}"
        slug = f"control-{label}".lower().replace(" ", "-")

        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        existing = db.query(TrustArticle).filter(
            TrustArticle.workspace_id == workspace_id,
            TrustArticle.slug == slug,
        ).first()

        title = f"Control {label}: {ctrl.status.title()}"
        content = f"This control has been evaluated and is currently in **{ctrl.status}** status."

        if existing:
            if existing.published == 1:
                skipped += 1
                continue
            existing.title = title
            existing.content = content
            existing.published = 1
            updated += 1
        else:
            article = TrustArticle(
                workspace_id=workspace_id,
                title=title,
                slug=slug,
                content=content,
                published=1,
            )
            db.add(article)
            created += 1

    db.flush()
    return {
        "total_controls": len(controls),
        "articles_created": created,
        "articles_updated": updated,
        "articles_skipped": skipped,
    }


def get_published_controls(db: Session, workspace_id: int) -> list[dict]:
    """Get all published Trust Center articles for controls."""
    articles = db.query(TrustArticle).filter(
        TrustArticle.workspace_id == workspace_id,
        TrustArticle.slug.like("control-%"),
        TrustArticle.published == 1,
    ).all()
    return [
        {
            "id": a.id,
            "title": a.title,
            "slug": a.slug,
            "published": a.published,
        }
        for a in articles
    ]
