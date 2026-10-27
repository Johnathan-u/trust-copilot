"""TC-20-001 provider adapter and observation contract.

Uses hand-built fixtures only. No provider calls, credentials, or network.
"""

import json
import socket
from datetime import datetime, timezone

import pytest

from app.models.credential_store import CredentialStore
from app.models.source_registry import SourceRegistry
from app.services import aws_collector_service as aws
from app.services import cloud_connector_service as cloud
from app.services import connector_health_service as health
from app.services import connector_wizard_service as wizard
from app.services import credential_store_service as credentials
from app.services import crm_connector_service as crm
from app.services import source_registry_service as registry
from app.services.provider_adapter.adapters import (
    ADAPTERS,
    AWS,
    AWS_IAM,
    AWS_S3,
    HRIS,
    RecordedCollection,
    RecordedSignal,
    SignalSpec,
    describe_source,
)
from app.services.provider_adapter.contract import (
    SCHEMA_VERSION,
    ObservationState,
    ProvenanceKind,
    make_observation,
)
from app.services.provider_adapter.persistence import (
    CollectedEvidenceRejected,
    guard_ingest_payload,
    store_successful_observation,
)
from app.services.provider_adapter.seams import LocalKeyPurpose, MemorySideEffectIdempotency

_TYPED_NON_SUCCESS = {
    ObservationState.MISSING_PERMISSION,
    ObservationState.UNKNOWN,
    ObservationState.FAILURE,
    ObservationState.UNSUPPORTED,
}


class FakeSession:
    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        for index, obj in enumerate(self.added, start=1):
            if getattr(obj, "id", None) is None:
                obj.id = index


class ExplodingSession:
    def add(self, obj) -> None:
        raise AssertionError(f"demo sync persisted {obj!r}")

    def query(self, *args, **kwargs):
        raise AssertionError("demo sync queried the database")

    def flush(self) -> None:
        raise AssertionError("demo sync flushed")


def _reject(observation) -> str:
    session = FakeSession()
    with pytest.raises(CollectedEvidenceRejected) as caught:
        store_successful_observation(
            session,
            1,
            observation,
            idempotency=MemorySideEffectIdempotency(),
        )
    assert session.added == []
    return caught.value.code


def test_every_adapter_default_collection_is_typed_and_not_success():
    assert set(ADAPTERS) >= {
        "aws",
        "github",
        "google_workspace",
        "gcp",
        "azure",
        "gitlab",
        "okta",
        "hris",
        "slack",
        "gmail",
        "jira",
        "salesforce",
        "hubspot",
    }
    seen_ids: set[str] = set()
    for provider, adapter in ADAPTERS.items():
        collected = adapter.collect(workspace_id=7, external_account_id=f"{provider}-acct")
        envelope = collected["envelope"]
        assert envelope["schema_version"] == SCHEMA_VERSION
        assert envelope["contract"] == "provider-observation"
        assert envelope["adapter"]["live_collection"] is False
        assert envelope["adapter"]["on_contract"] is True
        assert collected["findings"]
        for observation in collected["observations"]:
            assert observation.observation_id.startswith("obs_")
            assert observation.observation_id not in seen_ids
            seen_ids.add(observation.observation_id)
            assert observation.observed_at.tzinfo is not None
            assert observation.provenance.redacted is True
            assert observation.provenance.redacted_ref.startswith("sha256:")
            assert observation.source_version.startswith("srcver:v0-local:")
            assert observation.collector_version == "tc-20-001/1"
            assert observation.state in _TYPED_NON_SUCCESS
            assert observation.state is not ObservationState.SUCCESS
            assert observation.normalized_value is None
            assert observation.connection_id.startswith(f"conn:7:{provider}:")
            assert _reject(observation)
        if provider == "hris":
            assert adapter.descriptor().vendor_selected is False
            assert adapter.descriptor().default_state is ObservationState.UNSUPPORTED
            assert all(
                item.state is ObservationState.UNSUPPORTED for item in collected["observations"]
            )


def test_connections_are_not_source_type_only():
    first = AWS.collect(workspace_id=1, external_account_id="111")
    second = AWS.collect(workspace_id=1, external_account_id="222")
    third = AWS.collect(workspace_id=2, external_account_id="111")
    assert first["observations"][0].connection_id != second["observations"][0].connection_id
    assert first["observations"][0].connection_id != third["observations"][0].connection_id


