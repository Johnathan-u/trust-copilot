"""GitHub connector services (P1-23, P1-24, P1-25).

Returns the versioned observation contract. Does not call the GitHub API.
"""

import logging

from app.services.provider_adapter.adapters import (
    GITHUB,
    GITHUB_ACCESS,
    GITHUB_PROTECTION,
    GITHUB_REPOS,
    legacy_collection,
    merge_observations,
)
from app.services.provider_adapter.contract import CONTRACT_NAME, SCHEMA_VERSION, utc_now

logger = logging.getLogger(__name__)


def collect_repos(
    org: str | None = None,
    *,
    workspace_id: int | None = None,
    recorded=None,
) -> dict:
    """Collect GitHub repository metadata (P1-23)."""
    return legacy_collection(
        GITHUB,
        source="github.repos",
        scope_fields={"org": org},
        workspace_id=workspace_id,
        external_account_id=org,
        signals=GITHUB_REPOS,
        recorded=recorded,
    )


def collect_access(
    org: str | None = None,
    *,
    workspace_id: int | None = None,
    recorded=None,
) -> dict:
    """Collect GitHub access and membership posture (P1-24)."""
    return legacy_collection(
        GITHUB,
        source="github.access",
        scope_fields={"org": org},
        workspace_id=workspace_id,
        external_account_id=org,
        signals=GITHUB_ACCESS,
        recorded=recorded,
    )


def collect_branch_protection(
    org: str | None = None,
    *,
    workspace_id: int | None = None,
    recorded=None,
) -> dict:
    """Collect GitHub branch protection settings (P1-25)."""
    return legacy_collection(
        GITHUB,
        source="github.protection",
        scope_fields={"org": org},
        workspace_id=workspace_id,
        external_account_id=org,
        signals=GITHUB_PROTECTION,
        recorded=recorded,
    )


def run_github_sync(workspace_id: int, org: str | None = None, *, recorded=None) -> dict:
    """Run full GitHub collection sync."""
    repos = collect_repos(org, workspace_id=workspace_id, recorded=recorded)
    access = collect_access(org, workspace_id=workspace_id, recorded=recorded)
    protection = collect_branch_protection(org, workspace_id=workspace_id, recorded=recorded)
    findings = repos["findings"] + access["findings"] + protection["findings"]
    return {
        "workspace_id": workspace_id,
        "org": org,
        "synced_at": utc_now().isoformat(),
        "sources_checked": ["github.repos", "github.access", "github.protection"],
        "total_findings": len(findings),
        "findings": findings,
        "observation_contract": {
            "schema_version": SCHEMA_VERSION,
            "contract": CONTRACT_NAME,
            "adapter": GITHUB.descriptor().to_dict(),
            "observations": merge_observations([repos, access, protection]),
        },
    }
