"""Least-privilege scopes for connector permission probes.

Verify, connect, and rotate use the same read-only calls. Revoke destroys the
local ciphertext and requests no provider scope. Collection scopes in the
wizard catalog are broader; this table is only the probe.
"""

from __future__ import annotations

from dataclasses import dataclass

SOURCE_ALIASES = {"google": "google_workspace"}

DEFAULT_CREDENTIAL_TYPE = {
    "aws": "access_key",
    "github": "personal_token",
    "google_workspace": "oauth_token",
    "gcp": "oauth_token",
    "azure": "oauth_token",
    "gitlab": "personal_token",
    "okta": "api_token",
    "salesforce": "oauth_token",
    "hubspot": "private_app_token",
    "slack": "bot_token",
    "gmail": "oauth_token",
    "hris": "api_token",
}


@dataclass(frozen=True)
class ProbeSpec:
    source_type: str
    scopes: tuple[str, ...]
    calls: tuple[str, ...]
    kind: str  # aws, http, slack, gmail, unsupported
    header: str = "bearer"
    needs_account: bool = False
    needs_base: bool = False
    account_is_host: bool = False


def _http(
    source: str,
    scopes: tuple[str, ...],
    calls: tuple[str, ...],
    *,
    header: str = "bearer",
    needs_account: bool = False,
    needs_base: bool = False,
    account_is_host: bool = False,
) -> ProbeSpec:
    return ProbeSpec(
        source_type=source,
        scopes=scopes,
        calls=calls,
        kind="http",
        header=header,
        needs_account=needs_account,
        needs_base=needs_base,
        account_is_host=account_is_host,
    )


PROBES: dict[str, ProbeSpec] = {
    "aws": ProbeSpec(
        source_type="aws",
        scopes=("sts:GetCallerIdentity", "iam:GetAccountSummary"),
        calls=("sts:GetCallerIdentity", "iam:GetAccountSummary"),
        kind="aws",
    ),
    "github": _http(
        "github",
        ("read:org",),
        (
            "GET https://api.github.com/user",
            "GET https://api.github.com/user/orgs?per_page=1",
        ),
        header="github",
    ),
    "google_workspace": _http(
        "google_workspace",
        ("https://www.googleapis.com/auth/admin.directory.user.readonly",),
        (
            "GET https://admin.googleapis.com/admin/directory/v1/users"
            "?customer=my_customer&maxResults=1",
        ),
    ),
    "gcp": _http(
        "gcp",
        ("https://www.googleapis.com/auth/cloudplatformprojects.readonly",),
        ("GET https://cloudresourcemanager.googleapis.com/v1/projects/{account}",),
        needs_account=True,
    ),
    "azure": _http(
        "azure",
        ("Organization.Read.All",),
        ("GET https://graph.microsoft.com/v1.0/organization?$select=id",),
    ),
    "gitlab": _http(
        "gitlab",
        ("read_api",),
        ("GET {base}/api/v4/user", "GET {base}/api/v4/groups?per_page=1"),
        header="private-token",
        needs_base=True,
    ),
    "okta": _http(
        "okta",
        ("okta.users.read",),
        ("GET https://{account}/api/v1/users?limit=1",),
        header="ssws",
        needs_account=True,
        account_is_host=True,
    ),
    "salesforce": _http(
        "salesforce",
        ("api",),
        (
            "GET {base}/services/oauth2/userinfo",
            "GET {base}/services/data/v59.0/sobjects/Opportunity/describe",
        ),
        needs_base=True,
    ),
    "hubspot": _http(
        "hubspot",
        ("crm.objects.deals.read",),
        ("GET https://api.hubapi.com/crm/v3/objects/deals?limit=1",),
    ),
    "slack": ProbeSpec(
        source_type="slack",
        scopes=("channels:read",),
        calls=(
            "POST https://slack.com/api/auth.test",
            "GET https://slack.com/api/conversations.list",
        ),
        kind="slack",
    ),
    "gmail": ProbeSpec(
        source_type="gmail",
        scopes=("https://www.googleapis.com/auth/gmail.readonly",),
        calls=(
            "GET https://gmail.googleapis.com/gmail/v1/users/me/profile",
            "GET https://gmail.googleapis.com/gmail/v1/users/me/labels",
        ),
        kind="gmail",
    ),
    "hris": ProbeSpec(
        source_type="hris",
        scopes=(),
        calls=(),
        kind="unsupported",
    ),
}

KNOWN_SOURCES = frozenset(PROBES)
CLOUD_SOURCES = frozenset({"gcp", "azure", "gitlab", "okta", "hris"})
CRM_SOURCES = frozenset({"salesforce", "hubspot"})


def canonical_source(source_type: str) -> str:
    return SOURCE_ALIASES.get(source_type, source_type)


def default_credential_type(source_type: str) -> str:
    return DEFAULT_CREDENTIAL_TYPE.get(canonical_source(source_type), "api_token")


def probe_spec(source_type: str) -> ProbeSpec | None:
    return PROBES.get(canonical_source(source_type))


def least_privilege(source_type: str) -> dict:
    """Additive catalog field. Revoke never asks the provider for a scope."""
    source = canonical_source(source_type)
    spec = PROBES.get(source)
    if spec is None:
        return {
            "source_type": source,
            "verify_scopes": [],
            "verify_calls": [],
            "revoke_scopes": [],
            "revoke_calls": ["Destroy the local ciphertext. No provider call."],
        }
    return {
        "source_type": source,
        "verify_scopes": list(spec.scopes),
        "verify_calls": list(spec.calls),
        "revoke_scopes": [],
        "revoke_calls": ["Destroy the local ciphertext. No provider call."],
    }
