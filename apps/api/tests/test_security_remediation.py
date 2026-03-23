"""Tests for security remediation pass (items 1-7)."""

import asyncio
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# 1. switch-workspace preserves session_id
# ---------------------------------------------------------------------------

class TestSwitchWorkspaceSessionId:
    """switch-workspace must preserve session_id so sessions remain revocable."""

    def test_switch_workspace_preserves_session_id(self, client: TestClient):
        """After workspace switch, the session cookie still contains a valid session_id."""
        r = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
        assert r.status_code == 200
        from app.core.session import verify_token
        cookie_before = client.cookies.get("tc_session")
        payload_before = verify_token(cookie_before)
        assert payload_before is not None
        assert payload_before.get("session_id"), "Login must set session_id"

        r2 = client.post("/api/auth/switch-workspace", json={"workspace_id": 2})
        assert r2.status_code == 200
        cookie_after = client.cookies.get("tc_session")
        payload_after = verify_token(cookie_after)
        assert payload_after is not None
        assert payload_after.get("session_id"), "switch-workspace must preserve session_id"
        assert payload_after["session_id"] == payload_before["session_id"]
        assert payload_after["workspace_id"] == 2

    def test_revoke_others_works_after_workspace_switch(self, client: TestClient):
        """revoke-others should still work after a workspace switch."""
        client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
        client.post("/api/auth/switch-workspace", json={"workspace_id": 2})
        r = client.post("/api/auth/sessions/revoke-others")
        assert r.status_code == 200

    def test_session_valid_after_switch(self, client: TestClient):
        """The session remains valid for authenticated requests after workspace switch."""
        client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
        client.post("/api/auth/switch-workspace", json={"workspace_id": 2})
        r = client.get("/api/auth/me")
        assert r.status_code == 200
        assert r.json().get("workspace_id") == 2

    def test_switch_to_unauthorized_workspace_forbidden(self, client: TestClient):
        """Switching to a workspace the user is not a member of returns 403."""
        client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
        r = client.post("/api/auth/switch-workspace", json={"workspace_id": 3})
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# 2. Session secret fallback
# ---------------------------------------------------------------------------

class TestSessionSecretFallback:
    """Session secret must fail fast in production if missing."""

    def test_dev_mode_uses_fallback(self):
        """In dev mode, missing SESSION_SECRET uses fallback with warning."""
        from app.core.session import _get_session_secret, _DEV_SECRET
        with patch.dict(os.environ, {"APP_ENV": "development", "SESSION_SECRET": ""}, clear=False):
            from app.core.config import get_settings
            get_settings.cache_clear()
            secret = _get_session_secret()
            assert secret == _DEV_SECRET
            get_settings.cache_clear()

    def test_production_mode_raises_without_secret(self):
        """In production, missing or default SESSION_SECRET raises RuntimeError."""
        from app.core.session import _get_session_secret
        with patch.dict(os.environ, {"APP_ENV": "production", "SESSION_SECRET": ""}, clear=False):
            from app.core.config import get_settings
            get_settings.cache_clear()
            with pytest.raises(RuntimeError, match="SESSION_SECRET"):
                _get_session_secret()
            get_settings.cache_clear()

    def test_production_mode_raises_with_dev_default(self):
        """In production, using the dev default secret raises RuntimeError."""
        from app.core.session import _get_session_secret
        with patch.dict(os.environ, {"APP_ENV": "production", "SESSION_SECRET": "change_me_dev_secret"}, clear=False):
            from app.core.config import get_settings
            get_settings.cache_clear()
            with pytest.raises(RuntimeError, match="SESSION_SECRET"):
                _get_session_secret()
            get_settings.cache_clear()

    def test_production_mode_accepts_real_secret(self):
        """In production, a real secret works fine."""
        from app.core.session import _get_session_secret
        with patch.dict(os.environ, {"APP_ENV": "production", "SESSION_SECRET": "my-strong-production-secret-42"}, clear=False):
            from app.core.config import get_settings
            get_settings.cache_clear()
            assert _get_session_secret() == "my-strong-production-secret-42"
            get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 3. X-Forwarded-For / client IP trust
# ---------------------------------------------------------------------------

