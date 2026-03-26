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
    "/dashboard/members",
    "/dashboard/notifications",
    "/dashboard/slack",
    "/dashboard/gmail",
    "/dashboard/audit",
    "/dashboard/ai-governance",
    "/dashboard/settings",
    "/dashboard/security",
]

ALLOWED_ICONS = [
    "document", "questionnaire", "export", "trust", "request",
    "vendor", "control", "compliance", "mapping", "audit",
    "members", "notification", "slack", "gmail", "settings",
    "security", "shield", "chart", "star", "folder",
    "link", "globe", "lock", "check", "alert",
]


class DashboardCard(Base):
    __tablename__ = "dashboard_cards"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
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
