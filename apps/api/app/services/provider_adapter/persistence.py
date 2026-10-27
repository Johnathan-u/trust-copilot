"""Persistence boundary for collected provider evidence.

Successful evidence is written only through ``store_successful_observation``.
Static catalog rows, demo fixtures, seeded values, and non-success states are
rejected before any insert. Manual ingestion can still store ordinary titles,
and it refuses observation-shaped claims.
"""

from __future__ import annotations

import json
from typing import Any

from app.models.evidence_item import EvidenceItem
from app.services.provider_adapter.contract import (
    SCHEMA_VERSION,
    ProviderObservation,
    rejection_code,
    value_claims_denied_marker,
)
from app.services.provider_adapter.seams import (
    SideEffectIdempotencyPort,
    SourceVersionPort,
    default_idempotency,
    default_source_version,
)

_COLLECTION_CLAIM_KEYS = frozenset(
    {"observation_id", "state", "provenance", "normalized_value", "collector_version"}
)


class CollectedEvidenceRejected(Exception):
    """The payload must not be stored as successfully collected evidence."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def assert_storable(observation: ProviderObservation) -> None:
    code = rejection_code(observation)
    if code:
        raise CollectedEvidenceRejected(
            code,
            f"refusing to store observation as collected evidence ({code})",
        )


def store_successful_observation(
    db: Any,
    workspace_id: int,
    observation: ProviderObservation,
    *,
    idempotency_key: str | None = None,
    idempotency: SideEffectIdempotencyPort | None = None,
    source_versions: SourceVersionPort | None = None,
) -> dict[str, Any]:
    """Insert one successful observation, or refuse before touching the session."""
    assert_storable(observation)
    port = idempotency if idempotency is not None else default_idempotency
    key = idempotency_key or f"provider-observation:{observation.observation_id}"
    if not port.claim(key):
        return {
            "stored": False,
            "duplicate": True,
            "idempotency_key": key,
            "evidence_id": None,
        }
    versions = source_versions or default_source_version
    source_version = observation.source_version or versions.source_version(
        workspace_id=workspace_id,
        provider=observation.provider,
        resource_id=observation.resource_id,
        object_revision=observation.object_revision,
    )
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "source_version": source_version,
        "observation": observation.to_dict(),
    }
    item = EvidenceItem(
        workspace_id=workspace_id,
        source_type="integration",
        title=f"{observation.provider}:{observation.resource_id}"[:512],
        source_metadata=json.dumps(metadata),
        approval_status="pending",
    )
    db.add(item)
    if hasattr(db, "flush"):
        db.flush()
    return {
        "stored": True,
        "duplicate": False,
        "idempotency_key": key,
        "evidence_id": getattr(item, "id", None),
        "source_version": source_version,
    }


def _parse_metadata(source_metadata: str | None) -> Any:
    if source_metadata is None:
        return None
    try:
        return json.loads(source_metadata)
    except (TypeError, ValueError):
        return source_metadata


def _claims_collection(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if _COLLECTION_CLAIM_KEYS.intersection(value.keys()):
        return True
    nested = value.get("observation")
    return isinstance(nested, dict) and bool(_COLLECTION_CLAIM_KEYS.intersection(nested.keys()))


def guard_ingest_payload(*, title: str, source_metadata: str | None) -> None:
    """Refuse demo, seeded, static, or observation-shaped intake.

    Ordinary titles with no collection claim are unchanged.
    """
    parsed = _parse_metadata(source_metadata)
    marker = value_claims_denied_marker({"title": title, "source_metadata": parsed})
    if marker:
        raise CollectedEvidenceRejected(
            marker,
            f"refusing to store intake as collected evidence ({marker})",
        )
    if _claims_collection(parsed):
        raise CollectedEvidenceRejected(
            "not_success",
            "ingestion cannot store provider observation claims",
        )
