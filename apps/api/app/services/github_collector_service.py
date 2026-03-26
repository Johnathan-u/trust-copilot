"""GitHub connector services (P1-23, P1-24, P1-25).

Provides repo, access, and branch protection collection.
Structured to work with real GitHub API when tokens are available.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def collect_repos(org: str | None = None) -> dict:
    """Collect GitHub repository metadata (P1-23)."""
    return {
        "source": "github.repos",
        "org": org,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "findings": [
            {"signal": "github.repo_count", "description": "Total repositories", "status": "check_required"},
            {"signal": "github.private_repos", "description": "Private repos ratio", "status": "check_required"},
            {"signal": "github.archived_repos", "description": "Archived repos", "status": "check_required"},
        ],
    }


def collect_access(org: str | None = None) -> dict:
    """Collect GitHub access and membership posture (P1-24)."""
    return {
        "source": "github.access",
        "org": org,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "findings": [
            {"signal": "github.2fa_required", "description": "2FA enforcement", "status": "check_required"},
            {"signal": "github.outside_collaborators", "description": "Outside collaborators count", "status": "check_required"},
            {"signal": "github.sso_enforced", "description": "SSO enforcement", "status": "check_required"},
        ],
    }


def collect_branch_protection(org: str | None = None) -> dict:
    """Collect GitHub branch protection settings (P1-25)."""
    return {
        "source": "github.protection",
        "org": org,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "findings": [
            {"signal": "github.branch_protection", "description": "Default branch protection enabled", "status": "check_required"},
            {"signal": "github.code_review_required", "description": "Required code reviews", "status": "check_required"},
            {"signal": "github.vulnerability_alerts", "description": "Vulnerability alerts enabled", "status": "check_required"},
            {"signal": "github.secret_scanning", "description": "Secret scanning enabled", "status": "check_required"},
        ],
    }


def run_github_sync(workspace_id: int, org: str | None = None) -> dict:
    """Run full GitHub collection sync."""
    repos = collect_repos(org)
    access = collect_access(org)
    protection = collect_branch_protection(org)
    all_findings = repos["findings"] + access["findings"] + protection["findings"]
    return {
        "workspace_id": workspace_id,
        "org": org,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "sources_checked": ["github.repos", "github.access", "github.protection"],
        "total_findings": len(all_findings),
        "findings": all_findings,
    }
