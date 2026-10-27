"""TC-19-001: Slack and Gmail providers are selected by configuration.

Fixtures are hand-built Slack Web API and Gmail API responses. No network, token,
or sandbox account is used. Recorded shapes follow the documented error bodies
(invalid_auth, missing_scope, ratelimited, and Gmail 401/403/429).
"""

from __future__ import annotations

import base64
import json
import logging

import httpx
import pytest

from app.core.config import get_settings
from app.services.gmail_service import (
    ConsoleGmailProvider,
    HttpGmailProvider,
    get_gmail_provider,
    reset_gmail_provider,
)
from app.services.message_providers.errors import is_provider_failure
from app.services.message_providers.oauth_seam import OAuthStatePkceSeam
from app.services.message_providers.outbound_http import (
    ALLOWED_HOSTS,
    MAX_RESPONSE_BYTES,
    OutboundHttpDenied,
    OutboundHttpSeam,
)
from app.services.message_providers.selection import (
    MessageProviderConfigurationError,
    assert_message_provider_preflight,
    delivery_accepted,
    message_provider_preflight,
)
from app.services.slack_service import (
    ConsoleSlackProvider,
    HttpSlackProvider,
    get_slack_provider,
    reset_slack_provider,
)

TOKEN = "xoxb-test-token-not-a-real-secret"
GMAIL_TOKEN = "ya29.test-access-token-not-real"

SLACK_AUTH_OK = {
    "ok": True,
    "url": "https://acme.slack.com/",
    "team": "Acme",
    "user": "trustbot",
    "team_id": "T123",
    "user_id": "U123",
    "bot_id": "B123",
}
SLACK_CHANNELS_OK = {
    "ok": True,
    "channels": [
        {"id": "C012AB3CD", "name": "general", "is_channel": True, "is_member": True},
        {"id": "C999", "name": "alerts", "is_channel": True, "is_member": True},
    ],
    "response_metadata": {"next_cursor": ""},
}
SLACK_POST_OK = {
    "ok": True,
    "channel": "C012AB3CD",
    "ts": "1503435956.000247",
    "message": {"text": "hello", "type": "message", "ts": "1503435956.000247"},
}
SLACK_INVALID_AUTH = {"ok": False, "error": "invalid_auth"}
SLACK_MISSING_SCOPE = {
    "ok": False,
    "error": "missing_scope",
    "needed": "chat:write",
    "provided": "identify,channels:read",
}
SLACK_RATELIMITED = {"ok": False, "error": "ratelimited"}
SLACK_UNKNOWN = {"ok": False, "error": "channel_not_found"}

GMAIL_PROFILE_OK = {
    "emailAddress": "owner@example.com",
    "messagesTotal": 12,
    "threadsTotal": 8,
    "historyId": "12345",
}
GMAIL_LABELS_OK = {
    "labels": [
        {
            "id": "INBOX",
            "name": "INBOX",
            "messageListVisibility": "show",
            "labelListVisibility": "labelShow",
            "type": "system",
        },
        {"id": "Label_1", "name": "Compliance", "type": "user"},
    ],
}
GMAIL_MESSAGES_OK = {
    "messages": [{"id": "18c1", "threadId": "18c1"}],
    "resultSizeEstimate": 1,
}
GMAIL_MESSAGE_OK = {
    "id": "18c1",
    "threadId": "18c1",
    "snippet": "Please review",
    "payload": {
        "mimeType": "text/plain",
        "headers": [
            {"name": "Subject", "value": "Policy"},
            {"name": "From", "value": "a@example.com"},
            {"name": "Date", "value": "Tue, 15 Mar 2026 10:00:00 +0000"},
        ],
    },
}
GMAIL_401 = {
    "error": {
        "code": 401,
        "message": "Request had invalid authentication credentials. Expected OAuth 2 access token, login cookie or other valid authentication credential.",
        "status": "UNAUTHENTICATED",
        "errors": [{"message": "Invalid Credentials", "domain": "global", "reason": "authError"}],
    }
}
GMAIL_403_SCOPE = {
    "error": {
        "code": 403,
        "message": "Request had insufficient authentication scopes.",
        "status": "PERMISSION_DENIED",
        "errors": [
            {
                "message": "Insufficient Permission",
                "domain": "global",
                "reason": "insufficientPermissions",
            }
        ],
        "details": [
            {
                "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                "reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
                "domain": "googleapis.com",
            }
        ],
    }
}
GMAIL_403_DENIED = {
    "error": {
        "code": 403,
        "message": "The domain administrators have disabled Gmail apps.",
        "status": "PERMISSION_DENIED",
        "errors": [{"message": "Domain policy", "domain": "global", "reason": "domainPolicy"}],
    }
}
GMAIL_429 = {
    "error": {
        "code": 429,
        "message": "Resource has been exhausted (e.g. check quota).",
        "status": "RESOURCE_EXHAUSTED",
        "errors": [
            {"message": "Rate Limit Exceeded", "domain": "global", "reason": "rateLimitExceeded"}
        ],
    }
}