def test_recorded_success_has_identity_and_stores_once():
    recorded = RecordedCollection(
        signals=(
            RecordedSignal(
                signal="aws.s3.encryption",
                outcome=ObservationState.SUCCESS,
                value={"encryption": "AES256"},
                object_revision="rev-9",
                resource_id="arn:aws:s3:::example-bucket",
            ),
        )
    )
    collected = AWS.collect(
        workspace_id=3,
        external_account_id="us-east-1",
        signals=AWS_S3,
        recorded=recorded,
    )
    success = next(item for item in collected["observations"] if item.signal == "aws.s3.encryption")
    unknown = [item for item in collected["observations"] if item.signal != "aws.s3.encryption"]
    assert success.state is ObservationState.SUCCESS
    assert success.normalized_value == {"encryption": "AES256"}
    assert success.provenance.kind is ProvenanceKind.RECORDED
    assert success.object_revision == "rev-9"
    assert success.resource_id == "arn:aws:s3:::example-bucket"
    assert success.observed_at.tzinfo is not None
    assert unknown
    assert all(item.state is ObservationState.UNKNOWN for item in unknown)

    session = FakeSession()
    port = MemorySideEffectIdempotency()
    stored = store_successful_observation(
        session,
        3,
        success,
        idempotency_key="aws-s3-encryption",
        idempotency=port,
    )
    assert stored["stored"] is True
    assert stored["evidence_id"] == 1
    assert len(session.added) == 1
    metadata = json.loads(session.added[0].source_metadata)
    assert metadata["observation"]["state"] == "success"
    assert "secret" not in metadata["observation"]["provenance"]["redacted_ref"]
    duplicate = store_successful_observation(
        session,
        3,
        success,
        idempotency_key="aws-s3-encryption",
        idempotency=port,
    )
    assert duplicate["duplicate"] is True
    assert duplicate["stored"] is False
    assert len(session.added) == 1


def test_missing_permission_is_explicit_and_not_stored():
    recorded = RecordedCollection(
        signals=(
            RecordedSignal(
                signal="aws.iam.mfa_enabled",
                outcome=ObservationState.MISSING_PERMISSION,
                error_code="access_denied",
            ),
        )
    )
    collected = AWS.collect(workspace_id=4, signals=AWS_IAM, recorded=recorded)
    observation = next(
        item for item in collected["observations"] if item.signal == "aws.iam.mfa_enabled"
    )
    assert observation.state is ObservationState.MISSING_PERMISSION
    assert observation.error_code == "access_denied"
    assert observation.normalized_value is None
    assert _reject(observation) == "not_success"
    body = aws.collect_iam_posture("us-east-1", workspace_id=4, recorded=recorded)
    finding = next(item for item in body["findings"] if item["signal"] == "aws.iam.mfa_enabled")
    assert finding["status"] == "missing_permission"
    assert finding["observation_id"].startswith("obs_")


def test_unknown_is_explicit_and_not_stored():
    recorded = RecordedCollection(
        signals=(
            RecordedSignal(
                signal="aws.iam.password_policy",
                outcome=ObservationState.UNKNOWN,
                error_code="not_observed",
            ),
        )
    )
    collected = AWS.collect(workspace_id=4, signals=AWS_IAM, recorded=recorded)
    observation = next(
        item for item in collected["observations"] if item.signal == "aws.iam.password_policy"
    )
    assert observation.state is ObservationState.UNKNOWN
    assert observation.normalized_value is None
    assert _reject(observation) == "not_success"


def test_failure_is_explicit_and_not_stored():
    recorded = RecordedCollection(
        signals=(
            RecordedSignal(
                signal="aws.iam.root_access_key",
                outcome=ObservationState.FAILURE,
                error_code="provider_unavailable",
            ),
        )
    )
    collected = AWS.collect(workspace_id=4, signals=AWS_IAM, recorded=recorded)
    observation = next(
        item for item in collected["observations"] if item.signal == "aws.iam.root_access_key"
    )
    assert observation.state is ObservationState.FAILURE
    assert observation.error_code == "provider_unavailable"
    assert observation.normalized_value is None
    assert _reject(observation) == "not_success"


