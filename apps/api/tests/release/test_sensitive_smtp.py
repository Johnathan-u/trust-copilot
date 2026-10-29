"""Synthetic transport failures must never disclose sensitive invitation/reply data."""

import re

import pytest

from app.services import email_service


@pytest.mark.parametrize("production", [False, True])
@pytest.mark.parametrize("port", [587, 465])
def test_sensitive_failure_logs_only_exception_class_and_random_id(
    monkeypatch, capsys, production, port
):
    secret = "synthetic-bearer-and-reply-content"
    provider = email_service.SmtpEmailProvider(
        "synthetic-host", port, None, None, "sender@example.com"
    )
    message = email_service.EmailMessage("recipient@example.com", "private-subject", secret)

    def fail(*args, **kwargs):
        raise OSError(secret)

    monkeypatch.setattr(email_service.smtplib, "SMTP_SSL" if port == 465 else "SMTP", fail)
    monkeypatch.setattr(email_service, "is_production_env", lambda: production)
    assert provider.send(message, sensitive=True) is False
    captured = capsys.readouterr()
    assert re.fullmatch(
        r"\[EMAIL\] SMTP send failed: OSError; message_id=[a-f0-9]{32}\n", captured.out
    )
    assert captured.err == ""
    for private in (secret, message.to, message.subject, provider.host, provider.from_addr):
        assert private not in captured.out


def test_non_sensitive_default_keeps_existing_dev_fallback(monkeypatch, capsys):
    provider = email_service.SmtpEmailProvider(
        "synthetic-host", 587, None, None, "sender@example.com"
    )
    message = email_service.EmailMessage(
        "recipient@example.com", "public-subject", "synthetic-public-body"
    )

    def fail(*args, **kwargs):
        raise OSError("synthetic-public-error")

    monkeypatch.setattr(email_service.smtplib, "SMTP", fail)
    monkeypatch.setattr(email_service, "is_production_env", lambda: False)
    assert provider.send(message) is False
    out = capsys.readouterr().out
    assert "synthetic-public-error" in out
    assert "synthetic-public-body" in out