def _use_env(monkeypatch: pytest.MonkeyPatch, **env: str | None) -> None:
    for key in ("APP_ENV", "MESSAGE_PROVIDER_RUNTIME_MODE", "MESSAGE_PROVIDER_DEV_STUB"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    reset_slack_provider()
    reset_gmail_provider()


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _assert_no_secret(payload: object) -> None:
    encoded = json.dumps(payload, default=str)
    assert TOKEN not in encoded
    assert GMAIL_TOKEN not in encoded
    assert "Authorization" not in encoded


class TestProviderSelection:
    def test_production_selects_http_providers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_env(monkeypatch, APP_ENV="production")
        selection = message_provider_preflight()
        assert selection.ok is True
        assert selection.runtime_mode == "production"
        assert selection.provider_mode == "http"
        assert isinstance(get_slack_provider(), HttpSlackProvider)
        assert isinstance(get_gmail_provider(), HttpGmailProvider)
        assert_message_provider_preflight().provider_mode == "http"

    def test_production_with_stub_flag_explicitly_false_is_http(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_env(monkeypatch, APP_ENV="production", MESSAGE_PROVIDER_DEV_STUB="0")
        assert isinstance(get_slack_provider(), HttpSlackProvider)
        assert isinstance(get_gmail_provider(), HttpGmailProvider)

    def test_development_explicit_http_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_env(monkeypatch, APP_ENV="development", MESSAGE_PROVIDER_DEV_STUB="false")
        assert message_provider_preflight().provider_mode == "http"
        assert isinstance(get_slack_provider(), HttpSlackProvider)
        assert isinstance(get_gmail_provider(), HttpGmailProvider)

    def test_development_runtime_mode_can_force_http_without_app_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_env(monkeypatch, MESSAGE_PROVIDER_RUNTIME_MODE="production")
        assert get_settings().app_env != "production"
        assert isinstance(get_slack_provider(), HttpSlackProvider)
        assert isinstance(get_gmail_provider(), HttpGmailProvider)

    def test_development_default_is_labelled_stub(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_env(monkeypatch, APP_ENV="development")
        selection = message_provider_preflight()
        assert selection.ok is True
        assert selection.provider_mode == "dev-stub"
        assert selection.dev_stub_source == "unset"
        fields = selection.status_fields()
        assert fields["provider_label"] == "development-stub"
        assert fields["dev_stub"] is True
        slack = get_slack_provider()
        gmail = get_gmail_provider()
        assert isinstance(slack, ConsoleSlackProvider)
        assert isinstance(gmail, ConsoleGmailProvider)
        sent = slack.send_message(TOKEN, "C1", "hello")
        assert sent["ok"] is True
        assert sent["provider_mode"] == "dev-stub"
        assert sent["provider_label"] == "development-stub"
        assert sent["delivered_to_provider"] is False
        assert delivery_accepted(sent) is True
        profile = gmail.get_profile(GMAIL_TOKEN)
        assert profile["email"] == "stub@example.com"
        assert profile["provider_mode"] == "dev-stub"
        assert profile["provider_label"] == "development-stub"

    def test_explicit_dev_stub_flag_labels_the_stub(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_env(monkeypatch, APP_ENV="development", MESSAGE_PROVIDER_DEV_STUB="yes")
        selection = message_provider_preflight()
        assert selection.provider_mode == "dev-stub"
        assert selection.dev_stub_source == "true"
        auth = get_slack_provider().test_auth(TOKEN)
        assert auth["team"] == "stub-team"
        assert auth["provider_label"] == "development-stub"

    def test_production_stub_flag_fails_preflight_and_does_not_claim_delivery(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_env(monkeypatch, APP_ENV="production", MESSAGE_PROVIDER_DEV_STUB="1")
        selection = message_provider_preflight()
        assert selection.ok is False
        assert selection.provider_mode == "rejected"
        assert selection.failures
        with pytest.raises(MessageProviderConfigurationError):
            assert_message_provider_preflight()
        with pytest.raises(MessageProviderConfigurationError):
            get_slack_provider()
        with pytest.raises(MessageProviderConfigurationError):
            get_gmail_provider()
        refused = ConsoleSlackProvider().send_message(TOKEN, "C1", "should not send")
        assert refused["ok"] is False
        assert refused["error_code"] == "dev_stub_forbidden"
        assert refused["delivered_to_provider"] is False
        assert delivery_accepted(refused) is False
        _assert_no_secret(refused)
        gmail_refused = ConsoleGmailProvider().get_profile(GMAIL_TOKEN)
        assert gmail_refused["ok"] is False
        assert "email" not in gmail_refused
        assert delivery_accepted(gmail_refused) is False

    def test_production_cannot_downgrade_to_the_development_runtime(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_env(monkeypatch, APP_ENV="production", MESSAGE_PROVIDER_RUNTIME_MODE="development")
        selection = message_provider_preflight()
        assert selection.ok is False
        assert selection.provider_mode == "rejected"
        with pytest.raises(MessageProviderConfigurationError):
            get_slack_provider()

    def test_invalid_mode_and_stub_flag_do_not_select_a_stub(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_env(monkeypatch, APP_ENV="development", MESSAGE_PROVIDER_RUNTIME_MODE="staging")
        assert message_provider_preflight().ok is False
        with pytest.raises(MessageProviderConfigurationError):
            get_gmail_provider()
        _use_env(monkeypatch, APP_ENV="development", MESSAGE_PROVIDER_DEV_STUB="maybe")
        assert message_provider_preflight().provider_mode == "rejected"
        with pytest.raises(MessageProviderConfigurationError):
            get_slack_provider()


class TestSlackHttpFixtures:
    def test_success_shapes(self) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            assert request.url.host == "slack.com"
            assert request.headers["Authorization"] == f"Bearer {TOKEN}"
            if request.url.path == "/api/auth.test":
                return httpx.Response(200, json=SLACK_AUTH_OK)
            if request.url.path == "/api/conversations.list":
                return httpx.Response(200, json=SLACK_CHANNELS_OK)
            if request.url.path == "/api/chat.postMessage":
                body = json.loads(request.content.decode())
                assert body["channel"] == "C012AB3CD"
                assert body["text"] == "hello"
                return httpx.Response(200, json=SLACK_POST_OK)
            raise AssertionError(request.url.path)

        provider = HttpSlackProvider(transport=_transport(handler), sleeper=lambda *_: None)
        try:
            auth = provider.test_auth(TOKEN)
            assert auth["ok"] is True
            assert auth["team"] == "Acme"
            assert auth["team_id"] == "T123"
            assert auth["bot_id"] == "B123"
            assert auth["provider_mode"] == "http"
            assert delivery_accepted(auth) is True
            channels = provider.list_channels(TOKEN)
            assert isinstance(channels, list)
            assert channels[0] == {"id": "C012AB3CD", "name": "general"}
            posted = provider.send_message(TOKEN, "C012AB3CD", "hello")
            assert posted["ok"] is True
            assert posted["ts"] == "1503435956.000247"
            assert posted["delivered_to_provider"] is True
        finally:
            provider.close()
        assert len(calls) == 3

    @pytest.mark.parametrize(
        ("body", "error_code", "provider_error"),
        [
            (SLACK_INVALID_AUTH, "denied", "invalid_auth"),
            (SLACK_MISSING_SCOPE, "missing_scope", "missing_scope"),
            (SLACK_UNKNOWN, "unknown", "channel_not_found"),
        ],
    )
    def test_error_bodies_are_typed_and_not_ok(self, body, error_code, provider_error) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json=body)

        provider = HttpSlackProvider(transport=_transport(handler), sleeper=lambda *_: None)
        try:
            result = provider.send_message(TOKEN, "C1", "hello")
            listed = provider.list_channels(TOKEN)
        finally:
            provider.close()
        assert result["ok"] is False
        assert result["error_code"] == error_code
        assert result["provider_error"] == provider_error
        assert result["retryable"] is False
        assert result["attempts"] == 1
        assert delivery_accepted(result) is False
        assert is_provider_failure(listed)
        assert listed["error_code"] == error_code
        assert listed != []
        assert "needed" not in result
        assert "provided" not in result
        _assert_no_secret(result)
        assert calls["n"] == 2

    def test_rate_limit_retries_then_succeeds(self) -> None:
        calls = {"n": 0}
        sleeps: list[tuple[int, float | None]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] < 3:
                return httpx.Response(429, json=SLACK_RATELIMITED, headers={"Retry-After": "30"})
            return httpx.Response(200, json=SLACK_POST_OK)

        def sleeper(attempt: int, retry_after: float | None) -> None:
            sleeps.append((attempt, retry_after))

        provider = HttpSlackProvider(transport=_transport(handler), sleeper=sleeper)
        try:
            result = provider.send_message(TOKEN, "C1", "hello")
        finally:
            provider.close()
        assert result["ok"] is True
        assert result["ts"] == "1503435956.000247"
        assert calls["n"] == 3
        assert sleeps == [(1, 30.0), (2, 30.0)]

    def test_rate_limit_exhaustion_is_not_success(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=SLACK_RATELIMITED)

        provider = HttpSlackProvider(
            transport=_transport(handler), max_attempts=3, sleeper=lambda *_: None
        )
        try:
            result = provider.test_auth(TOKEN)
        finally:
            provider.close()
        assert result["ok"] is False
        assert result["error_code"] == "rate_limited"
        assert result["retryable"] is True
        assert result["exhausted"] is True
        assert result["attempts"] == 3
        assert delivery_accepted(result) is False

    def test_server_error_retries_then_unknown_when_exhausted(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"ok": False, "error": "internal_error"})

        provider = HttpSlackProvider(transport=_transport(handler), sleeper=lambda *_: None)
        try:
            result = provider.send_message(TOKEN, "C1", "hello")
        finally:
            provider.close()
        assert result["ok"] is False
        assert result["error_code"] == "unknown"
        assert result["retryable"] is True
        assert result["exhausted"] is True
        assert result["attempts"] == 3

    def test_denied_is_not_retried(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json=SLACK_INVALID_AUTH)

        provider = HttpSlackProvider(transport=_transport(handler), sleeper=lambda *_: None)
        try:
            result = provider.test_auth(TOKEN)
        finally:
            provider.close()
        assert calls["n"] == 1
        assert result["error_code"] == "denied"
        assert result["retryable"] is False
        assert result.get("exhausted") is not True

    def test_history_threads_and_files_are_not_implemented(self, caplog) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            raise AssertionError("absent methods must not call Slack")

        provider = HttpSlackProvider(transport=_transport(handler))
        try:
            with caplog.at_level(logging.INFO, logger="app.services.message_providers.errors"):
                history = provider.fetch_messages(TOKEN, "C1", limit=5)
                replies = provider.fetch_thread_replies(TOKEN, "C1", "1503435956.000247")
                file_info = provider.fetch_file(TOKEN, "F123")
        finally:
            provider.close()
        assert "TC-19-003" in caplog.text
        assert "conversations.history" in caplog.text
        assert calls["n"] == 0
        for result, method in (
            (history, "conversations.history"),
            (replies, "conversations.replies"),
            (file_info, "files.info"),
        ):
            assert result["ok"] is False
            assert result["error_code"] == "not_implemented"
            assert "TC-19-003" not in result["error"]
            assert "TC-19-003" in result["provider_error"]
            assert method in result["provider_error"]
            assert method not in result["error"]
            if method == "conversations.history":
                assert result["error"] == "Slack message import is not available yet."
            else:
                assert result["error"] == "This provider method is not implemented."
            assert delivery_accepted(result) is False

    def test_redirect_is_not_followed(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            assert request.url.host == "slack.com"
            return httpx.Response(
                302, headers={"Location": "http://169.254.169.254/latest/meta-data/"}
            )

        provider = HttpSlackProvider(transport=_transport(handler), sleeper=lambda *_: None)
        try:
            result = provider.test_auth(TOKEN)
        finally:
            provider.close()
        assert calls["n"] == 1
        assert result["ok"] is False
        assert result["provider_error"] == "redirect_blocked"
        assert "169.254.169.254" not in json.dumps(result)
        assert delivery_accepted(result) is False


class TestGmailHttpFixtures:
    def test_success_shapes(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.host == "gmail.googleapis.com"
            assert request.headers["Authorization"] == f"Bearer {GMAIL_TOKEN}"
            path = request.url.path
            if path.endswith("/profile"):
                return httpx.Response(200, json=GMAIL_PROFILE_OK)
            if path.endswith("/labels"):
                return httpx.Response(200, json=GMAIL_LABELS_OK)
            if path.endswith("/messages") and "labelIds" in str(request.url):
                return httpx.Response(200, json=GMAIL_MESSAGES_OK)
            if path.endswith("/messages/18c1"):
                return httpx.Response(200, json=GMAIL_MESSAGE_OK)
            raw = base64.urlsafe_b64encode(b"hello-bytes").decode().rstrip("=")
            if "/attachments/" in path:
                return httpx.Response(200, json={"size": 11, "data": raw})
            raise AssertionError(path)

        provider = HttpGmailProvider(transport=_transport(handler), sleeper=lambda *_: None)
        try:
            profile = provider.get_profile(GMAIL_TOKEN)
            assert profile["ok"] is True
            assert profile["email"] == "owner@example.com"
            assert profile["emailAddress"] == "owner@example.com"
            labels = provider.list_labels(GMAIL_TOKEN)
            assert labels == [
                {"id": "INBOX", "name": "INBOX"},
                {"id": "Label_1", "name": "Compliance"},
            ]
            messages = provider.list_messages(GMAIL_TOKEN, "Label_1", max_results=5)
            assert messages == [{"id": "18c1", "threadId": "18c1"}]
            message = provider.get_message(GMAIL_TOKEN, "18c1")
            assert message["ok"] is True
            assert message["subject"] == "Policy"
            assert message["from"] == "a@example.com"
            assert message["body"] == "Please review"
            attachment = provider.get_attachment(GMAIL_TOKEN, "18c1", "att-1")
            assert attachment["ok"] is True
            assert attachment["data"] == b"hello-bytes"
        finally:
            provider.close()

    @pytest.mark.parametrize(
        ("status", "body", "error_code"),
        [
            (401, GMAIL_401, "denied"),
            (403, GMAIL_403_SCOPE, "missing_scope"),
            (403, GMAIL_403_DENIED, "denied"),
        ],
    )
    def test_denied_and_missing_scope_stop_without_empty_success(
        self, status, body, error_code
    ) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(status, json=body)

        provider = HttpGmailProvider(transport=_transport(handler), sleeper=lambda *_: None)
        try:
            profile = provider.get_profile(GMAIL_TOKEN)
            labels = provider.list_labels(GMAIL_TOKEN)
            messages = provider.list_messages(GMAIL_TOKEN, "INBOX")
            attachment = provider.get_attachment(GMAIL_TOKEN, "18c1", "att")
        finally:
            provider.close()
        assert profile["ok"] is False
        assert profile["error_code"] == error_code
        assert profile["retryable"] is False
        assert "email" not in profile
        assert is_provider_failure(labels)
        assert labels != []
        assert isinstance(messages, dict)
        assert messages["error_code"] == error_code
        assert attachment["ok"] is False
        assert attachment.get("data", b"") in (b"", None) or "data" not in attachment
        assert calls["n"] == 4
        _assert_no_secret(profile)
        encoded = json.dumps(profile)
        assert "Expected OAuth 2 access token" not in encoded

    def test_rate_limit_retries_and_exhaustion_is_not_ok(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, json=GMAIL_429, headers={"Retry-After": "1"})
            return httpx.Response(200, json=GMAIL_PROFILE_OK)

        provider = HttpGmailProvider(transport=_transport(handler), sleeper=lambda *_: None)
        try:
            profile = provider.get_profile(GMAIL_TOKEN)
        finally:
            provider.close()
        assert calls["n"] == 2
        assert profile["email"] == "owner@example.com"

        def always_limited(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json=GMAIL_429)

        limited = HttpGmailProvider(transport=_transport(always_limited), sleeper=lambda *_: None)
        try:
            failed = limited.list_labels(GMAIL_TOKEN)
        finally:
            limited.close()
        assert failed["ok"] is False
        assert failed["error_code"] == "rate_limited"
        assert failed["provider_error"] == "RESOURCE_EXHAUSTED"
        assert failed["retryable"] is True
        assert failed["exhausted"] is True
        assert failed["attempts"] == 3
        assert failed != []

    def test_empty_mailbox_is_not_an_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"resultSizeEstimate": 0})

        provider = HttpGmailProvider(transport=_transport(handler), sleeper=lambda *_: None)
        try:
            messages = provider.list_messages(GMAIL_TOKEN, "Label_1")
        finally:
            provider.close()
        assert messages == []

    def test_threaded_send_is_not_implemented(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            raise AssertionError("threaded send must not call Gmail")

        provider = HttpGmailProvider(transport=_transport(handler))
        try:
            result = provider.send_threaded_reply(GMAIL_TOKEN, "18c1", "raw")
        finally:
            provider.close()
        assert calls["n"] == 0
        assert result["ok"] is False
        assert result["error_code"] == "not_implemented"
        assert result["error"] == "This provider method is not implemented."
        assert "TC-19-007" not in result["error"]
        assert "TC-19-007" in result["provider_error"]
        stub = ConsoleGmailProvider().send_threaded_reply(GMAIL_TOKEN, "18c1", "raw")
        assert stub["error_code"] == "not_implemented"
        assert stub["ok"] is False

    def test_attachment_error_is_not_empty_bytes(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json=GMAIL_401)

        provider = HttpGmailProvider(transport=_transport(handler), sleeper=lambda *_: None)
        try:
            result = provider.get_attachment(GMAIL_TOKEN, "18c1", "att")
        finally:
            provider.close()
        assert result["ok"] is False
        assert result["error_code"] == "denied"
        assert "data" not in result


class TestOutboundAndOAuthSeams:
    @pytest.mark.parametrize(
        "url",
        [
            "http://slack.com/api/auth.test",
            "https://evil.example/api/auth.test",
            "https://169.254.169.254/latest/meta-data/",
            "https://slack.com.evil.example/api/auth.test",
            "https://user:pass@slack.com/api/auth.test",
            "https://slack.com:8443/api/auth.test",
            "https://api.slack.com/api/auth.test",
            "https://gmail.googleapis.com.evil.example/gmail/v1/users/me/profile",
        ],
    )
    def test_allowlist_blocks_before_transport(self, url: str) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError(f"transport was called for {request.url}")

        seam = OutboundHttpSeam(transport=_transport(handler))
        try:
            with pytest.raises(OutboundHttpDenied):
                seam.request("GET", url, headers={"Authorization": f"Bearer {TOKEN}"})
        finally:
            seam.close()

    def test_allowlist_contains_slack_and_google_api_hosts(self) -> None:
        assert "slack.com" in ALLOWED_HOSTS
        assert "gmail.googleapis.com" in ALLOWED_HOSTS
        assert "www.googleapis.com" in ALLOWED_HOSTS
        assert "oauth2.googleapis.com" in ALLOWED_HOSTS

    def test_allowlist_denial_is_not_a_silent_ok(self) -> None:
        from app.services.message_providers.http_client import MessageProviderHttp
        from app.services.message_providers.retry_seam import call_result_to_dict

        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError(f"transport was called for {request.url}")

        client = MessageProviderHttp(transport=_transport(handler), sleeper=lambda *_: None)
        try:
            result = call_result_to_dict(
                client.call(
                    "POST",
                    "https://evil.example/nope",
                    provider="slack",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                ),
                "slack",
            )
        finally:
            client.close()
        assert result["ok"] is False
        assert result["error_code"] == "denied"
        assert result["provider_error"] == "outbound_not_allowlisted"
        assert result["retryable"] is False
        assert result["attempts"] == 1
        assert "evil.example" not in json.dumps(result)

    def test_response_over_the_size_limit_is_not_ok(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))

        provider = HttpSlackProvider(transport=_transport(handler), sleeper=lambda *_: None)
        try:
            result = provider.test_auth(TOKEN)
        finally:
            provider.close()
        assert result["ok"] is False
        assert result["error_code"] == "unknown"
        assert result["provider_error"] == "response_too_large"
        assert result["retryable"] is False

    def test_timeout_retries_then_fails(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            raise httpx.TimeoutException("timed out")

        provider = HttpGmailProvider(
            transport=_transport(handler), max_attempts=3, sleeper=lambda *_: None
        )
        try:
            result = provider.get_profile(GMAIL_TOKEN)
        finally:
            provider.close()
        assert calls["n"] == 3
        assert result["ok"] is False
        assert result["error_code"] == "unknown"
        assert result["provider_error"] == "timeout"
        assert result["retryable"] is True
        assert result["exhausted"] is True

    def test_oauth_seam_does_not_exchange_or_succeed(self) -> None:
        seam = OAuthStatePkceSeam()
        exchanged = seam.exchange_code(
            "gmail", code="auth-code", verifier="verifier", state="state"
        )
        started = seam.begin_authorization("slack")
        assert exchanged["ok"] is False
        assert exchanged["error_code"] == "not_implemented"
        assert "TC-05-004" not in exchanged["error"]
        assert "TC-19-005" not in exchanged["error"]
        assert "TC-05-004" in exchanged["provider_error"]
        assert "TC-19-005" in exchanged["provider_error"]
        assert started["error_code"] == "not_implemented"
        assert "TC-19-002" not in started["error"]
        assert "TC-19-002" in started["provider_error"]
        assert delivery_accepted(exchanged) is False
        assert "auth-code" not in json.dumps(exchanged)


class TestDevStubDoesNotInventProviderDelivery:
    def test_slack_history_stub_is_labelled_and_http_is_not_the_stub(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_env(monkeypatch, APP_ENV="development", MESSAGE_PROVIDER_DEV_STUB="1")
        stub = get_slack_provider().fetch_messages(TOKEN, "C_RUN", limit=3)
        assert stub["ok"] is True
        assert stub["provider_mode"] == "dev-stub"
        assert stub["delivered_to_provider"] is False
        assert len(stub["messages"]) == 3
        assert stub["messages"][0]["user"] == "U_STUB"
        _use_env(monkeypatch, APP_ENV="production")
        http_provider = get_slack_provider()
        assert isinstance(http_provider, HttpSlackProvider)
        missing = http_provider.fetch_messages(TOKEN, "C_RUN", limit=3)
        assert missing["ok"] is False
        assert missing["error_code"] == "not_implemented"
        assert "messages" not in missing