def test_check_required_demo_and_seeded_cannot_be_stored_as_success():
    check_required, _connection = make_observation(
        provider="aws",
        resource_id="aws.iam.mfa_enabled",
        signal="aws.iam.mfa_enabled",
        state=ObservationState.SUCCESS,
        provenance_kind=ProvenanceKind.RECORDED,
        workspace_id=1,
        object_revision="rev-1",
        normalized_value={"status": "check_required"},
    )
    assert _reject(check_required) == "check_required"

    demo, _connection = make_observation(
        provider="salesforce",
        resource_id="sf-opp-001",
        signal="salesforce.opportunity",
        state=ObservationState.SUCCESS,
        provenance_kind=ProvenanceKind.DEMO,
        workspace_id=1,
        object_revision="demo",
        normalized_value={"external_id": "sf-opp-001", "demo": True},
    )
    assert _reject(demo) == "demo_value"

    seeded, _connection = make_observation(
        provider="aws",
        resource_id="aws.s3.versioning",
        signal="aws.s3.versioning",
        state=ObservationState.SUCCESS,
        provenance_kind=ProvenanceKind.SEEDED,
        workspace_id=1,
        object_revision="seed",
        normalized_value={"versioning": True, "seeded": True},
    )
    assert _reject(seeded) == "seeded_value"

    catalog = AWS.collect(
        workspace_id=1,
        signals=(SignalSpec("aws.s3.encryption", "Default encryption"),),
    )
    assert _reject(catalog["observations"][0]) == "static_catalog"


def test_adapter_downgrades_static_success_before_return():
    recorded = RecordedCollection(
        signals=(
            RecordedSignal(
                signal="aws.s3.encryption",
                outcome=ObservationState.SUCCESS,
                value={"status": "check_required"},
            ),
        )
    )
    collected = AWS.collect(
        signals=(SignalSpec("aws.s3.encryption", "Default encryption"),),
        recorded=recorded,
    )
    assert collected["observations"][0].state is ObservationState.UNKNOWN
    assert collected["findings"][0]["status"] != "check_required"
    assert collected["findings"][0]["status"] != "success"


def test_demo_crm_fixtures_are_rejected_without_persistence():
    salesforce = crm.sync_salesforce(ExplodingSession(), 9)
    hubspot = crm.sync_hubspot(ExplodingSession(), 9)
    assert salesforce["synced"] == 0
    assert hubspot["synced"] == 0
    assert {item["external_id"] for item in salesforce["details"]} == {"sf-opp-001", "sf-opp-002"}
    assert {item["external_id"] for item in hubspot["details"]} == {"hs-deal-001"}
    combined = salesforce["details"] + hubspot["details"]
    assert all(item["reason"] == "demo_value" for item in combined)
    for body in (salesforce, hubspot):
        observations = body["observation_contract"]["observations"]
        assert observations
        assert {item["state"] for item in observations} == {"unknown"}
        assert {item["provenance"]["kind"] for item in observations} == {"demo"}
        assert all(item["observation_id"].startswith("obs_") for item in observations)


def test_hris_stays_unsupported_when_a_vendor_name_or_success_fixture_is_supplied():
    body = cloud.collect_hris("BambooHR", workspace_id=5)
    assert body["source"] == "hris"
    assert body["provider"] == "BambooHR"
    assert {item["status"] for item in body["findings"]} == {"unsupported"}
    adapter = body["observation_contract"]["adapter"]
    assert adapter["vendor_selected"] is False
    assert adapter["accepts_success"] is False
    assert adapter["blocked_reason"]
    assert "TC-20-005" in adapter["blocked_reason"]
    assert body["observation_contract"]["connection"]["external_account_id"] is None
    recorded = RecordedCollection(
        signals=(
            RecordedSignal(
                signal="hris.background_checks",
                outcome=ObservationState.SUCCESS,
                value={"complete": True},
                resource_id="workforce-1",
            ),
        )
    )
    collected = HRIS.collect(workspace_id=5, recorded=recorded)
    assert all(item.state is ObservationState.UNSUPPORTED for item in collected["observations"])
    assert all(_reject(item) for item in collected["observations"])


def test_ingest_boundary_rejects_static_demo_and_seeded_claims():
    guard_ingest_payload(title="Test Evidence", source_metadata=None)
    guard_ingest_payload(title="Batch 1", source_metadata=None)
    with pytest.raises(CollectedEvidenceRejected) as check_required:
        guard_ingest_payload(title="signal", source_metadata='{"status": "check_required"}')
    assert check_required.value.code == "check_required"
    with pytest.raises(CollectedEvidenceRejected) as demo:
        guard_ingest_payload(title="signal", source_metadata='{"demo": true}')
    assert demo.value.code == "demo_value"
    with pytest.raises(CollectedEvidenceRejected) as seeded:
        guard_ingest_payload(title="signal", source_metadata='{"seeded": true}')
    assert seeded.value.code == "seeded_value"
    with pytest.raises(CollectedEvidenceRejected) as claimed:
        guard_ingest_payload(
            title="signal",
            source_metadata='{"observation_id": "obs_client", "state": "success"}',
        )
    assert claimed.value.code == "not_success"


