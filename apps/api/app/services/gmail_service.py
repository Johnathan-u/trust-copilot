"""Phase F: Gmail service — provider interface, token encryption, dev stub, HTTP client."""

import base64
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
from app.services.slack_service import decrypt_token, encrypt_token  # reuse Fernet  # noqa: F401

logger = logging.getLogger(__name__)


class GmailProvider(Protocol):
    def list_labels(self, access_token: str) -> list[dict] | dict:
        """Return label dicts, or a failure dict. Never an empty list on error."""
        ...

    def list_messages(
        self, access_token: str, label_id: str, max_results: int = 20
    ) -> list[dict] | dict:
        """Return message refs, or a failure dict. Never an empty list on error."""
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


def _stub_label(payload: dict) -> dict:
    body = dict(payload)
    body["provider_mode"] = DEV_STUB_MODE
    body["provider_label"] = DEV_STUB_LABEL
    body["delivered_to_provider"] = False
    return body


class ConsoleGmailProvider:
    """Labelled development stub. Returns fixture mailbox data and does not call Gmail.

    Attachment bytes and a threaded send are not a real Gmail delivery. The
    attachment fixture stays for the existing dev ingest path. ``send_threaded_reply``
    is not implemented (TC-19-007). In production every method refuses.
    """

    def _refused(self) -> dict | None:
        selection = resolve_message_provider_selection()
        if selection.runtime_mode == "production" or not selection.ok:
            return dev_stub_forbidden_result("gmail")
        return None

    def list_labels(self, access_token: str) -> list[dict] | dict:
        refused = self._refused()
        if refused:
            return refused
        return [
            {"id": "INBOX", "name": "Inbox"},
            {"id": "Label_Compliance", "name": "Compliance"},
            {"id": "Label_Security", "name": "Security Policies"},
        ]

    def list_messages(
        self, access_token: str, label_id: str, max_results: int = 20
    ) -> list[dict] | dict:
        refused = self._refused()
        if refused:
            return refused
        return [
            {"id": f"msg_stub_{i}_{label_id}", "threadId": f"thread_stub_{i}"}
            for i in range(min(max_results, 3))
        ]

    def get_message(self, access_token: str, message_id: str) -> dict:
        refused = self._refused()
        if refused:
            return refused
        return _stub_label(
            {
                "id": message_id,
                "threadId": f"thread_{message_id}",
                "subject": f"Security Policy Update — {message_id}",
                "from": "compliance@example.com",
                "date": "2026-03-15T10:00:00Z",
                "snippet": "Please review the updated access control policy attached to this email.",
                "body": "Please review the updated access control policy.",
                "attachments": [
                    {
                        "id": f"att_{message_id}_1",
                        "filename": "access_control_policy_v3.pdf",
                        "mime_type": "application/pdf",
                        "size": 245000,
                    },
                ],
                "ok": True,
                "provider": "gmail",
            }
        )

    def get_attachment(self, access_token: str, message_id: str, attachment_id: str) -> dict:
        refused = self._refused()
        if refused:
            return refused
        return _stub_label(
            {
                "ok": True,
                "filename": "stub_attachment.pdf",
                "data": b"stub-content",
                "mime_type": "application/pdf",
                "provider": "gmail",
            }
        )

    def get_profile(self, access_token: str) -> dict:
        refused = self._refused()
        if refused:
            return refused
        return _stub_label({"ok": True, "email": "stub@example.com", "provider": "gmail"})

    def send_threaded_reply(self, access_token: str, thread_id: str, raw_message: str) -> dict:
        del access_token, thread_id, raw_message
        return not_implemented_result("gmail", "messages.send", "TC-19-007")


