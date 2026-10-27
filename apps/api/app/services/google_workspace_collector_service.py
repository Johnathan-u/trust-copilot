"""Google Workspace connector services (P1-27, P1-28, P1-29).

Returns the versioned observation contract. Does not call Google APIs.
"""

import logging

from app.services.provider_adapter.adapters import (
    GOOGLE,
    GOOGLE_MFA,
    GOOGLE_ROLES,
    GOOGLE_USERS,
    legacy_collection,
    merge_observations,
)
from app.services.provider_adapter.contract import CONTRACT_NAME, SCHEMA_VERSION, utc_now

logger = logging.getLogger(__name__)


def collect_users(
    domain: str | None = None,
    *,
    workspace_id: int | None = None,
    recorded=None,
) -> dict:
    """Collect Google Workspace user directory (P1-27)."""
    return legacy_collection(
        GOOGLE,
        source="google.users",
        scope_fields={"domain": domain},
        workspace_id=workspace_id,
        external_account_id=domain,
        signals=GOOGLE_USERS,
        recorded=recorded,
    )


def collect_mfa_enrollment(
    domain: str | None = None,
    *,
    workspace_id: int | None = None,
    recorded=None,
) -> dict:
    """Collect Google Workspace MFA enrollment status (P1-28)."""
    return legacy_collection(
        GOOGLE,
        source="google.mfa",
        scope_fields={"domain": domain},
        workspace_id=workspace_id,
        external_account_id=domain,
        signals=GOOGLE_MFA,
        recorded=recorded,
    )


def collect_admin_roles(
    domain: str | None = None,
    *,
    workspace_id: int | None = None,
    recorded=None,
) -> dict:
    """Collect Google Workspace admin role assignments (P1-29)."""
    return legacy_collection(
        GOOGLE,
        source="google.admin_roles",
        scope_fields={"domain": domain},
        workspace_id=workspace_id,
        external_account_id=domain,
        signals=GOOGLE_ROLES,
        recorded=recorded,
    )


def run_google_sync(workspace_id: int, domain: str | None = None, *, recorded=None) -> dict:
    """Run full Google Workspace sync."""
    users = collect_users(domain, workspace_id=workspace_id, recorded=recorded)
    mfa = collect_mfa_enrollment(domain, workspace_id=workspace_id, recorded=recorded)
    roles = collect_admin_roles(domain, workspace_id=workspace_id, recorded=recorded)
    findings = users["findings"] + mfa["findings"] + roles["findings"]
    return {
        "workspace_id": workspace_id,
        "domain": domain,
        "synced_at": utc_now().isoformat(),
        "sources_checked": ["google.users", "google.mfa", "google.admin_roles"],
        "total_findings": len(findings),
        "findings": findings,
        "observation_contract": {
            "schema_version": SCHEMA_VERSION,
            "contract": CONTRACT_NAME,
            "adapter": GOOGLE.descriptor().to_dict(),
            "observations": merge_observations([users, mfa, roles]),
        },
    }
