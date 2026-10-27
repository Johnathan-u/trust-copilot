"""Provider observation contract, schema version 1.

Field meaning follows PRODUCT_SPEC ProviderConnection and ProviderObservation.
Unknown, missing permission, failure and unsupported are not success.
Static, demo and seeded provenance is never successful collected evidence.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from app.services.provider_adapter.seams import (
    KeyPurposePort,
    SourceVersionPort,
    default_key_purpose,
    default_source_version,
)

CONTRACT_NAME = "provider-observation"
SCHEMA_VERSION = "1"
COLLECTOR_VERSION = "tc-20-001/1"
CAPABILITY_VERSION = "1"
FINDING_STATUS_VOCABULARY = "observation-state-v1"

DENIED_STATUSES = frozenset({"check_required", "demo", "seeded", "static", "static_catalog"})
DEMO_EXTERNAL_IDS = frozenset({"sf-opp-001", "sf-opp-002", "hs-deal-001"})
_SECRET_KEY_FRAGMENTS = (
    "secret",
    "token",
    "password",
    "access_key",
    "authorization",
    "api_key",
    "private_key",
)


class ObservationState(str, Enum):
    SUCCESS = "success"
    MISSING_PERMISSION = "missing_permission"
    UNKNOWN = "unknown"
    FAILURE = "failure"
    UNSUPPORTED = "unsupported"


class ProvenanceKind(str, Enum):
    RECORDED = "recorded"
    STATIC_CATALOG = "static_catalog"
    DEMO = "demo"
    SEEDED = "seeded"
    CREDENTIAL_CUSTODY = "credential_custody"
    ABSENT = "absent"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_observation_id() -> str:
    return "obs_" + uuid.uuid4().hex


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SECRET_KEY_FRAGMENTS)


def redact_mapping(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy a mapping, replacing secret-like fields. Does not call providers."""
    if not payload:
        return {}
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        name = str(key)
        if _is_secret_key(name):
            redacted[name] = "[redacted]"
            continue
        if isinstance(value, Mapping):
            redacted[name] = redact_mapping(value)
        elif isinstance(value, list):
            redacted[name] = [
                redact_mapping(item) if isinstance(item, Mapping) else item for item in value
            ]
        else:
            redacted[name] = value
    return redacted


def provenance_digest(payload: Mapping[str, Any] | None) -> str:
    encoded = json.dumps(redact_mapping(payload), sort_keys=True, default=str).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()[:16]


@dataclass(frozen=True)
class ObservationProvenance:
    kind: ProvenanceKind
    redacted_ref: str
    collector: str
    note: str
    redacted: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "redacted_ref": self.redacted_ref,
            "collector": self.collector,
            "note": self.note,
            "redacted": self.redacted,
        }


@dataclass(frozen=True)
class ProviderObservation:
    observation_id: str
    connection_id: str
    provider: str
    resource_id: str
    object_revision: str
    observed_at: datetime
    collector_version: str
    state: ObservationState
    normalized_value: dict[str, Any] | None
    provenance: ObservationProvenance
    source_version: str
    error_code: str | None = None
    safe_message: str | None = None
    signal: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "connection_id": self.connection_id,
            "provider": self.provider,
            "resource_id": self.resource_id,
            "signal": self.signal,
            "object_revision": self.object_revision,
            "observed_at": self.observed_at.isoformat(),
            "collector_version": self.collector_version,
            "state": self.state.value,
            "normalized_value": self.normalized_value,
            "provenance": self.provenance.to_dict(),
            "source_version": self.source_version,
            "error_code": self.error_code,
            "safe_message": self.safe_message,
        }


@dataclass(frozen=True)
class ProviderConnection:
    connection_id: str
    workspace_id: int | None
    provider: str
    external_account_id: str | None
    resource_scopes: tuple[str, ...]
    credential_ref: str | None
    capability_version: str
    cadence: str | None = None
    cursor: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "workspace_id": self.workspace_id,
            "provider": self.provider,
            "external_account_id": self.external_account_id,
            "resource_scopes": list(self.resource_scopes),
            "credential_ref": self.credential_ref,
            "capability_version": self.capability_version,
            "cadence": self.cadence,
            "cursor": self.cursor,
            "last_success_at": self.last_success_at,
            "last_error": self.last_error,
        }


def connection_id_for(
    workspace_id: int | None,
    provider: str,
    external_account_id: str | None,
) -> str:
    """Identity is workspace + provider + account, not source type alone."""
    account = external_account_id or "unbound"
    workspace = workspace_id if workspace_id is not None else "none"
    return f"conn:{workspace}:{provider}:{account}"


@dataclass(frozen=True)
class AdapterDescriptor:
    provider: str
    capability_version: str
    collector_version: str
    on_contract: bool
    accepts_success: bool
    live_collection: bool
    vendor_selected: bool
    default_state: ObservationState
    blocked_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "capability_version": self.capability_version,
            "collector_version": self.collector_version,
            "schema_version": SCHEMA_VERSION,
            "contract": CONTRACT_NAME,
            "on_contract": self.on_contract,
            "accepts_success": self.accepts_success,
            "live_collection": self.live_collection,
            "vendor_selected": self.vendor_selected,
            "default_state": self.default_state.value,
            "blocked_reason": self.blocked_reason,
        }


