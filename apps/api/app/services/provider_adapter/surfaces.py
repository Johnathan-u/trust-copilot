"""Observation envelopes for wizard, health, credentials and registry actions.

These actions are not provider collections. Their state is never success.
"""

from __future__ import annotations

from datetime import datetime

from app.services.provider_adapter.contract import (
    CAPABILITY_VERSION,
    COLLECTOR_VERSION,
    AdapterDescriptor,
    ObservationState,
    ProvenanceKind,
    make_observation,
    observation_envelope,
)


def _descriptor(provider: str, state: ObservationState, reason: str | None) -> AdapterDescriptor:
    return AdapterDescriptor(
        provider=provider,
        capability_version=CAPABILITY_VERSION,
        collector_version=COLLECTOR_VERSION,
        on_contract=True,
        accepts_success=False,
        live_collection=False,
        vendor_selected=provider != "hris",
        default_state=state,
        blocked_reason=reason,
    )


def action_contract(
    *,
    provider: str,
    resource_id: str,
    state: ObservationState,
    provenance_kind: ProvenanceKind,
    workspace_id: int | None = None,
    error_code: str | None = None,
    safe_message: str | None = None,
    note: str = "",
    external_account_id: str | None = None,
    credential_type: str | None = None,
    observed_at: datetime | None = None,
) -> dict:
    observation, connection = make_observation(
        provider=provider,
        resource_id=resource_id,
        signal=resource_id,
        state=state,
        provenance_kind=provenance_kind,
        workspace_id=workspace_id,
        external_account_id=external_account_id,
        error_code=error_code,
        safe_message=safe_message,
        note=note,
        credential_type=credential_type,
        observed_at=observed_at,
    )
    return observation_envelope(
        _descriptor(provider, state, safe_message),
        [observation],
        connection,
    )
