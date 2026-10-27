"""CRM connector service for Salesforce and HubSpot (E1-02, E1-03).

Demo opportunity rows are returned as rejected observations. They are not
inserted into deals and are not successful collected evidence. No CRM API calls.
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.deal import Deal
from app.services.provider_adapter.adapters import HUBSPOT, SALESFORCE
from app.services.provider_adapter.contract import (
    ObservationState,
    ProvenanceKind,
    ProviderObservation,
    make_observation,
    observation_envelope,
)
from app.services.provider_adapter.demo_fixtures import (
    DEMO_HUBSPOT_DEALS,
    DEMO_SALESFORCE_OPPORTUNITIES,
)
from app.services.provider_adapter.persistence import (
    CollectedEvidenceRejected,
    assert_storable,
)

logger = logging.getLogger(__name__)


def _demo_observation(
    provider: str,
    workspace_id: int,
    record: dict,
) -> ProviderObservation:
    observation, _connection = make_observation(
        provider=provider,
        resource_id=str(record["external_id"]),
        signal=f"{provider}.demo",
        state=ObservationState.UNKNOWN,
        provenance_kind=ProvenanceKind.DEMO,
        workspace_id=workspace_id,
        external_account_id=None,
        object_revision="demo",
        error_code="demo_value",
        safe_message="Demo CRM fixture is not collected evidence",
        note="Hand-built demo fixture; provider was not contacted",
    )
    return observation


def _poisoned_success(provider: str, workspace_id: int, record: dict) -> ProviderObservation:
    """A success-shaped demo observation used only to prove the store rejects it."""
    observation, _connection = make_observation(
        provider=provider,
        resource_id=str(record["external_id"]),
        signal=f"{provider}.demo",
        state=ObservationState.SUCCESS,
        provenance_kind=ProvenanceKind.DEMO,
        workspace_id=workspace_id,
        object_revision="demo",
        normalized_value={"external_id": record["external_id"], "demo": True},
        note="Poisoned demo success must be rejected",
    )
    return observation


def _reject_demo_sync(
    db: Session,
    workspace_id: int,
    provider: str,
    records: tuple[dict, ...],
    adapter,
) -> dict[str, Any]:
    if db is None:
        raise CollectedEvidenceRejected("not_success", "workspace session is required")
    observations: list[ProviderObservation] = []
    details: list[dict[str, str]] = []
    for record in records:
        poisoned = _poisoned_success(provider, workspace_id, record)
        try:
            assert_storable(poisoned)
        except CollectedEvidenceRejected as exc:
            reason = exc.code
        else:
            reason = "demo_value"
        public = _demo_observation(provider, workspace_id, record)
        observations.append(public)
        details.append(
            {
                "action": "rejected",
                "external_id": str(record["external_id"]),
                "reason": reason,
            }
        )
    return {
        "source": provider,
        "synced": 0,
        "details": details,
        "mock": True,
        "data_basis": "synthetic_example",
        "observation_contract": observation_envelope(
            adapter.descriptor(),
            observations,
        ),
    }


def sync_salesforce(db: Session, workspace_id: int) -> dict:
    """Reject demo Salesforce rows. Does not write deals."""
    return _reject_demo_sync(
        db,
        workspace_id,
        "salesforce",
        DEMO_SALESFORCE_OPPORTUNITIES,
        SALESFORCE,
    )


def sync_hubspot(db: Session, workspace_id: int) -> dict:
    """Reject demo HubSpot rows. Does not write deals."""
    return _reject_demo_sync(
        db,
        workspace_id,
        "hubspot",
        DEMO_HUBSPOT_DEALS,
        HUBSPOT,
    )


def get_sync_status(db: Session, workspace_id: int) -> dict:
    sf_count = (
        db.query(Deal)
        .filter(
            Deal.workspace_id == workspace_id,
            Deal.crm_source == "salesforce",
        )
        .count()
    )
    hs_count = (
        db.query(Deal)
        .filter(
            Deal.workspace_id == workspace_id,
            Deal.crm_source == "hubspot",
        )
        .count()
    )
    manual = (
        db.query(Deal)
        .filter(
            Deal.workspace_id == workspace_id,
            Deal.crm_source.is_(None),
        )
        .count()
    )
    return {
        "salesforce": sf_count,
        "hubspot": hs_count,
        "manual": manual,
        "total": sf_count + hs_count + manual,
    }