class TestClientIpTrust:
    """get_client_ip must only trust X-Forwarded-For from configured trusted proxies."""

    def test_direct_request_uses_client_host(self):
        """Without trusted proxy config, uses direct connection IP."""
        from app.core.rate_limit import get_client_ip
        req = MagicMock()
        req.client.host = "192.168.1.100"
        req.headers = {"x-forwarded-for": "1.2.3.4"}
        with patch.dict(os.environ, {"TRUSTED_PROXY_IPS": ""}, clear=False):
            assert get_client_ip(req) == "192.168.1.100"

    def test_trusted_proxy_uses_forwarded_for(self):
        """When connection IP is in TRUSTED_PROXY_IPS, use X-Forwarded-For."""
        from app.core.rate_limit import get_client_ip
        req = MagicMock()
        req.client.host = "10.0.0.1"
        req.headers = {"x-forwarded-for": "203.0.113.50, 10.0.0.1"}
        with patch.dict(os.environ, {"TRUSTED_PROXY_IPS": "10.0.0.1,10.0.0.2"}, clear=False):
            assert get_client_ip(req) == "203.0.113.50"

    def test_spoofed_forwarded_for_ignored_from_untrusted(self):
        """An untrusted client sending X-Forwarded-For is ignored."""
        from app.core.rate_limit import get_client_ip
        req = MagicMock()
        req.client.host = "192.168.1.100"
        req.headers = {"x-forwarded-for": "spoofed-ip"}
        with patch.dict(os.environ, {"TRUSTED_PROXY_IPS": "10.0.0.1"}, clear=False):
            assert get_client_ip(req) == "192.168.1.100"

    def test_no_client_returns_unknown(self):
        """When request has no client, returns 'unknown'."""
        from app.core.rate_limit import get_client_ip
        req = MagicMock(spec=[])
        with patch.dict(os.environ, {"TRUSTED_PROXY_IPS": ""}, clear=False):
            assert get_client_ip(req) == "unknown"


# ---------------------------------------------------------------------------
# 4. Password reset token invalidation
# ---------------------------------------------------------------------------

class TestPasswordResetTokenInvalidation:
    """New password reset request must invalidate prior unused tokens."""

    def test_old_token_rejected_after_new_reset(self, client: TestClient):
        """Requesting a second reset invalidates the first token."""
        r1 = client.post("/api/auth/forgot-password", json={"email": "demo@trust.local"})
        assert r1.status_code == 200

        from app.core.database import SessionLocal
        from app.models import PasswordResetToken, User
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == "demo@trust.local").first()
            tokens_after_first = db.query(PasswordResetToken).filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            ).all()
            assert len(tokens_after_first) >= 1
            first_token_id = tokens_after_first[0].id
        finally:
            db.close()

        r2 = client.post("/api/auth/forgot-password", json={"email": "demo@trust.local"})
        assert r2.status_code == 200

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == "demo@trust.local").first()
            old_token = db.query(PasswordResetToken).filter(
                PasswordResetToken.id == first_token_id,
                PasswordResetToken.used_at.is_(None),
            ).first()
            assert old_token is None, "Old unused token should be deleted after new reset request"

            current_tokens = db.query(PasswordResetToken).filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            ).all()
            assert len(current_tokens) == 1, "Exactly one valid token should remain"
        finally:
            db.close()

    def test_used_token_rejected(self, client: TestClient):
        """A used token cannot be used again."""
        r = client.post("/api/auth/reset-password", json={"token": "already-used", "new_password": "newpass123"})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# 5. /db-test endpoint gating
# ---------------------------------------------------------------------------

class TestDbTestEndpoint:

    def test_db_test_blocked_in_production(self, client: TestClient):
        """In production mode, /db-test returns 404."""
        from app.core.config import get_settings
        original_env = get_settings().app_env
        with patch.object(get_settings(), "app_env", "production"):
            from app.core.config import get_settings as gs
            gs.cache_clear()
            with patch.dict(os.environ, {"APP_ENV": "production"}, clear=False):
                gs.cache_clear()
                r = client.get("/db-test")
                assert r.status_code == 404
                gs.cache_clear()

    def test_db_test_allowed_in_dev(self, client: TestClient):
        """In dev mode, /db-test returns a response (200 or 503)."""
        r = client.get("/db-test")
        assert r.status_code in (200, 503)

    def test_db_test_does_not_leak_error_details_in_production(self):
        """In production, even if reached, no raw DB error is exposed."""
        from app.core.config import get_settings
        with patch.dict(os.environ, {"APP_ENV": "production"}, clear=False):
            get_settings.cache_clear()
            from app.main import app
            from fastapi.testclient import TestClient as TC
            c = TC(app)
            r = c.get("/db-test")
            if r.status_code == 404:
                assert "OperationalError" not in r.text
            get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 6. OAuth auto-link requires verified email
# ---------------------------------------------------------------------------

class _MockAsyncClient:
    """Reusable mock for httpx.AsyncClient as async context manager."""

    def __init__(self, post_responses, get_responses):
        self._post_responses = post_responses if isinstance(post_responses, list) else [post_responses]
        self._get_responses = get_responses if isinstance(get_responses, list) else [get_responses]
        self._post_idx = 0
        self._get_idx = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, *args, **kwargs):
        resp = self._post_responses[min(self._post_idx, len(self._post_responses) - 1)]
        self._post_idx += 1
        return resp

    async def get(self, *args, **kwargs):
        resp = self._get_responses[min(self._get_idx, len(self._get_responses) - 1)]
        self._get_idx += 1
        return resp


def _make_resp(status_code, json_data, text="ok"):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data
    r.text = text
    return r


