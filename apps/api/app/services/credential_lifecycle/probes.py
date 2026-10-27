"""Read-only permission probes. Success is custody metadata, not evidence.

Under TRUST_COPILOT_TESTING=1 a probe does not open a socket unless the caller
injects an httpx transport or a botocore client factory. A missing injection
is ``failure`` / ``live_probe_disabled``, never a hardcoded success.
"""

from __future__ import annotations

import contextvars
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.services.credential_lifecycle.scopes import ProbeSpec, canonical_source, probe_spec
from app.services.provider_adapter.contract import (
    ObservationState,
    ProvenanceKind,
    make_observation,
)

_transport_ctx: contextvars.ContextVar[httpx.BaseTransport | None] = contextvars.ContextVar(
    "tc20002_probe_transport",
    default=None,
)
_aws_ctx: contextvars.ContextVar[object | None] = contextvars.ContextVar(
    "tc20002_aws_factory",
    default=None,
)

_AWS_EXPIRED = frozenset({"ExpiredToken", "ExpiredTokenException", "RequestExpired"})
_AWS_REVOKED = frozenset(
    {
        "InvalidClientTokenId",
        "UnrecognizedClientException",
        "AuthFailure",
        "SignatureDoesNotMatch",
    }
)
_AWS_DENIED = frozenset({"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"})
_HOST_RE = re.compile(r"[a-z0-9.-]{1,253}")
_PROJECT_RE = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")

_MESSAGES = {
    "ok": "Read-only permission probe succeeded.",
    "missing_permission": "The credential is missing a required permission.",
    "credential_expired": "The credential is expired.",
    "credential_revoked": "The credential was rejected by the provider.",
    "provider_failure": "The provider probe failed.",
    "missing_credentials": "A required credential field is missing.",
    "live_probe_disabled": "Live provider probes are disabled in this process.",
    "vendor_not_selected": "No HRIS vendor is selected.",
    "unsupported_connector": "This connector has no permission probe.",
}


@dataclass(frozen=True)
class ProbeOutcome:
    state: str
    error_code: str | None
    safe_message: str
    observation: dict
    scopes: tuple[str, ...]


class probe_overrides:
    """Test-only injection. Ignored unless TRUST_COPILOT_TESTING=1."""

    def __init__(self, transport=None, aws_factory=None) -> None:
        self._transport = transport
        self._aws_factory = aws_factory
        self._tokens: tuple[contextvars.Token, contextvars.Token] | None = None

    def __enter__(self) -> probe_overrides:
        self._tokens = (
            _transport_ctx.set(self._transport),
            _aws_ctx.set(self._aws_factory),
        )
        return self

    def __exit__(self, *exc: object) -> None:
        if self._tokens is not None:
            _transport_ctx.reset(self._tokens[0])
            _aws_ctx.reset(self._tokens[1])


def _testing() -> bool:
    return os.environ.get("TRUST_COPILOT_TESTING") == "1"


def _injected_transport(explicit: httpx.BaseTransport | None) -> httpx.BaseTransport | None:
    if explicit is not None:
        return explicit
    if _testing():
        return _transport_ctx.get()
    return None


def _injected_aws(explicit):
    if explicit is not None:
        return explicit
    if _testing():
        return _aws_ctx.get()
    return None


def _finish(
    source_type: str,
    action: str,
    workspace_id: int,
    credential_type: str,
    *,
    state: ObservationState,
    error_code: str | None,
    scopes: tuple[str, ...],
) -> ProbeOutcome:
    message = _MESSAGES["ok" if error_code is None else error_code]
    normalized = (
        {"probe": "read_only", "action": action} if state is ObservationState.SUCCESS else None
    )
    observation, _connection = make_observation(
        provider=source_type,
        resource_id=f"credential-probe:{source_type}:{action}",
        state=state,
        provenance_kind=ProvenanceKind.CREDENTIAL_CUSTODY,
        workspace_id=workspace_id,
        credential_type=credential_type,
        error_code=error_code,
        safe_message=message,
        normalized_value=normalized,
        resource_scopes=scopes,
        note="read_only_permission_probe",
    )
    return ProbeOutcome(state.value, error_code, message, observation.to_dict(), scopes)


