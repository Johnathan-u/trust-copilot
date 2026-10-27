"""Phase D: Slack notification delivery service. Provider interface, dev stub, HTTP client."""

import base64
import hashlib
import json
import logging
import time
from typing import Protocol

import httpx

from app.services.message_providers.errors import (
    DEV_STUB_LABEL,
    DEV_STUB_MODE,
    dev_stub_forbidden_result,
    failure_result,
    not_implemented_result,
)
from app.services.message_providers.http_client import MessageProviderHttp
from app.services.message_providers.retry_seam import call_result_to_dict
from app.services.message_providers.selection import (
    MessageProviderConfigurationError,
    resolve_message_provider_selection,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token encryption (reuse Fernet pattern from mfa.py)
# ---------------------------------------------------------------------------


def _fernet():
    from cryptography.fernet import Fernet
    from app.core.session import get_session_secret

    raw = hashlib.sha256(get_session_secret().encode()).digest()
    key = base64.urlsafe_b64encode(raw)
    return Fernet(key)


def encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    return _fernet().decrypt(encrypted.encode()).decode()


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------


class SlackProvider(Protocol):
    def send_message(self, bot_token: str, channel_id: str, text: str, on_attempt=None) -> dict:
        """Post a message. Return {"ok": True/False, "error": "...", "ts": "..."}."""
        ...

    def list_channels(self, bot_token: str) -> list[dict] | dict:
        """List channels the bot can see, or a failure dict. Never an empty list on error."""
        ...

    def test_auth(self, bot_token: str) -> dict:
        """Test the bot token. Return {"ok": True, "team": "...", "bot_id": "..."} or {"ok": False, "error": "..."}."""
        ...


def _stub_label(payload: dict) -> dict:
    body = dict(payload)
    body["provider_mode"] = DEV_STUB_MODE
    body["provider_label"] = DEV_STUB_LABEL
    body["delivered_to_provider"] = False
    return body


class ConsoleSlackProvider:
    """Labelled development stub. Logs instead of calling Slack.

    In a production runtime every method returns ``dev_stub_forbidden`` and
    does not report delivery. History, thread replies, and files are not this
    stub's success path: ``fetch_messages`` returns the existing dev fixture
    only outside production. Thread replies and files are not implemented.
    """

    def _refused(self) -> dict | None:
        selection = resolve_message_provider_selection()
        if selection.runtime_mode == "production" or not selection.ok:
            return dev_stub_forbidden_result("slack")
        return None

    def send_message(self, bot_token: str, channel_id: str, text: str, on_attempt=None) -> dict:
        del on_attempt  # the stub does not retry; the caller records the single outcome
        refused = self._refused()
        if refused:
            return refused
        logger.info("[SLACK DEV-STUB] channel=%s text=%s", channel_id, text[:100])
        return _stub_label({"ok": True, "ts": str(time.time()), "provider": "slack"})

    def list_channels(self, bot_token: str) -> list[dict] | dict:
        refused = self._refused()
        if refused:
            return refused
        return [
            {"id": "C_STUB_001", "name": "general"},
            {"id": "C_STUB_002", "name": "alerts"},
        ]

    def test_auth(self, bot_token: str) -> dict:
        refused = self._refused()
        if refused:
            return refused
        return _stub_label(
            {"ok": True, "team": "stub-team", "bot_id": "B_STUB", "provider": "slack"}
        )

    def fetch_messages(self, bot_token: str, channel_id: str, limit: int = 20) -> dict:
        """Development fixture for channel history. Not a Slack API call."""
        refused = self._refused()
        if refused:
            return refused
        return _stub_label(
            {
                "ok": True,
                "provider": "slack",
                "messages": [
                    {
                        "ts": f"stub.{time.time()}.{i}",
                        "text": f"Stub message {i} from #{channel_id}",
                        "user": "U_STUB",
                    }
                    for i in range(min(limit, 3))
                ],
            }
        )

    def fetch_thread_replies(self, bot_token: str, channel_id: str, thread_ts: str) -> dict:
        del bot_token, channel_id, thread_ts
        return not_implemented_result("slack", "conversations.replies", "TC-19-003")

    def fetch_file(self, bot_token: str, file_id: str) -> dict:
        del bot_token, file_id
        return not_implemented_result("slack", "files.info", "TC-19-003")


class HttpSlackProvider:
    """Slack Web API provider. Calls go through the outbound HTTP seam."""

    API_BASE = "https://slack.com/api"

    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
        max_attempts: int = 3,
        sleeper=None,
    ) -> None:
        self._http = MessageProviderHttp(
            transport=transport,
            timeout=timeout,
            max_attempts=max_attempts,
            sleeper=sleeper,
        )

    def close(self) -> None:
        self._http.close()

    def _headers(self, bot_token: str, *, json_body: bool = False) -> dict:
        headers = {"Authorization": f"Bearer {bot_token}"}
        if json_body:
            headers["Content-Type"] = "application/json; charset=utf-8"
        return headers

    def _post(
        self, bot_token: str, method: str, payload: dict | None = None, on_attempt=None
    ) -> dict:
        result = self._http.call(
            "POST",
            f"{self.API_BASE}/{method}",
            provider="slack",
            headers=self._headers(bot_token, json_body=True),
            content=json.dumps(payload or {}).encode(),
            on_attempt=on_attempt,
        )
        return call_result_to_dict(result, "slack")

    def _get(self, bot_token: str, method: str, params: dict | None = None) -> dict:
        result = self._http.call(
            "GET",
            f"{self.API_BASE}/{method}",
            provider="slack",
            headers=self._headers(bot_token),
            params=params,
        )
        return call_result_to_dict(result, "slack")

    def send_message(self, bot_token: str, channel_id: str, text: str, on_attempt=None) -> dict:
        return self._post(
            bot_token,
            "chat.postMessage",
            {"channel": channel_id, "text": text},
            on_attempt=on_attempt,
        )

    def list_channels(self, bot_token: str) -> list[dict] | dict:
        result = self._get(
            bot_token,
            "conversations.list",
            {"types": "public_channel,private_channel", "limit": "200"},
        )
        if result.get("ok") is not True:
            return result
        channels = result.get("channels") or []
        if not isinstance(channels, list):
            return failure_result(
                error_code="unknown",
                provider="slack",
                retryable=False,
                provider_error="invalid_channel_list",
            )
        return [
            {"id": c["id"], "name": c.get("name", "")}
            for c in channels
            if isinstance(c, dict) and c.get("id")
        ]

    def test_auth(self, bot_token: str) -> dict:
        return self._post(bot_token, "auth.test")

    def fetch_messages(self, bot_token: str, channel_id: str, limit: int = 20) -> dict:
        del bot_token, channel_id, limit
        return not_implemented_result("slack", "conversations.history", "TC-19-003")

    def fetch_thread_replies(self, bot_token: str, channel_id: str, thread_ts: str) -> dict:
        del bot_token, channel_id, thread_ts
        return not_implemented_result("slack", "conversations.replies", "TC-19-003")

    def fetch_file(self, bot_token: str, file_id: str) -> dict:
        del bot_token, file_id
        return not_implemented_result("slack", "files.info", "TC-19-003")


# ---------------------------------------------------------------------------
# Global provider instance
# ---------------------------------------------------------------------------

_provider: SlackProvider | None = None


def build_slack_provider() -> SlackProvider:
    """Return the configured provider. Raises when preflight refuses a stub."""
    selection = resolve_message_provider_selection()
    if not selection.ok:
        raise MessageProviderConfigurationError("; ".join(selection.failures))
    if selection.provider_mode == "http":
        logger.info("Slack provider: http (runtime_mode=%s)", selection.runtime_mode)
        return HttpSlackProvider()
    logger.info(
        "Slack provider: dev-stub (runtime_mode=%s, MESSAGE_PROVIDER_DEV_STUB=%s)",
        selection.runtime_mode,
        selection.dev_stub_source,
    )
    return ConsoleSlackProvider()


def get_slack_provider() -> SlackProvider:
    global _provider
    if _provider is None:
        _provider = build_slack_provider()
    return _provider


def set_slack_provider(provider: SlackProvider | None) -> None:
    global _provider
    _provider = provider


def reset_slack_provider() -> None:
    set_slack_provider(None)
