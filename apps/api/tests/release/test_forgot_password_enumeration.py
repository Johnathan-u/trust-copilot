"""TC-04-007a: forgot-password must throttle a known address and an unknown one alike.

The IP window is cleared between the two sequences. They share the test client
address, so each sequence has to start from zero. A missing user row must not
skip the counter.
"""

from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.password import hash_password
from app.core.rate_limit import DEFAULT_MAX_ATTEMPTS, _store
from app.models import AuditEvent, PasswordResetToken, User
from app.services.email_service import set_email_provider

_GENERIC = {"message": "If that email is registered, you will receive a reset link."}
_LIMITED = {"detail": "Too many requests. Try again later."}


class _Outbox:
    def send(self, message) -> bool:
        return True


def _address(label: str) -> str:
    return f"forgot-enum-{label}-{secrets.token_hex(4)}@example.test"


def _purge(email: str) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one_or_none()
        db.query(AuditEvent).filter(AuditEvent.email == email).delete(synchronize_session=False)
        if user is not None:
            db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).delete(
                synchronize_session=False
            )
            db.query(AuditEvent).filter(AuditEvent.user_id == user.id).delete(
                synchronize_session=False
            )
            db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _create_user(email: str) -> None:
    db = SessionLocal()
    try:
        db.add(
            User(
                email=email,
                password_hash=hash_password(secrets.token_urlsafe(18)),
                display_name="Synthetic",
                email_verified=True,
            )
        )
        db.commit()
    finally:
        db.close()


def _sequence(client: TestClient, email: str) -> list[tuple[int, dict]]:
    _store.clear()
    found: list[tuple[int, dict]] = []
    for _ in range(DEFAULT_MAX_ATTEMPTS + 1):
        response = client.post("/api/auth/forgot-password", json={"email": email})
        found.append((response.status_code, response.json()))
    return found


def test_forgot_password_rate_limit_matches_for_known_and_unknown(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N+1 requests for a known address and an unknown address share one status sequence."""
    monkeypatch.delenv("TRUST_COPILOT_DEV_RETURN_RESET_URL", raising=False)
    known_email = _address("known")
    unknown_email = _address("unknown")
    _purge(known_email)
    _purge(unknown_email)
    set_email_provider(_Outbox())
    try:
        _create_user(known_email)
        known = _sequence(client, known_email)
        unknown = _sequence(client, unknown_email)
    finally:
        set_email_provider(None)
        _purge(known_email)
        _purge(unknown_email)

    expected = [(200, _GENERIC)] * DEFAULT_MAX_ATTEMPTS + [(429, _LIMITED)]
    assert known == unknown == expected