def _failure(source, action, workspace_id, credential_type, code, scopes) -> ProbeOutcome:
    return _finish(
        source,
        action,
        workspace_id,
        credential_type,
        state=ObservationState.FAILURE,
        error_code=code,
        scopes=scopes,
    )


def _missing(source, action, workspace_id, credential_type, scopes) -> ProbeOutcome:
    return _finish(
        source,
        action,
        workspace_id,
        credential_type,
        state=ObservationState.MISSING_PERMISSION,
        error_code="missing_permission",
        scopes=scopes,
    )


def _unsupported(source, action, workspace_id, credential_type, code, scopes) -> ProbeOutcome:
    return _finish(
        source,
        action,
        workspace_id,
        credential_type,
        state=ObservationState.UNSUPPORTED,
        error_code=code,
        scopes=scopes,
    )


def _https_base(base: str | None) -> str | None:
    if not base or not isinstance(base, str):
        return None
    parts = urlsplit(base.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password:
        return None
    if parts.port:
        host = f"{host}:{parts.port}"
    path = parts.path.rstrip("/")
    return f"https://{host}{path}"


def _account_host(account: str | None) -> str | None:
    if not account or not isinstance(account, str):
        return None
    host = account.strip().lower()
    if "://" in host or "/" in host or "@" in host or not _HOST_RE.fullmatch(host):
        return None
    return host


def _project_id(account: str | None) -> str | None:
    if not account or not isinstance(account, str):
        return None
    if not _PROJECT_RE.fullmatch(account):
        return None
    return account


def _headers(style: str, secret: str) -> dict[str, str]:
    if style == "github":
        return {
            "Authorization": f"Bearer {secret}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "trust-copilot-probe",
        }
    if style == "private-token":
        return {"PRIVATE-TOKEN": secret}
    if style == "ssws":
        return {"Authorization": f"SSWS {secret}"}
    return {"Authorization": f"Bearer {secret}"}


def _classify_http(response: httpx.Response) -> str | None:
    """Return an error code, or None when the call may continue. Never copies the body."""
    status = response.status_code
    if 200 <= status < 300:
        return None
    expired = b"expired" in response.content.lower()
    if status == 401:
        return "credential_expired" if expired else "credential_revoked"
    if status == 403:
        return "missing_permission"
    if status == 429 or status >= 500:
        return "provider_failure"
    return "provider_failure"


def _http_get(
    url: str, headers: dict[str, str], transport: httpx.BaseTransport | None
) -> httpx.Response:
    client = httpx.Client(transport=transport, timeout=10.0, follow_redirects=False)
    try:
        return client.get(url, headers=headers)
    finally:
        client.close()


def _call_urls(spec: ProbeSpec, material: dict) -> list[str] | str:
    """Return URLs, or an error code when a local field is missing."""
    account = material.get("external_account_id")
    base = _https_base(material.get("base_url")) if spec.needs_base else None
    if spec.needs_base and base is None:
        return "missing_credentials"
    if spec.needs_account:
        if spec.account_is_host:
            host = _account_host(account if isinstance(account, str) else None)
            if host is None:
                return "missing_credentials"
            account = host
        else:
            project = _project_id(account if isinstance(account, str) else None)
            if project is None:
                return "missing_credentials"
            account = project
    urls = []
    for call in spec.calls:
        url = call.split(" ", 1)[1]
        url = url.replace("{base}", base or "").replace("{account}", account or "")
        urls.append(url)
    return urls


def _probe_http(spec, material, transport) -> str | None:
    urls = _call_urls(spec, material)
    if isinstance(urls, str):
        return urls
    if transport is None and _testing():
        return "live_probe_disabled"
    headers = _headers(spec.header, material["secret"])
    for url in urls:
        if material["secret"] and material["secret"] in url:
            return "provider_failure"
        try:
            response = _http_get(url, headers, transport)
        except Exception:
            return "provider_failure"
        code = _classify_http(response)
        if code:
            return code
    return None


def _map_aws(exc) -> str:
    from botocore.exceptions import ClientError

    if not isinstance(exc, ClientError):
        return "provider_failure"
    error = exc.response.get("Error") or {}
    code = error.get("Code") or ""
    meta = exc.response.get("ResponseMetadata") or {}
    status = int(meta.get("HTTPStatusCode") or 0)
    if status >= 500:
        return "provider_failure"
    if code in _AWS_EXPIRED:
        return "credential_expired"
    if code in _AWS_REVOKED:
        return "credential_revoked"
    if code in _AWS_DENIED:
        return "missing_permission"
    return "provider_failure"


def _real_aws_factory(material: dict):
    import boto3

    os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
    region = material.get("region") or "us-east-1"

    def factory(service: str):
        return boto3.client(
            service,
            region_name=region,
            aws_access_key_id=material.get("access_key_id"),
            aws_secret_access_key=material["secret"],
        )

    return factory


def _probe_aws(material, factory) -> str | None:
    if not material.get("secret") or not material.get("access_key_id"):
        return "missing_credentials"
    resolved = factory or (None if _testing() else _real_aws_factory(material))
    if resolved is None:
        return "live_probe_disabled"
    try:
        resolved("sts").get_caller_identity()
        resolved("iam").get_account_summary()
    except Exception as exc:
        return _map_aws(exc)
    return None


def _map_message(result: dict) -> str:
    code = result.get("error_code")
    provider_error = str(result.get("provider_error") or "")
    if code == "missing_scope":
        return "missing_permission"
    if "expired" in provider_error.lower():
        return "credential_expired"
    if code == "denied":
        return "credential_revoked"
    return "provider_failure"


def _probe_slack(material, transport) -> str | None:
    if transport is None and _testing():
        return "live_probe_disabled"
    from app.services.slack_service import HttpSlackProvider

    provider = HttpSlackProvider(transport=transport, max_attempts=1)
    try:
        auth = provider.test_auth(material["secret"])
        if auth.get("ok") is not True:
            return _map_message(auth)
        channels = provider.list_channels(material["secret"])
    finally:
        provider.close()
    if isinstance(channels, dict) and channels.get("ok") is not True:
        return _map_message(channels)
    if not isinstance(channels, list):
        return "provider_failure"
    return None


def _probe_gmail(material, transport) -> str | None:
    if transport is None and _testing():
        return "live_probe_disabled"
    from app.services.gmail_service import HttpGmailProvider

    provider = HttpGmailProvider(transport=transport, max_attempts=1)
    try:
        profile = provider.get_profile(material["secret"])
        if profile.get("ok") is not True:
            return _map_message(profile)
        labels = provider.list_labels(material["secret"])
    finally:
        provider.close()
    if isinstance(labels, dict) and labels.get("ok") is not True:
        return _map_message(labels)
    if not isinstance(labels, list):
        return "provider_failure"
    return None


def probe_credential(
    source_type: str,
    material: dict,
    *,
    action: str,
    workspace_id: int,
    credential_type: str,
    transport: httpx.BaseTransport | None = None,
    aws_factory=None,
) -> ProbeOutcome:
    source = canonical_source(source_type)
    spec = probe_spec(source)
    scopes = spec.scopes if spec else ()
    if spec is None:
        return _unsupported(
            source, action, workspace_id, credential_type, "unsupported_connector", scopes
        )
    if spec.kind == "unsupported":
        return _unsupported(
            source, action, workspace_id, credential_type, "vendor_not_selected", scopes
        )
    secret = material.get("secret")
    if not isinstance(secret, str) or not secret:
        return _failure(
            source, action, workspace_id, credential_type, "missing_credentials", scopes
        )
    bound = dict(material)
    bound["secret"] = secret
    transport = _injected_transport(transport)
    aws_factory = _injected_aws(aws_factory)
    if spec.kind == "aws":
        code = _probe_aws(bound, aws_factory)
    elif spec.kind == "slack":
        code = _probe_slack(bound, transport)
    elif spec.kind == "gmail":
        code = _probe_gmail(bound, transport)
    else:
        code = _probe_http(spec, bound, transport)
    if code == "missing_permission":
        return _missing(source, action, workspace_id, credential_type, scopes)
    if code is None:
        return _finish(
            source,
            action,
            workspace_id,
            credential_type,
            state=ObservationState.SUCCESS,
            error_code=None,
            scopes=scopes,
        )
    state_code = code
    return _failure(source, action, workspace_id, credential_type, state_code, scopes)
