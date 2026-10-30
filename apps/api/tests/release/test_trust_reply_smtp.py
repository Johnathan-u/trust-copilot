"""Reviewed replies use the sensitive SMTP path without changing delivery outcomes."""

import hashlib
from datetime import datetime, timezone
from email import message_from_string
from unittest.mock import Mock

import pytest

from app.models import TrustRequest, TrustRequestNote
from app.services import email_service, trust_request_service


@pytest.mark.parametrize("production", [False, True])
@pytest.mark.parametrize("port", [587, 465])
@pytest.mark.parametrize("accepted", [False, True])
def test_reviewed_reply_smtp_outcome_never_logs_private_content(
    monkeypatch, capsys, production, port, accepted
):
    request = TrustRequest(
        id=42,
        workspace_id=1,
        requester_email="private-recipient@example.com",
        subject="Private reply subject",
    )
    note = TrustRequestNote(
        id=43,
        trust_request_id=42,
        body="Private reviewed reply body",
        body_revision=1,
        approved_revision=1,
        approved_by=7,
        approved_at=datetime.now(timezone.utc),
        approved_body_hash=hashlib.sha256(b"Private reviewed reply body").hexdigest(),
        delivery_status="approved",
    )
    provider = email_service.SmtpEmailProvider(
        "synthetic-host", port, None, None, "sender@example.com"
    )
    attempts = []

    class SmtpConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def ehlo(self):
            pass

        def starttls(self, **kwargs):
            pass

        def sendmail(self, sender, recipients, message):
            assert recipients == [request.requester_email]
            parsed = message_from_string(message)
            assert parsed["Subject"] == request.subject
            assert parsed.get_payload(0).get_payload(decode=True).decode() == note.body
            attempts.append(message)
            if not accepted:
                raise OSError("Private SMTP exception text")

    monkeypatch.setattr(
        email_service.smtplib,
        "SMTP_SSL" if port == 465 else "SMTP",
        lambda *args, **kwargs: SmtpConnection(),
    )
    monkeypatch.setattr(email_service, "is_production_env", lambda: production)
    monkeypatch.setattr(trust_request_service, "get_email_provider", lambda: provider)
    # Exercise the real send state machine and SMTP transport; row lookup is the
    # only external persistence boundary replaced in this no-database regression.
    monkeypatch.setattr(
        trust_request_service, "reply_for_update", lambda *args, **kwargs: (request, note)
    )
    db = Mock()
    actor = {"user_id": 7, "workspace_id": 1}
    result = trust_request_service.send_reply(db, 1, 42, 43, 1, actor)
    assert result.delivery_status == ("accepted" if accepted else "uncertain")
    assert (result.delivery_accepted_at is not None) is accepted
    assert result.delivery_error == (None if accepted else "delivery_outcome_unknown")
    assert result.delivery_attempts == 1
    # Retrying either accepted or uncertain delivery must not resend mail.
    trust_request_service.send_reply(db, 1, 42, 43, 1, actor)
    assert len(attempts) == 1
    captured = capsys.readouterr()
    for private in (
        request.requester_email,
        request.subject,
        note.body,
        "Private SMTP exception text",
    ):
        assert private not in captured.out + captured.err
