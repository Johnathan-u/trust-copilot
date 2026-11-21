"""Admin-configurable workspace dashboard cards."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base

CARD_SIZES = ("small", "medium", "large")
VISIBILITY_SCOPES = ("all", "admin")

ALLOWED_ROUTES = [
    "/dashboard/documents",
    "/dashboard/questionnaires",
    "/dashboard/review",
    "/dashboard/requests",
    "/dashboard/exports",
    "/dashboard/compliance-gaps",
    "/dashboard/trust-center",
    "/dashboard/proof-chain",
    "/dashboard/members",
    "/dashboard/notifications",
    "/dashboard/slack",
    "/dashboard/gmail",
    "/dashboard/audit",
    "/dashboard/ai-governance",
    "/dashboard/settings",
    "/dashboard/security",
]

# Permission the application nav requires before it shows the route.
# None means apps/web/lib/app-navigation.ts shows it to every signed-in member.
# requiresAdmin is can_admin. requiresReview is can_review.
# /dashboard/review and /dashboard/exports have neither flag.
# /dashboard/security is accountNavItems and has no flag.
ROUTE_PERMISSION: dict[str, str | None] = {
    "/dashboard/documents": None,
    "/dashboard/questionnaires": None,
    "/dashboard/review": None,
    "/dashboard/requests": "can_review",
    "/dashboard/exports": None,
    "/dashboard/compliance-gaps": None,
    "/dashboard/trust-center": None,
    "/dashboard/proof-chain": None,
    "/dashboard/members": "can_admin",
    "/dashboard/notifications": "can_admin",
    "/dashboard/slack": "can_admin",
    "/dashboard/gmail": "can_admin",
    "/dashboard/audit": "can_admin",
    "/dashboard/ai-governance": "can_admin",
    "/dashboard/settings": "can_admin",
    "/dashboard/security": None,
}

ALLOWED_ICONS = [
    "document",
    "questionnaire",
    "export",
    "trust",
    "request",
    "vendor",
    "control",
    "compliance",
    "mapping",
    "audit",
    "members",
    "notification",
    "slack",
    "gmail",
    "settings",
    "security",
    "shield",
    "chart",
    "star",
    "folder",
    "link",
    "globe",
    "lock",
    "check",
    "alert",
]


class DashboardCard(Base):
    __tablename__ = "dashboard_cards"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(32), nullable=False, default="document")
    target_route = Column(String(256), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    is_enabled = Column(Boolean, nullable=False, default=True)
    visibility_scope = Column(String(16), nullable=False, default="all")
    size = Column(String(16), nullable=False, default="medium")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