def test_listed_surfaces_use_the_same_contract():
    catalog = wizard.get_catalog()
    assert len(catalog) >= 8
    for item in catalog:
        contract = item["adapter_contract"]
        assert contract["schema_version"] == SCHEMA_VERSION
        assert contract["on_contract"] is True
        assert contract["live_collection"] is False
    details = wizard.get_connector_details("aws")
    assert details["adapter_contract"]["provider"] == "aws"
    for source in registry.KNOWN_SOURCES:
        described = describe_source(source["source_type"])
        assert described["schema_version"] == SCHEMA_VERSION
        assert described["live_collection"] is False
    hris = describe_source("hris")
    assert hris["default_state"] == "unsupported"
    assert hris["vendor_selected"] is False

    seeded = registry.registry_observation(1, "seed")
    assert seeded["observations"][0]["state"] == "unknown"
    assert seeded["observations"][0]["provenance"]["kind"] == "seeded"

    row = CredentialStore(
        workspace_id=1,
        source_type="slack",
        credential_type="bot_token",
        encrypted_value="ciphertext-not-a-secret-field",
        status="active",
    )
    serialized = credentials._serialize(row, include_value=False)
    blob = json.dumps(serialized)
    assert "value" not in serialized
    assert "ciphertext-not-a-secret-field" not in blob
    custody = serialized["observation_contract"]["observations"][0]
    assert custody["state"] == "unknown"
    assert custody["provenance"]["kind"] == "credential_custody"
    assert custody["observation_id"].startswith("obs_")
    ref = serialized["observation_contract"]["connection"]["credential_ref"]
    assert ref.startswith("key-purpose:connector_encryption:v0:")
    assert "ciphertext" not in ref

    healthy = SourceRegistry(
        workspace_id=1,
        source_type="slack",
        display_name="Slack",
        enabled=True,
        last_sync_status="success",
        last_sync_at=datetime.now(timezone.utc),
        sync_cadence="daily",
    )
    posture = health.evidence_posture(healthy)
    assert posture["state"] == "unknown"
    assert posture["reason"] == "sync_bookkeeping_is_not_collected_evidence"
    failed = SourceRegistry(
        workspace_id=1,
        source_type="gmail",
        display_name="Gmail",
        enabled=True,
        last_sync_status="failed",
        last_sync_at=datetime.now(timezone.utc),
        sync_cadence="daily",
    )
    failed_posture = health.evidence_posture(failed)
    assert failed_posture["state"] == "failure"
    assert failed_posture["observation_id"].startswith("obs_")


def test_key_purpose_seam_does_not_carry_secret_material():
    secret = "xoxb-test-token-should-not-leak"
    ref = LocalKeyPurpose().credential_ref(
        workspace_id=1,
        source_type="slack",
        credential_type="bot_token",
    )
    assert secret not in ref
    assert ref.startswith("key-purpose:connector_encryption:v0:ws:1:slack:bot_token")


def test_authentication_does_not_echo_secrets_or_claim_provider_success():
    secret_key = "AKIA_LOCAL_SHAPE_ONLY"
    secret_value = "local-shape-secret"
    present = aws.authenticate_aws(secret_key, secret_value, workspace_id=1)
    blob = json.dumps(present)
    assert secret_key not in blob
    assert secret_value not in blob
    assert present["authenticated"] is True
    assert present["observation_contract"]["observations"][0]["state"] == "unknown"
    missing = aws.authenticate_aws()
    assert missing["authenticated"] is False
    assert missing["observation_contract"]["observations"][0]["state"] == "missing_permission"


def test_default_collectors_do_not_open_sockets(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("provider adapter opened a socket")

    monkeypatch.setattr(socket, "socket", blocked)
    aws.collect_iam_posture("us-east-1", workspace_id=1)
    cloud.collect_gcp("proj", workspace_id=1)
    cloud.collect_hris("BambooHR", workspace_id=1)
    crm.sync_salesforce(ExplodingSession(), 1)
    wizard.get_catalog()
