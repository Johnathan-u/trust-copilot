"""Phase F: Gmail service — provider interface, token encryption, console stub."""

import json
import logging
import time
from typing import Protocol

from app.services.slack_service import encrypt_token, decrypt_token  # reuse Fernet

logger = logging.getLogger(__name__)


class GmailProvider(Protocol):
    def list_labels(self, access_token: str) -> list[dict]:
        """Return [{"id": "Label_1", "name": "Compliance"}, ...]."""
        ...

    def list_messages(self, access_token: str, label_id: str, max_results: int = 20) -> list[dict]:
        """Return [{"id": "msg_id", "threadId": "thread_id"}, ...]."""
        ...

    def get_message(self, access_token: str, message_id: str) -> dict:
        """Return full message: subject, from, date, snippet, body, attachments."""
        ...

    def get_attachment(self, access_token: str, message_id: str, attachment_id: str) -> dict:
        """Return {"filename": "...", "data": b"...", "mime_type": "..."}."""
        ...

    def get_profile(self, access_token: str) -> dict:
        """Return {"email": "user@example.com"}."""
        ...


class ConsoleGmailProvider:
    """Dev/test stub that returns fake data."""

    def list_labels(self, access_token: str) -> list[dict]:
        return [
            {"id": "INBOX", "name": "Inbox"},
            {"id": "Label_Compliance", "name": "Compliance"},
            {"id": "Label_Security", "name": "Security Policies"},
        ]

    def list_messages(self, access_token: str, label_id: str, max_results: int = 20) -> list[dict]:
        return [
            {"id": f"msg_stub_{i}_{label_id}", "threadId": f"thread_stub_{i}"}
            for i in range(min(max_results, 3))
        ]

    def get_message(self, access_token: str, message_id: str) -> dict:
        return {
            "id": message_id,
            "threadId": f"thread_{message_id}",
            "subject": f"Security Policy Update — {message_id}",
            "from": "compliance@example.com",
            "date": "2026-03-15T10:00:00Z",
            "snippet": "Please review the updated access control policy attached to this email.",
            "body": "Please review the updated access control policy.",
            "attachments": [
                {"id": f"att_{message_id}_1", "filename": "access_control_policy_v3.pdf", "mime_type": "application/pdf", "size": 245000},
            ],
        }

    def get_attachment(self, access_token: str, message_id: str, attachment_id: str) -> dict:
        return {"filename": "stub_attachment.pdf", "data": b"stub-content", "mime_type": "application/pdf"}

    def get_profile(self, access_token: str) -> dict:
        return {"email": "stub@example.com"}


class HttpGmailProvider:
    """Real Gmail API provider using urllib."""

    API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

    def _get(self, access_token: str, path: str, params: dict | None = None) -> dict:
        import urllib.request, urllib.parse
        qs = urllib.parse.urlencode(params or {})
        url = f"{self.API_BASE}/{path}" + (f"?{qs}" if qs else "")
        headers = {"Authorization": f"Bearer {access_token}"}
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            return {"error": str(e)[:200]}

    def list_labels(self, access_token: str) -> list[dict]:
        result = self._get(access_token, "labels")
        return [{"id": l["id"], "name": l.get("name", "")} for l in result.get("labels", [])]

    def list_messages(self, access_token: str, label_id: str, max_results: int = 20) -> list[dict]:
        result = self._get(access_token, "messages", {"labelIds": label_id, "maxResults": str(max_results)})
        return result.get("messages", [])

    def get_message(self, access_token: str, message_id: str) -> dict:
        result = self._get(access_token, f"messages/{message_id}", {"format": "full"})
        if "error" in result:
            return result
        headers_list = result.get("payload", {}).get("headers", [])
        headers_map = {h["name"].lower(): h["value"] for h in headers_list}
        attachments = []
        for part in result.get("payload", {}).get("parts", []):
            if part.get("filename") and part.get("body", {}).get("attachmentId"):
                attachments.append({
                    "id": part["body"]["attachmentId"],
                    "filename": part["filename"],
                    "mime_type": part.get("mimeType", ""),
                    "size": part.get("body", {}).get("size", 0),
                })
        return {
            "id": result.get("id"),
            "threadId": result.get("threadId"),
            "subject": headers_map.get("subject", "(no subject)"),
            "from": headers_map.get("from", ""),
            "date": headers_map.get("date", ""),
            "snippet": result.get("snippet", ""),
            "body": result.get("snippet", ""),
            "attachments": attachments,
        }

    def get_attachment(self, access_token: str, message_id: str, attachment_id: str) -> dict:
        import base64
        result = self._get(access_token, f"messages/{message_id}/attachments/{attachment_id}")
        data = base64.urlsafe_b64decode(result.get("data", "")) if result.get("data") else b""
        return {"filename": "", "data": data, "mime_type": ""}

    def get_profile(self, access_token: str) -> dict:
        return self._get(access_token, "profile")


_provider: GmailProvider | None = None


def get_gmail_provider() -> GmailProvider:
    global _provider
    if _provider is None:
        _provider = ConsoleGmailProvider()
    return _provider


def set_gmail_provider(provider: GmailProvider) -> None:
    global _provider
    _provider = provider


# Dedup
_gmail_dedup: dict[str, float] = {}
GMAIL_DEDUP_WINDOW = 60


def is_gmail_duplicate(workspace_id: int, message_id: str) -> bool:
    key = f"gmail:{workspace_id}:{message_id}"
    now = time.monotonic()
    last = _gmail_dedup.get(key)
    if last and (now - last) < GMAIL_DEDUP_WINDOW:
        return True
    _gmail_dedup[key] = now
    stale = [k for k, v in _gmail_dedup.items() if now - v > GMAIL_DEDUP_WINDOW * 2]
    for k in stale:
        _gmail_dedup.pop(k, None)
    return False
