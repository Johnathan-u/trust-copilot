"""Trust Center analytics service (P1-67).

Track what was viewed, requested, downloaded per buyer/opportunity.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.trust_article import TrustArticle
from app.models.nda_access_request import NdaAccessRequest

logger = logging.getLogger(__name__)


def get_trust_center_analytics(db: Session, workspace_id: int) -> dict:
    """Aggregate Trust Center analytics for a workspace."""
    total_articles = db.query(func.count(TrustArticle.id)).filter(
        TrustArticle.workspace_id == workspace_id,
    ).scalar() or 0

    published = db.query(func.count(TrustArticle.id)).filter(
        TrustArticle.workspace_id == workspace_id,
        TrustArticle.published == 1,
    ).scalar() or 0

    unpublished = total_articles - published

    total_access_requests = db.query(func.count(NdaAccessRequest.id)).filter(
        NdaAccessRequest.workspace_id == workspace_id,
    ).scalar() or 0

    approved_requests = db.query(func.count(NdaAccessRequest.id)).filter(
        NdaAccessRequest.workspace_id == workspace_id,
        NdaAccessRequest.status == "approved",
    ).scalar() or 0

    pending_requests = db.query(func.count(NdaAccessRequest.id)).filter(
        NdaAccessRequest.workspace_id == workspace_id,
        NdaAccessRequest.status == "pending",
    ).scalar() or 0

    categories = db.query(
        TrustArticle.category,
        func.count(TrustArticle.id),
    ).filter(
        TrustArticle.workspace_id == workspace_id,
    ).group_by(TrustArticle.category).all()

    return {
        "total_articles": total_articles,
        "published": published,
        "unpublished": unpublished,
        "by_category": {cat or "uncategorized": cnt for cat, cnt in categories},
        "access_requests": {
            "total": total_access_requests,
            "approved": approved_requests,
            "pending": pending_requests,
        },
    }