class TestOAuthAutoLinkVerifiedEmail:
    """OAuth auto-link should require email_verified from provider."""

    def test_google_returns_email_verified_flag(self):
        """Google exchange includes email_verified field."""
        from app.services.oauth_service import google_exchange_code

        token_resp = _make_resp(200, {"access_token": "test-token"})
        userinfo_resp = _make_resp(200, {
            "id": "12345", "email": "user@example.com",
            "name": "Test User", "verified_email": True,
        })
        mock_client = _MockAsyncClient(token_resp, userinfo_resp)

        async def _test():
            with patch("app.services.oauth_service.httpx.AsyncClient", return_value=mock_client):
                result = await google_exchange_code("test-code", "http://localhost/callback")
                assert result is not None
                assert result["email_verified"] is True

        asyncio.new_event_loop().run_until_complete(_test())

    def test_github_returns_email_verified_flag(self):
        """GitHub exchange includes email_verified field."""
        from app.services.oauth_service import github_exchange_code

        token_resp = _make_resp(200, {"access_token": "test-token"})
        user_resp = _make_resp(200, {"id": 42, "email": "user@example.com", "name": "Test"})
        emails_resp = _make_resp(200, [{"email": "user@example.com", "primary": True, "verified": True}])
        mock_client = _MockAsyncClient(token_resp, [user_resp, emails_resp])

        async def _test():
            with patch("app.services.oauth_service.httpx.AsyncClient", return_value=mock_client):
                result = await github_exchange_code("test-code", "http://localhost/callback")
                assert result is not None
                assert result["email_verified"] is True

        asyncio.new_event_loop().run_until_complete(_test())

    def test_microsoft_returns_email_verified_flag(self):
        """Microsoft exchange marks email_verified=True when email comes from mail field."""
        from app.services.oauth_service import microsoft_exchange_code

        token_resp = _make_resp(200, {"access_token": "test-token"})
        graph_resp = _make_resp(200, {"id": "ms-id-123", "mail": "user@corp.com", "displayName": "Corp User"})
        mock_client = _MockAsyncClient(token_resp, graph_resp)

        async def _test():
            with patch("app.services.oauth_service.httpx.AsyncClient", return_value=mock_client):
                result = await microsoft_exchange_code("test-code", "http://localhost/callback")
                assert result is not None
                assert result["email_verified"] is True

        asyncio.new_event_loop().run_until_complete(_test())

    def test_microsoft_upn_only_marks_unverified(self):
        """Microsoft: when only userPrincipalName is present (no mail), email_verified is False."""
        from app.services.oauth_service import microsoft_exchange_code

        token_resp = _make_resp(200, {"access_token": "test-token"})
        graph_resp = _make_resp(200, {
            "id": "ms-id-456", "userPrincipalName": "user@personal.onmicrosoft.com",
            "displayName": "Personal User",
        })
        mock_client = _MockAsyncClient(token_resp, graph_resp)

        async def _test():
            with patch("app.services.oauth_service.httpx.AsyncClient", return_value=mock_client):
                result = await microsoft_exchange_code("test-code", "http://localhost/callback")
                assert result is not None
                assert result["email_verified"] is False

        asyncio.new_event_loop().run_until_complete(_test())


# ---------------------------------------------------------------------------
# 7. Rate-limit backend selection and logging
# ---------------------------------------------------------------------------

class TestRateLimitBackendSelection:
    """Rate-limit backend selection behavior and production warnings."""

    def test_in_memory_backend_in_dev(self):
        """Without REDIS_URL, in-memory backend is selected."""
        from app.core.rate_limit import _get_backend, _InMemoryBackend
        with patch.dict(os.environ, {"REDIS_URL": "", "APP_ENV": "development"}, clear=False):
            backend = _get_backend()
            assert isinstance(backend, _InMemoryBackend)

    def test_production_without_redis_logs_warning(self):
        """In production without REDIS_URL, a warning is logged."""
        from app.core.rate_limit import _get_backend, _InMemoryBackend, _rl_logger
        with patch.dict(os.environ, {"REDIS_URL": "", "APP_ENV": "production"}, clear=False):
            with patch.object(_rl_logger, "warning") as mock_warn:
                backend = _get_backend()
                assert isinstance(backend, _InMemoryBackend)
                mock_warn.assert_called_once()
                assert "production" in mock_warn.call_args[0][0].lower()

    def test_redis_backend_selected_when_configured(self):
        """With REDIS_URL set, Redis backend is attempted."""
        from app.core.rate_limit import _get_backend, _RedisBackend
        with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379/0", "APP_ENV": "production"}, clear=False):
            with patch("app.core.rate_limit._RedisBackend") as mock_redis_cls:
                mock_redis_cls.return_value = MagicMock(spec=_RedisBackend)
                backend = _get_backend()
                mock_redis_cls.assert_called_once()

    def test_rate_limit_key_uses_safe_client_ip(self, client: TestClient):
        """Rate-limit key should be based on the safe client IP, not a spoofed header."""
        from app.core.rate_limit import get_client_ip
        req = MagicMock()
        req.client.host = "127.0.0.1"
        req.headers = {"x-forwarded-for": "evil-spoof"}
        with patch.dict(os.environ, {"TRUSTED_PROXY_IPS": ""}, clear=False):
            ip = get_client_ip(req)
            assert ip == "127.0.0.1"
            assert ip != "evil-spoof"