def observation_envelope(
    descriptor: AdapterDescriptor,
    observations: list[ProviderObservation],
    connection: ProviderConnection | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "contract": CONTRACT_NAME,
        "finding_status_vocabulary": FINDING_STATUS_VOCABULARY,
        "adapter": descriptor.to_dict(),
        "observations": [item.to_dict() for item in observations],
    }
    if connection is not None:
        body["connection"] = connection.to_dict()
    return body


def _marker_code(status: str) -> str | None:
    if status in {"check_required", "static", "static_catalog"}:
        return "check_required" if status == "check_required" else "static_catalog"
    if status == "demo":
        return "demo_value"
    if status == "seeded":
        return "seeded_value"
    return None


def value_claims_denied_marker(value: Any) -> str | None:
    """Return a rejection code when a value is static, demo, or seeded."""
    if value is None:
        return None
    if isinstance(value, str):
        return _marker_code(value.strip().lower()) or (
            "demo_value" if value.strip() in DEMO_EXTERNAL_IDS else None
        )
    if isinstance(value, Mapping):
        status = value.get("status")
        if isinstance(status, str):
            code = _marker_code(status.strip().lower())
            if code:
                return code
        if value.get("demo") is True:
            return "demo_value"
        if value.get("seeded") is True:
            return "seeded_value"
        external = value.get("external_id") or value.get("crm_external_id")
        if isinstance(external, str) and external in DEMO_EXTERNAL_IDS:
            return "demo_value"
        provenance = value.get("provenance")
        if isinstance(provenance, Mapping):
            kind = provenance.get("kind")
            if isinstance(kind, str):
                code = _marker_code(kind.strip().lower())
                if code:
                    return code
        for child in value.values():
            found = value_claims_denied_marker(child)
            if found:
                return found
        return None
    if isinstance(value, list):
        for item in value:
            found = value_claims_denied_marker(item)
            if found:
                return found
    return None


def rejection_code(observation: ProviderObservation) -> str | None:
    """Why this observation must not be stored as successful collected evidence."""
    demo_resource = observation.resource_id in DEMO_EXTERNAL_IDS
    demo_provenance = observation.provenance.kind is ProvenanceKind.DEMO
    if demo_resource or demo_provenance:
        return "demo_value"
    if observation.provenance.kind is ProvenanceKind.SEEDED:
        return "seeded_value"
    if observation.provenance.kind is ProvenanceKind.STATIC_CATALOG:
        return "static_catalog"
    marker = value_claims_denied_marker(observation.normalized_value)
    if marker:
        return marker
    if observation.provenance.kind in {ProvenanceKind.CREDENTIAL_CUSTODY, ProvenanceKind.ABSENT}:
        return "not_evidence"
    if observation.state is not ObservationState.SUCCESS:
        return "not_success"
    if not observation.normalized_value:
        return "empty_success"
    if not observation.provenance.redacted:
        return "unredacted_provenance"
    return None


def make_observation(
    *,
    provider: str,
    resource_id: str,
    state: ObservationState,
    provenance_kind: ProvenanceKind,
    workspace_id: int | None = None,
    external_account_id: str | None = None,
    object_revision: str = "unobserved",
    normalized_value: dict[str, Any] | None = None,
    error_code: str | None = None,
    safe_message: str | None = None,
    note: str = "",
    signal: str | None = None,
    credential_ref: str | None = None,
    credential_type: str | None = None,
    resource_scopes: tuple[str, ...] = (),
    cadence: str | None = None,
    source_versions: SourceVersionPort | None = None,
    key_purposes: KeyPurposePort | None = None,
    observed_at: datetime | None = None,
) -> tuple[ProviderObservation, ProviderConnection]:
    """Build one observation with a real id, timestamp, provenance and source version."""
    versions = source_versions or default_source_version
    purposes = key_purposes or default_key_purpose
    when = observed_at or utc_now()
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    public_value = normalized_value if state is ObservationState.SUCCESS else None
    if public_value is not None:
        public_value = redact_mapping(public_value)
    ref = credential_ref
    if ref is None and credential_type is not None:
        ref = purposes.credential_ref(
            workspace_id=workspace_id,
            source_type=provider,
            credential_type=credential_type,
        )
    connection = ProviderConnection(
        connection_id=connection_id_for(workspace_id, provider, external_account_id),
        workspace_id=workspace_id,
        provider=provider,
        external_account_id=external_account_id,
        resource_scopes=resource_scopes,
        credential_ref=ref,
        capability_version=CAPABILITY_VERSION,
        cadence=cadence,
    )
    source_version = versions.source_version(
        workspace_id=workspace_id,
        provider=provider,
        resource_id=resource_id,
        object_revision=object_revision,
    )
    provenance = ObservationProvenance(
        kind=provenance_kind,
        redacted_ref=provenance_digest(
            {"resource_id": resource_id, "value": public_value, "kind": provenance_kind.value}
        ),
        collector=COLLECTOR_VERSION,
        note=note,
        redacted=True,
    )
    observation = ProviderObservation(
        observation_id=new_observation_id(),
        connection_id=connection.connection_id,
        provider=provider,
        resource_id=resource_id,
        object_revision=object_revision,
        observed_at=when,
        collector_version=COLLECTOR_VERSION,
        state=state,
        normalized_value=public_value,
        provenance=provenance,
        source_version=source_version,
        error_code=error_code,
        safe_message=safe_message,
        signal=signal,
    )
    return observation, connection
