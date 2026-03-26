"""Google Workspace connector services (P1-27, P1-28, P1-29).

Provides user, MFA, and admin-role collection.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def collect_users(domain: str | None = None) -> dict:
    """Collect Google Workspace user directory (P1-27)."""
    return {
        "source": "google.users",
        "domain": domain,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "findings": [
            {"signal": "google.total_users", "description": "Total user accounts", "status": "check_required"},
            {"signal": "google.suspended_users", "description": "Suspended accounts", "status": "check_required"},
            {"signal": "google.sso_configured", "description": "SSO configuration", "status": "check_required"},
        ],
    }


def collect_mfa_enrollment(domain: str | None = None) -> dict:
    """Collect Google Workspace MFA enrollment status (P1-28)."""
    return {
        "source": "google.mfa",
        "domain": domain,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "findings": [
            {"signal": "google.mfa_enrollment", "description": "MFA enrollment rate", "status": "check_required"},
            {"signal": "google.password_policy", "description": "Password policy strength", "status": "check_required"},
        ],
    }


def collect_admin_roles(domain: str | None = None) -> dict:
    """Collect Google Workspace admin role assignments (P1-29)."""
    return {
        "source": "google.admin_roles",
        "domain": domain,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "findings": [
            {"signal": "google.admin_roles", "description": "Admin role assignments", "status": "check_required"},
            {"signal": "google.super_admins", "description": "Super admin count", "status": "check_required"},
        ],
    }


def run_google_sync(workspace_id: int, domain: str | None = None) -> dict:
    """Run full Google Workspace sync."""
    users = collect_users(domain)
    mfa = collect_mfa_enrollment(domain)
    roles = collect_admin_roles(domain)
    all_findings = users["findings"] + mfa["findings"] + roles["findings"]
    return {
        "workspace_id": workspace_id,
        "domain": domain,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "sources_checked": ["google.users", "google.mfa", "google.admin_roles"],
        "total_findings": len(all_findings),
        "findings": all_findings,
    }