class HttpGmailProvider:
    """Gmail API provider. Calls go through the outbound HTTP seam.

    Attachment download keeps the existing thin GET (bytes only). Filename and
    ingest of those bytes are TC-19-006. Threaded send is TC-19-007 and returns
    not_implemented without a network call.
    """

    API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
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

    def _get(self, access_token: str, path: str, params: dict | None = None) -> dict:
        result = self._http.call(
            "GET",
            f"{self.API_BASE}/{path}",
            provider="gmail",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
        )
        return call_result_to_dict(result, "gmail")

    def list_labels(self, access_token: str) -> list[dict] | dict:
        result = self._get(access_token, "labels")
        if result.get("ok") is not True:
            return result
        labels = result.get("labels") or []
        if not isinstance(labels, list):
            return failure_result(
                error_code="unknown",
                provider="gmail",
                retryable=False,
                provider_error="invalid_label_list",
            )
        return [
            {"id": item["id"], "name": item.get("name", "")}
            for item in labels
            if isinstance(item, dict) and item.get("id")
        ]

    def list_messages(
        self, access_token: str, label_id: str, max_results: int = 20
    ) -> list[dict] | dict:
        result = self._get(
            access_token,
            "messages",
            {"labelIds": label_id, "maxResults": str(max_results)},
        )
        if result.get("ok") is not True:
            return result
        messages = result.get("messages") or []
        if not isinstance(messages, list):
            return failure_result(
                error_code="unknown",
                provider="gmail",
                retryable=False,
                provider_error="invalid_message_list",
            )
        return messages

    def get_message(self, access_token: str, message_id: str) -> dict:
        result = self._get(access_token, f"messages/{message_id}", {"format": "full"})
        if result.get("ok") is not True:
            return result
        headers_list = (
            result.get("payload", {}).get("headers", [])
            if isinstance(result.get("payload"), dict)
            else []
        )
        headers_map = {
            h["name"].lower(): h["value"]
            for h in headers_list
            if isinstance(h, dict) and h.get("name")
        }
        attachments = []
        parts = (
            result.get("payload", {}).get("parts", [])
            if isinstance(result.get("payload"), dict)
            else []
        )
        for part in parts or []:
            if not isinstance(part, dict):
                continue
            if part.get("filename") and part.get("body", {}).get("attachmentId"):
                attachments.append(
                    {
                        "id": part["body"]["attachmentId"],
                        "filename": part["filename"],
                        "mime_type": part.get("mimeType", ""),
                        "size": part.get("body", {}).get("size", 0),
                    }
                )
        return {
            "ok": True,
            "provider": "gmail",
            "provider_mode": "http",
            "delivered_to_provider": True,
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
        result = self._get(access_token, f"messages/{message_id}/attachments/{attachment_id}")
        if result.get("ok") is not True:
            return result
        raw = result.get("data") or ""
        if not isinstance(raw, str) or not raw:
            return failure_result(
                error_code="unknown",
                provider="gmail",
                retryable=False,
                provider_error="missing_attachment_data",
            )
        padded = raw + "=" * (-len(raw) % 4)
        try:
            data = base64.urlsafe_b64decode(padded.encode())
        except Exception:
            return failure_result(
                error_code="unknown",
                provider="gmail",
                retryable=False,
                provider_error="invalid_attachment_data",
            )
        return {
            "ok": True,
            "provider": "gmail",
            "provider_mode": "http",
            "filename": "",
            "data": data,
            "mime_type": "",
        }

    def get_profile(self, access_token: str) -> dict:
        result = self._get(access_token, "profile")
        if result.get("ok") is not True:
            return result
        email = result.get("emailAddress") or result.get("email")
        if not email:
            return failure_result(
                error_code="unknown",
                provider="gmail",
                retryable=False,
                provider_error="missing_email",
            )
        profile = dict(result)
        profile["email"] = email
        profile["emailAddress"] = email
        return profile

    def send_threaded_reply(self, access_token: str, thread_id: str, raw_message: str) -> dict:
        del access_token, thread_id, raw_message
        return not_implemented_result("gmail", "messages.send", "TC-19-007")


_provider: GmailProvider | None = None


def build_gmail_provider() -> GmailProvider:
    """Return the configured provider. Raises when preflight refuses a stub."""
    selection = resolve_message_provider_selection()
    if not selection.ok:
        raise MessageProviderConfigurationError("; ".join(selection.failures))
    if selection.provider_mode == "http":
        logger.info("Gmail provider: http (runtime_mode=%s)", selection.runtime_mode)
        return HttpGmailProvider()
    logger.info(
        "Gmail provider: dev-stub (runtime_mode=%s, MESSAGE_PROVIDER_DEV_STUB=%s)",
        selection.runtime_mode,
        selection.dev_stub_source,
    )
    return ConsoleGmailProvider()


def get_gmail_provider() -> GmailProvider:
    global _provider
    if _provider is None:
        _provider = build_gmail_provider()
    return _provider


def set_gmail_provider(provider: GmailProvider | None) -> None:
    global _provider
    _provider = provider


def reset_gmail_provider() -> None:
    set_gmail_provider(None)


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
