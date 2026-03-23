"""Regression tests for login + email sending issues after Docker/Caddy + invite-flow changes."""

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("TRUST_COPILOT_TESTING", "1")

from app.core.password import hash_password, verify_password
from app.services.email_service import (
    ConsoleEmailProvider,
    EmailMessage,
    SmtpEmailProvider,
    get_email_provider,
    send_invite_email,
    send_password_reset_email,
    set_email_provider,
)


class TestPasswordHashing:
    """Verify Argon2id hashing and verification work correctly."""

    def test_hash_and_verify(self):
        plain = "Admin123!"
        hashed = hash_password(plain)
        assert hashed.startswith("$argon2id$")
        assert verify_password(plain, hashed)

    def test_wrong_password_fails(self):
        hashed = hash_password("correct")
        assert not verify_password("wrong", hashed)

    def test_demo_password(self):
        hashed = hash_password("j")
        assert verify_password("j", hashed)
        assert not verify_password("k", hashed)

    def test_hash_differs_each_time(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2
        assert verify_password("same", h1)
        assert verify_password("same", h2)


class TestEmailProviderSelection:
    """Verify console vs SMTP provider selection based on SMTP_HOST."""

    def setup_method(self):
        set_email_provider(None)

    def teardown_method(self):
        set_email_provider(None)

    def test_console_provider_when_no_smtp_host(self):
        with patch.dict(os.environ, {"SMTP_HOST": ""}, clear=False):
            set_email_provider(None)
            provider = get_email_provider()
            assert isinstance(provider, ConsoleEmailProvider)

    def test_smtp_provider_when_smtp_host_set(self):
        env = {"SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587", "SMTP_FROM": "test@example.com"}
        with patch.dict(os.environ, env, clear=False):
            set_email_provider(None)
            provider = get_email_provider()
            assert isinstance(provider, SmtpEmailProvider)
            assert provider.host == "smtp.example.com"
            assert provider.port == 587

    def test_console_provider_send_returns_true(self):
        provider = ConsoleEmailProvider()
        msg = EmailMessage(to="a@b.com", subject="Test", body_text="body")
        assert provider.send(msg) is True


class TestSmtpFallbackLogging:
    """When SMTP fails, the message content should be logged to stdout."""

    def test_smtp_failure_logs_fallback(self, capsys):
        provider = SmtpEmailProvider(
            host="127.0.0.1",
            port=1,  # unlikely to be open
            user=None,
            password=None,
            from_addr="test@localhost",
            use_tls=False,
        )
        msg = EmailMessage(to="user@example.com", subject="Reset", body_text="Reset link: http://example.com/reset")
        result = provider.send(msg)
        assert result is False
        captured = capsys.readouterr()
        assert "[EMAIL] SMTP send failed" in captured.out
        assert "[EMAIL-FALLBACK]" in captured.out
        assert "user@example.com" in captured.out
        assert "Reset link:" in captured.out


class TestPasswordResetEmailPath:
    """Verify password reset email is constructed and sent correctly."""

    def test_send_password_reset_email(self):
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        set_email_provider(mock_provider)

        result = send_password_reset_email("user@example.com", "http://localhost:3000/reset-password?token=abc123")
        assert result is True
        mock_provider.send.assert_called_once()
        msg = mock_provider.send.call_args[0][0]
        assert msg.to == "user@example.com"
        assert "reset" in msg.subject.lower()
        assert "abc123" in msg.body_text

    def test_send_password_reset_email_failure(self):
        mock_provider = MagicMock()
        mock_provider.send.return_value = False
        set_email_provider(mock_provider)

        result = send_password_reset_email("user@example.com", "http://localhost:3000/reset-password?token=abc123")
        assert result is False


class TestInviteEmailPath:
    """Verify invite email is constructed and sent correctly."""

    def test_send_invite_email(self):
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        set_email_provider(mock_provider)

        result = send_invite_email(
            to="newuser@example.com",
            inviter_name="admin@trust.local",
            workspace_name="Default",
            verify_page_url="http://localhost:3000/accept-invite",
            verification_code="AB12-CD34-EF56",
        )
        assert result is True
        mock_provider.send.assert_called_once()
        msg = mock_provider.send.call_args[0][0]
        assert msg.to == "newuser@example.com"
        assert "Default" in msg.subject
        assert "AB12-CD34-EF56" in msg.body_text
        assert "accept-invite" in msg.body_text

    def test_invite_email_failure_returns_false(self):
        mock_provider = MagicMock()
        mock_provider.send.return_value = False
        set_email_provider(mock_provider)

        result = send_invite_email(
            to="newuser@example.com",
            inviter_name="admin@trust.local",
            workspace_name="Default",
            verify_page_url="http://localhost:3000/accept-invite",
            verification_code="AB12-CD34-EF56",
        )
        assert result is False


class TestInviteCodes:
    """Verify invite code generation and hashing."""

    def test_generate_and_hash(self):
        from app.core.invite_codes import generate_invite_code_pair, hash_invite_code

        formatted, normalized = generate_invite_code_pair()
        assert len(normalized) == 12
        assert "-" in formatted
        h1 = hash_invite_code(formatted)
        h2 = hash_invite_code(normalized)
        assert h1 == h2

    def test_hash_is_case_insensitive(self):
        from app.core.invite_codes import hash_invite_code

        assert hash_invite_code("ABCD1234EFGH") == hash_invite_code("abcd1234efgh")


class TestLoginEndpoint:
    """Integration tests for login endpoint (requires Postgres)."""

    def test_admin_login_success(self, client):
        resp = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["email"] == "admin@trust.local"
        assert "workspace_id" in data

    def test_demo_login_success(self, client):
        resp = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["email"] == "demo@trust.local"

    def test_wrong_password(self, client):
        resp = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "wrong"})
        assert resp.status_code == 401
        assert "Invalid credentials" in resp.json().get("detail", "")

    def test_nonexistent_user(self, client):
        resp = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "x"})
        assert resp.status_code == 401


class TestForgotPasswordEndpoint:
    """Integration tests for password reset flow (requires Postgres)."""

    def test_forgot_password_existing_user(self, client):
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        set_email_provider(mock_provider)
        try:
            resp = client.post("/api/auth/forgot-password", json={"email": "demo@trust.local"})
            assert resp.status_code == 200
            assert mock_provider.send.called
            msg = mock_provider.send.call_args[0][0]
            assert "reset" in msg.subject.lower()
            assert "demo@trust.local" == msg.to
        finally:
            set_email_provider(None)

    def test_forgot_password_nonexistent_no_email(self, client):
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        set_email_provider(mock_provider)
        try:
            resp = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
            assert resp.status_code == 200
            assert not mock_provider.send.called
        finally:
            set_email_provider(None)
