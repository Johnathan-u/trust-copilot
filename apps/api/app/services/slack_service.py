"""Phase D: Slack notification delivery service. Provider interface + console stub for dev."""

import base64
import hashlib
import json
import logging
import time
from typing import Protocol

from app.core.config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token encryption (reuse Fernet pattern from mfa.py)
# ---------------------------------------------------------------------------

def _fernet():
    from cryptography.fernet import Fernet
    raw = hashlib.sha256(get_settings().session_secret.encode()).digest()
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
    def send_message(self, bot_token: str, channel_id: str, text: str) -> dict:
        """Post a message. Return {"ok": True/False, "error": "...", "ts": "..."}."""
        ...

    def list_channels(self, bot_token: str) -> list[dict]:
        """List channels the bot can see. Return [{"id": "C...", "name": "general"}, ...]."""
        ...

    def test_auth(self, bot_token: str) -> dict:
        """Test the bot token. Return {"ok": True, "team": "...", "bot_id": "..."} or {"ok": False, "error": "..."}."""
        ...


class ConsoleSlackProvider:
    """Stub for dev/tests: logs to stdout instead of hitting Slack API."""

    def send_message(self, bot_token: str, channel_id: str, text: str) -> dict:
        logger.info("[SLACK STUB] channel=%s text=%s", channel_id, text[:100])
        return {"ok": True, "ts": str(time.time())}

    def list_channels(self, bot_token: str) -> list[dict]:
        return [
            {"id": "C_STUB_001", "name": "general"},
            {"id": "C_STUB_002", "name": "alerts"},
        ]

    def test_auth(self, bot_token: str) -> dict:
        return {"ok": True, "team": "stub-team", "bot_id": "B_STUB"}


class HttpSlackProvider:
    """Real Slack Web API provider using urllib (no extra deps)."""

    API_BASE = "https://slack.com/api"

    def _post(self, bot_token: str, method: str, payload: dict | None = None) -> dict:
        import urllib.request
        url = f"{self.API_BASE}/{method}"
        headers = {"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json; charset=utf-8"}
        data = json.dumps(payload or {}).encode()
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def _get(self, bot_token: str, method: str, params: dict | None = None) -> dict:
        import urllib.request, urllib.parse
        qs = urllib.parse.urlencode(params or {})
        url = f"{self.API_BASE}/{method}" + (f"?{qs}" if qs else "")
        headers = {"Authorization": f"Bearer {bot_token}"}
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def send_message(self, bot_token: str, channel_id: str, text: str) -> dict:
        return self._post(bot_token, "chat.postMessage", {"channel": channel_id, "text": text})

    def list_channels(self, bot_token: str) -> list[dict]:
        result = self._get(bot_token, "conversations.list", {"types": "public_channel,private_channel", "limit": "200"})
        if not result.get("ok"):
            return []
        return [{"id": c["id"], "name": c.get("name", "")} for c in result.get("channels", [])]

    def test_auth(self, bot_token: str) -> dict:
        return self._post(bot_token, "auth.test")


# ---------------------------------------------------------------------------
# Global provider instance
# ---------------------------------------------------------------------------

_provider: SlackProvider | None = None


def get_slack_provider() -> SlackProvider:
    global _provider
    if _provider is None:
        _provider = ConsoleSlackProvider()
    return _provider


def set_slack_provider(provider: SlackProvider) -> None:
    global _provider
    _provider = provider


# ---------------------------------------------------------------------------
# Dedup for Slack messages
# ---------------------------------------------------------------------------

_slack_dedup: dict[str, float] = {}
SLACK_DEDUP_WINDOW = 60


def _slack_dedup_key(workspace_id: int, event_type: str) -> str:
    return f"slack:{workspace_id}:{event_type}"


def is_slack_duplicate(workspace_id: int, event_type: str) -> bool:
    key = _slack_dedup_key(workspace_id, event_type)
    now = time.monotonic()
    last = _slack_dedup.get(key)
    if last and (now - last) < SLACK_DEDUP_WINDOW:
        return True
    _slack_dedup[key] = now
    stale = [k for k, v in _slack_dedup.items() if now - v > SLACK_DEDUP_WINDOW * 2]
    for k in stale:
        _slack_dedup.pop(k, None)
    return False
