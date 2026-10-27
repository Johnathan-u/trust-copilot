"""Cloud connector packs (P2-103 GCP, P2-104 Azure, P2-105 GitLab, P2-106 Okta, P2-107 HRIS).

HRIS stays unsupported until an owner selects a vendor (TC-20-005). No provider calls.
"""

import logging

from app.services.provider_adapter.adapters import (
    AZURE,
    GCP,
    GITLAB,
    HRIS,
    OKTA,
    legacy_collection,
)
from app.services.provider_adapter.contract import ObservationState, ProvenanceKind
from app.services.provider_adapter.surfaces import action_contract

logger = logging.getLogger(__name__)


def collect_gcp(
    project_id: str | None = None,
    *,
    workspace_id: int | None = None,
    recorded=None,
) -> dict:
    """GCP connector pack (P2-103)."""
    return legacy_collection(
        GCP,
        source="gcp",
        scope_fields={"project_id": project_id},
        workspace_id=workspace_id,
        external_account_id=project_id,
        recorded=recorded,
    )


def collect_azure(
    tenant_id: str | None = None,
    *,
    workspace_id: int | None = None,
    recorded=None,
) -> dict:
    """Azure connector pack (P2-104)."""
    return legacy_collection(
        AZURE,
        source="azure",
        scope_fields={"tenant_id": tenant_id},
        workspace_id=workspace_id,
        external_account_id=tenant_id,
        recorded=recorded,
    )


def collect_gitlab(
    group: str | None = None,
    *,
    workspace_id: int | None = None,
    recorded=None,
) -> dict:
    """GitLab connector pack (P2-105)."""
    return legacy_collection(
        GITLAB,
        source="gitlab",
        scope_fields={"group": group},
        workspace_id=workspace_id,
        external_account_id=group,
        recorded=recorded,
    )


def collect_okta(
    domain: str | None = None,
    *,
    workspace_id: int | None = None,
    recorded=None,
) -> dict:
    """Okta connector pack (P2-106)."""
    return legacy_collection(
        OKTA,
        source="okta",
        scope_fields={"domain": domain},
        workspace_id=workspace_id,
        external_account_id=domain,
        recorded=recorded,
    )


def collect_hris(
    provider: str | None = None,
    *,
    workspace_id: int | None = None,
    recorded=None,
) -> dict:
    """HRIS connector pack (P2-107). Vendor selection is BLOCKED (TC-20-005)."""
    del recorded
    body = legacy_collection(
        HRIS,
        source="hris",
        scope_fields={"provider": provider},
        workspace_id=workspace_id,
        external_account_id=None,
    )
    for observation in body["observation_contract"]["observations"]:
        observation["safe_message"] = HRIS.blocked_reason
    return body


def run_connector_sync(workspace_id: int, connector: str, **kwargs) -> dict:
    """Run sync for a specific cloud connector."""
    collectors = {
        "gcp": collect_gcp,
        "azure": collect_azure,
        "gitlab": collect_gitlab,
        "okta": collect_okta,
        "hris": collect_hris,
    }
    fn = collectors.get(connector)
    if not fn:
        contract = action_contract(
            provider=connector,
            resource_id=connector,
            state=ObservationState.UNKNOWN,
            provenance_kind=ProvenanceKind.ABSENT,
            workspace_id=workspace_id,
            error_code="unknown_connector",
            safe_message=f"Unknown connector: {connector}",
            note="Unknown connector is not collected evidence",
        )
        return {"error": f"Unknown connector: {connector}", "observation_contract": contract}
    result = fn(workspace_id=workspace_id, **kwargs)
    return {
        "workspace_id": workspace_id,
        "connector": connector,
        **result,
    }
