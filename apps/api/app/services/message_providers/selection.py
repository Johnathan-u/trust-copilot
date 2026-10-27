"""Runtime mode and dev-stub selection for Slack and Gmail.

Production never selects the console stub. An explicit dev-stub flag in
production fails preflight instead of reporting a delivery. Development uses
the labelled stub unless the flag is explicitly false, or the message-provider
runtime mode is production.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.services.message_providers.errors import DEV_STUB_LABEL, DEV_STUB_MODE, HTTP_MODE

_TRUE = frozenset({"1", "true", "yes"})
_FALSE = frozenset({"0", "false", "no"})
_STUB_VALUES = _TRUE | _FALSE


class MessageProviderConfigurationError(RuntimeError):
    """Selection failed preflight. No provider is returned and no delivery is claimed."""


@dataclass(frozen=True)
class MessageProviderSelection:
    ok: bool
    runtime_mode: str
    provider_mode: str
    dev_stub_requested: bool | None
    dev_stub_source: str
    failures: tuple[str, ...]

    def status_fields(self) -> dict:
        if not self.ok:
            label = "misconfigured"
            mode = "rejected"
        elif self.provider_mode == DEV_STUB_MODE:
            label = DEV_STUB_LABEL
            mode = DEV_STUB_MODE
        else:
            label = HTTP_MODE
            mode = HTTP_MODE
        return {
            "provider_mode": mode,
            "provider_label": label,
            "runtime_mode": self.runtime_mode
            if self.runtime_mode in ("production", "development")
            else "rejected",
            "dev_stub": bool(self.ok and self.provider_mode == DEV_STUB_MODE),
            "provider_preflight_ok": self.ok,
        }


def resolve_message_provider_selection(
    settings: Settings | None = None,
) -> MessageProviderSelection:
    settings = settings or get_settings()
    requested = (settings.message_provider_runtime_mode or "").strip().lower() or None
    raw_stub = (settings.message_provider_dev_stub_raw or "").strip().lower()
    failures: list[str] = []

    if requested not in (None, "production", "development"):
        failures.append("MESSAGE_PROVIDER_RUNTIME_MODE must be production or development")
    if raw_stub and raw_stub not in _STUB_VALUES:
        failures.append("MESSAGE_PROVIDER_DEV_STUB must be true or false")

    app_env = (getattr(settings, "app_env", None) or "development").strip().lower()
    if app_env == "production":
        runtime = "production"
        if requested == "development":
            failures.append(
                "APP_ENV=production cannot select the development message-provider runtime"
            )
    elif requested == "production":
        runtime = "production"
    elif requested in (None, "development"):
        runtime = "development"
    else:
        runtime = "rejected"

    if raw_stub in _TRUE:
        stub: bool | None = True
        stub_source = "true"
    elif raw_stub in _FALSE:
        stub = False
        stub_source = "false"
    else:
        stub = None
        stub_source = "unset"

    if failures:
        return MessageProviderSelection(
            ok=False,
            runtime_mode=runtime,
            provider_mode="rejected",
            dev_stub_requested=stub,
            dev_stub_source=stub_source,
            failures=tuple(failures),
        )

    if runtime == "production":
        if stub is True:
            return MessageProviderSelection(
                ok=False,
                runtime_mode="production",
                provider_mode="rejected",
                dev_stub_requested=True,
                dev_stub_source=stub_source,
                failures=(
                    "MESSAGE_PROVIDER_DEV_STUB is set, but production preflight refuses the development stub. "
                    "The HTTP providers are not replaced by a stub, and no delivery is reported.",
                ),
            )
        return MessageProviderSelection(
            ok=True,
            runtime_mode="production",
            provider_mode=HTTP_MODE,
            dev_stub_requested=stub,
            dev_stub_source=stub_source,
            failures=(),
        )

    if stub is False:
        return MessageProviderSelection(
            ok=True,
            runtime_mode="development",
            provider_mode=HTTP_MODE,
            dev_stub_requested=False,
            dev_stub_source=stub_source,
            failures=(),
        )
    return MessageProviderSelection(
        ok=True,
        runtime_mode="development",
        provider_mode=DEV_STUB_MODE,
        dev_stub_requested=stub,
        dev_stub_source=stub_source,
        failures=(),
    )


def message_provider_preflight(settings: Settings | None = None) -> MessageProviderSelection:
    return resolve_message_provider_selection(settings)


def assert_message_provider_preflight(settings: Settings | None = None) -> MessageProviderSelection:
    selection = message_provider_preflight(settings)
    if not selection.ok:
        raise MessageProviderConfigurationError("; ".join(selection.failures))
    return selection


def delivery_accepted(result: object) -> bool:
    """True only when a provider result may be logged as sent.

    A development stub may be accepted locally so existing dev flows keep
    their log row, but it is labelled and ``delivered_to_provider`` is false.
    A stub under a production runtime is never accepted. Failures are never
    accepted, including retry exhaustion.
    """
    if not isinstance(result, dict) or result.get("ok") is not True:
        return False
    if result.get("error_code"):
        return False
    if result.get("provider_mode") == DEV_STUB_MODE:
        selection = resolve_message_provider_selection()
        if not selection.ok or selection.runtime_mode == "production":
            return False
    return True
