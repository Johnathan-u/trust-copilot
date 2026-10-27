"""Catalog adapters. No network calls and no credential material.

Default collection is an explicit unknown (or unsupported) observation per
signal. A recorded fixture may produce success, missing permission, unknown,
or failure. HRIS never accepts success: TC-20-005 is BLOCKED.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.provider_adapter.contract import (
    CAPABILITY_VERSION,
    COLLECTOR_VERSION,
    AdapterDescriptor,
    ObservationState,
    ProvenanceKind,
    ProviderObservation,
    make_observation,
    observation_envelope,
    value_claims_denied_marker,
)

HRIS_BLOCKED_REASON = (
    "TC-20-005 BLOCKED: no HRIS vendor is selected. A caller-supplied name is not a vendor choice."
)


@dataclass(frozen=True)
class SignalSpec:
    signal: str
    description: str


@dataclass(frozen=True)
class RecordedSignal:
    signal: str
    outcome: ObservationState
    value: dict | None = None
    error_code: str | None = None
    object_revision: str = "recorded-1"
    resource_id: str | None = None
    provenance_kind: ProvenanceKind = ProvenanceKind.RECORDED
    safe_message: str | None = None


@dataclass(frozen=True)
class RecordedCollection:
    signals: tuple[RecordedSignal, ...]
    external_account_id: str | None = None


@dataclass(frozen=True)
class CatalogAdapter:
    provider: str
    signals: tuple[SignalSpec, ...]
    accepts_success: bool = True
    vendor_selected: bool = True
    forced_state: ObservationState | None = None
    blocked_reason: str | None = None
    role: str = "provider"

    def descriptor(self) -> AdapterDescriptor:
        default = self.forced_state or ObservationState.UNKNOWN
        return AdapterDescriptor(
            provider=self.provider,
            capability_version=CAPABILITY_VERSION,
            collector_version=COLLECTOR_VERSION,
            on_contract=True,
            accepts_success=self.accepts_success and self.forced_state is None,
            live_collection=False,
            vendor_selected=self.vendor_selected,
            default_state=default,
            blocked_reason=self.blocked_reason,
        )

    def collect(
        self,
        *,
        workspace_id: int | None = None,
        external_account_id: str | None = None,
        signals: tuple[SignalSpec, ...] | None = None,
        recorded: RecordedCollection | None = None,
        credential_ref: str | None = None,
        cadence: str | None = None,
    ) -> dict:
        chosen = signals or self.signals
        recorded_by_signal = {}
        if recorded is not None:
            recorded_by_signal = {item.signal: item for item in recorded.signals}
            if recorded.external_account_id and external_account_id is None:
                external_account_id = recorded.external_account_id
        observations: list[ProviderObservation] = []
        connection = None
        for spec in chosen:
            observation, connection = self._one(
                spec,
                recorded_by_signal.get(spec.signal),
                workspace_id=workspace_id,
                external_account_id=external_account_id,
                credential_ref=credential_ref,
                cadence=cadence,
                scopes=tuple(item.signal for item in chosen),
            )
            observations.append(observation)
        envelope = observation_envelope(self.descriptor(), observations, connection)
        return {
            "observations": observations,
            "envelope": envelope,
            "findings": [
                _finding(spec, obs) for spec, obs in zip(chosen, observations, strict=True)
            ],
        }

    def _one(
        self,
        spec: SignalSpec,
        recorded: RecordedSignal | None,
        *,
        workspace_id: int | None,
        external_account_id: str | None,
        credential_ref: str | None,
        cadence: str | None,
        scopes: tuple[str, ...],
    ) -> tuple[ProviderObservation, object]:
        if self.forced_state is not None:
            return make_observation(
                provider=self.provider,
                resource_id=spec.signal,
                signal=spec.signal,
                state=self.forced_state,
                provenance_kind=ProvenanceKind.ABSENT,
                workspace_id=workspace_id,
                external_account_id=external_account_id,
                object_revision="unobserved",
                error_code="vendor_unselected",
                safe_message=self.blocked_reason,
                note=self.blocked_reason or "",
                credential_ref=credential_ref,
                resource_scopes=scopes,
                cadence=cadence,
            )
        if recorded is None:
            return make_observation(
                provider=self.provider,
                resource_id=spec.signal,
                signal=spec.signal,
                state=ObservationState.UNKNOWN,
                provenance_kind=ProvenanceKind.STATIC_CATALOG,
                workspace_id=workspace_id,
                external_account_id=external_account_id,
                object_revision="unobserved",
                error_code="not_observed",
                safe_message="No recorded collection for this signal",
                note="Static catalog signal is not collected evidence",
                credential_ref=credential_ref,
                resource_scopes=scopes,
                cadence=cadence,
            )
        return _from_recorded(
            self,
            spec,
            recorded,
            workspace_id=workspace_id,
            external_account_id=external_account_id,
            credential_ref=credential_ref,
            cadence=cadence,
            scopes=scopes,
        )


def _from_recorded(
    adapter: CatalogAdapter,
    spec: SignalSpec,
    recorded: RecordedSignal,
    *,
    workspace_id: int | None,
    external_account_id: str | None,
    credential_ref: str | None,
    cadence: str | None,
    scopes: tuple[str, ...],
) -> tuple[ProviderObservation, object]:
    state = recorded.outcome
    provenance = recorded.provenance_kind
    value = recorded.value
    error_code = recorded.error_code
    message = recorded.safe_message
    revision = recorded.object_revision
    resource_id = recorded.resource_id or spec.signal
    if not adapter.accepts_success and state is ObservationState.SUCCESS:
        state = ObservationState.UNKNOWN
        provenance = ProvenanceKind.ABSENT
        value = None
        error_code = "success_not_accepted"
        message = adapter.blocked_reason or "Adapter does not accept success observations"
        revision = "unobserved"
    elif state is ObservationState.SUCCESS:
        marker = value_claims_denied_marker(value)
        denied_provenance = provenance in {
            ProvenanceKind.DEMO,
            ProvenanceKind.SEEDED,
            ProvenanceKind.STATIC_CATALOG,
            ProvenanceKind.CREDENTIAL_CUSTODY,
            ProvenanceKind.ABSENT,
        }
        if marker or denied_provenance or not value:
            state = ObservationState.UNKNOWN
            provenance = provenance if denied_provenance else ProvenanceKind.ABSENT
            error_code = marker or ("empty_success" if not value else "not_evidence")
            message = "Recorded success was rejected before it could be returned as success"
            value = None
            revision = "unobserved"
    else:
        value = None
        if error_code is None:
            error_code = _default_error(state)
    return make_observation(
        provider=adapter.provider,
        resource_id=resource_id,
        signal=spec.signal,
        state=state,
        provenance_kind=provenance,
        workspace_id=workspace_id,
        external_account_id=external_account_id,
        object_revision=revision,
        normalized_value=value,
        error_code=error_code,
        safe_message=message,
        note="Recorded fixture; provider was not contacted",
        credential_ref=credential_ref,
        resource_scopes=scopes,
        cadence=cadence,
    )


def _default_error(state: ObservationState) -> str:
    if state is ObservationState.MISSING_PERMISSION:
        return "missing_permission"
    if state is ObservationState.FAILURE:
        return "provider_failure"
    if state is ObservationState.UNKNOWN:
        return "not_observed"
    if state is ObservationState.UNSUPPORTED:
        return "vendor_unselected"
    return "not_success"


def _finding(spec: SignalSpec, observation: ProviderObservation) -> dict:
    return {
        "signal": spec.signal,
        "description": spec.description,
        "status": observation.state.value,
        "observation_id": observation.observation_id,
        "observed_at": observation.observed_at.isoformat(),
        "object_revision": observation.object_revision,
        "provenance": observation.provenance.to_dict(),
        "source_version": observation.source_version,
        "error_code": observation.error_code,
    }


def legacy_collection(
    adapter: CatalogAdapter,
    *,
    source: str,
    scope_fields: dict,
    workspace_id: int | None = None,
    external_account_id: str | None = None,
    signals: tuple[SignalSpec, ...] | None = None,
    recorded: RecordedCollection | None = None,
) -> dict:
    collected = adapter.collect(
        workspace_id=workspace_id,
        external_account_id=external_account_id,
        signals=signals,
        recorded=recorded,
    )
    observed_at = collected["findings"][0]["observed_at"] if collected["findings"] else None
    body = {
        "source": source,
        **scope_fields,
        "collected_at": observed_at,
        "findings": collected["findings"],
        "observation_contract": collected["envelope"],
    }
    return body


def merge_observations(parts: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for part in parts:
        contract = part.get("observation_contract") or {}
        merged.extend(contract.get("observations") or [])
    return merged


AWS_IAM = (
    SignalSpec("aws.iam.mfa_enabled", "MFA enforcement status"),
    SignalSpec("aws.iam.password_policy", "Password policy compliance"),
    SignalSpec("aws.iam.root_access_key", "Root account access key"),
)
AWS_S3 = (
    SignalSpec("aws.s3.public_access", "Public access block status"),
    SignalSpec("aws.s3.encryption", "Default encryption"),
    SignalSpec("aws.s3.versioning", "Versioning enabled"),
)
AWS_LOGGING = (
    SignalSpec("aws.cloudtrail.enabled", "CloudTrail enabled"),
    SignalSpec("aws.cloudtrail.multi_region", "Multi-region trails"),
)
GITHUB_REPOS = (
    SignalSpec("github.repo_count", "Total repositories"),
    SignalSpec("github.private_repos", "Private repos ratio"),
    SignalSpec("github.archived_repos", "Archived repos"),
)
GITHUB_ACCESS = (
    SignalSpec("github.2fa_required", "2FA enforcement"),
    SignalSpec("github.outside_collaborators", "Outside collaborators count"),
    SignalSpec("github.sso_enforced", "SSO enforcement"),
)
GITHUB_PROTECTION = (
    SignalSpec("github.branch_protection", "Default branch protection enabled"),
    SignalSpec("github.code_review_required", "Required code reviews"),
    SignalSpec("github.vulnerability_alerts", "Vulnerability alerts enabled"),
    SignalSpec("github.secret_scanning", "Secret scanning enabled"),
)
GOOGLE_USERS = (
    SignalSpec("google.total_users", "Total user accounts"),
    SignalSpec("google.suspended_users", "Suspended accounts"),
    SignalSpec("google.sso_configured", "SSO configuration"),
)
GOOGLE_MFA = (
    SignalSpec("google.mfa_enrollment", "MFA enrollment rate"),
    SignalSpec("google.password_policy", "Password policy strength"),
)
GOOGLE_ROLES = (
    SignalSpec("google.admin_roles", "Admin role assignments"),
    SignalSpec("google.super_admins", "Super admin count"),
)
GCP_SIGNALS = (
    SignalSpec("gcp.iam_audit", "IAM audit logging"),
    SignalSpec("gcp.service_account_keys", "Service account key rotation"),
    SignalSpec("gcp.vpc_flow_logs", "VPC flow logs enabled"),
    SignalSpec("gcp.encryption_at_rest", "Encryption at rest (CMEK)"),
)
AZURE_SIGNALS = (
    SignalSpec("azure.mfa_enabled", "MFA enforcement"),
    SignalSpec("azure.conditional_access", "Conditional access policies"),
    SignalSpec("azure.security_center", "Security Center score"),
    SignalSpec("azure.key_vault", "Key Vault usage"),
)
GITLAB_SIGNALS = (
    SignalSpec("gitlab.branch_protection", "Protected branches"),
    SignalSpec("gitlab.merge_request_approvals", "MR approval rules"),
    SignalSpec("gitlab.2fa_enforcement", "2FA enforcement"),
    SignalSpec("gitlab.container_scanning", "Container scanning enabled"),
)
OKTA_SIGNALS = (
    SignalSpec("okta.mfa_policy", "MFA policy enforcement"),
    SignalSpec("okta.session_policy", "Session lifetime policy"),
    SignalSpec("okta.password_policy", "Password policy strength"),
    SignalSpec("okta.api_tokens", "API token hygiene"),
)
HRIS_SIGNALS = (
    SignalSpec("hris.employee_offboarding", "Offboarding process compliance"),
    SignalSpec("hris.background_checks", "Background check status"),
    SignalSpec("hris.security_training", "Security awareness training completion"),
)
SLACK_SIGNALS = (
    SignalSpec("slack.channels", "Channel list"),
    SignalSpec("slack.membership", "Membership metadata"),
)
GMAIL_SIGNALS = (
    SignalSpec("gmail.labels", "Label metadata"),
    SignalSpec("gmail.messages", "Message metadata"),
)
JIRA_SIGNALS = (
    SignalSpec("jira.security_tickets", "Security tickets"),
    SignalSpec("jira.incidents", "Incident records"),
)
SALESFORCE_SIGNALS = (SignalSpec("salesforce.opportunity", "Opportunity sync"),)
HUBSPOT_SIGNALS = (SignalSpec("hubspot.deal", "Deal sync"),)
MANUAL_SIGNALS = (SignalSpec("manual.upload", "Manual upload"),)

AWS = CatalogAdapter("aws", AWS_IAM + AWS_S3 + AWS_LOGGING)
GITHUB = CatalogAdapter("github", GITHUB_REPOS + GITHUB_ACCESS + GITHUB_PROTECTION)
GOOGLE = CatalogAdapter("google_workspace", GOOGLE_USERS + GOOGLE_MFA + GOOGLE_ROLES)
GCP = CatalogAdapter("gcp", GCP_SIGNALS)
AZURE = CatalogAdapter("azure", AZURE_SIGNALS)
GITLAB = CatalogAdapter("gitlab", GITLAB_SIGNALS)
OKTA = CatalogAdapter("okta", OKTA_SIGNALS)
HRIS = CatalogAdapter(
    "hris",
    HRIS_SIGNALS,
    accepts_success=False,
    vendor_selected=False,
    forced_state=ObservationState.UNSUPPORTED,
    blocked_reason=HRIS_BLOCKED_REASON,
    role="blocked_vendor",
)
SLACK = CatalogAdapter("slack", SLACK_SIGNALS)
GMAIL = CatalogAdapter("gmail", GMAIL_SIGNALS)
JIRA = CatalogAdapter("jira", JIRA_SIGNALS)
SALESFORCE = CatalogAdapter("salesforce", SALESFORCE_SIGNALS, role="crm")
HUBSPOT = CatalogAdapter("hubspot", HUBSPOT_SIGNALS, role="crm")
MANUAL = CatalogAdapter(
    "manual",
    MANUAL_SIGNALS,
    accepts_success=False,
    role="local_intake",
    blocked_reason="Manual intake is not a provider observation",
)

ADAPTERS: dict[str, CatalogAdapter] = {
    adapter.provider: adapter
    for adapter in (
        AWS,
        GITHUB,
        GOOGLE,
        GCP,
        AZURE,
        GITLAB,
        OKTA,
        HRIS,
        SLACK,
        GMAIL,
        JIRA,
        SALESFORCE,
        HUBSPOT,
        MANUAL,
    )
}


def get_adapter(provider: str) -> CatalogAdapter | None:
    return ADAPTERS.get(provider)


def describe_source(source_type: str) -> dict:
    adapter = ADAPTERS.get(source_type)
    if adapter is not None:
        body = adapter.descriptor().to_dict()
        body["role"] = adapter.role
        return body
    return AdapterDescriptor(
        provider=source_type,
        capability_version=CAPABILITY_VERSION,
        collector_version=COLLECTOR_VERSION,
        on_contract=True,
        accepts_success=False,
        live_collection=False,
        vendor_selected=False,
        default_state=ObservationState.UNKNOWN,
        blocked_reason="No adapter is registered for this source type",
    ).to_dict()
