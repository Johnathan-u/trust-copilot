"""TC-04-003: a successful reset retires every unused reset link, and a password
change drops the other sessions even when the client asks to keep them.

``forgot_password`` still replaces unused links when it issues a new one. The
extra rows below are outstanding links that can exist beside that newest row
(a concurrent request that committed after the replace). Using any one of them
must reject the rest. Email-verification rows and MFA recovery codes are not
password-reset credentials and stay. ``invalidate_other_sessions`` is still
accepted; it does not choose which sessions survive.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.api.routes.auth import _token_hash
from app.core.database import SessionLocal
from app.models import (
    AuditEvent,
    EmailVerificationToken,
    MfaRecoveryCode,
    PasswordResetToken,
    User,
    UserSession,
)
from app.services.email_service import set_email_provider
from tests.conftest import TEST_HEADERS, TEST_ORIGIN

_GENERIC = "If that email is not yet registered, you will receive a verification code."
_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_LINK_RE = re.compile(r"[?&]token=([^&\s]+)&user=(\d+)")


class _Mailbox:
    def __init__(self) -> None:
        self.messages: list = []

    def send(self, message) -> bool:
        self.messages.append(message)
        return True


def _password() -> str:
    return secrets.token_urlsafe(18)


def _address(label: str) -> str:
    return f"reset-{label}-{secrets.token_hex(4)}@example.test"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _mailed(box: _Mailbox) -> tuple[str, str, str]:
    assert box.messages, "verification message was not sent"
    body = box.messages[-1].body_text
    code = _CODE_RE.search(body)
    link = _LINK_RE.search(body)
    assert code is not None and link is not None
    return code.group(1), link.group(1), link.group(2)


def _register(client: TestClient, box: _Mailbox, email: str, password: str) -> int:
    before = len(box.messages)
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "display_name": "Synthetic"},
    )
    assert response.status_code == 200, response.status_code
    assert response.json()["message"] == _GENERIC
    assert len(box.messages) == before + 1
    code, _link, user_id = _mailed(box)
    verified = client.post("/api/auth/verify-code", json={"email": email, "code": code})
    assert verified.status_code == 200, verified.status_code
    return int(user_id)


def _purge(email: str) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one_or_none()
        db.query(AuditEvent).filter(AuditEvent.email == email).delete(synchronize_session=False)
        if user is not None:
            uid = user.id
            db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == uid).delete(
                synchronize_session=False
            )
            db.query(PasswordResetToken).filter(PasswordResetToken.user_id == uid).delete(
                synchronize_session=False
            )
            db.query(UserSession).filter(UserSession.user_id == uid).delete(
                synchronize_session=False
            )
            db.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == uid).delete(
                synchronize_session=False
            )
            db.query(AuditEvent).filter(AuditEvent.user_id == uid).delete(synchronize_session=False)
            db.query(User).filter(User.id == uid).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _plant_reset_token(user_id: int) -> str:
    raw = secrets.token_urlsafe(32)
    db = SessionLocal()
    try:
        db.add(
            PasswordResetToken(
                user_id=user_id,
                token_hash=_token_hash(raw),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        db.commit()
    finally:
        db.close()
    return raw


def _unused_reset_count(user_id: int) -> int:
    db = SessionLocal()
    try:
        return (
            db.query(PasswordResetToken)
            .filter(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used_at.is_(None),
            )
            .count()
        )
    finally:
        db.close()


def _browser() -> TestClient:
    from app.main import app

    return TestClient(app, base_url=TEST_ORIGIN, headers=TEST_HEADERS)


def _login(client: TestClient, email: str, password: str) -> str:
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.status_code
    cookie = client.cookies.get("tc_session")
    assert cookie
    return cookie


def _replay(client: TestClient, cookie: str) -> TestClient:
    client.cookies.clear()
    client.cookies.set("tc_session", cookie)
    return client


@pytest.fixture(autouse=True)
def mailbox():
    box = _Mailbox()
    set_email_provider(box)
    yield box
    set_email_provider(None)


@pytest.fixture(autouse=True)
def _clear_limits():
    from app.core.rate_limit import _store

    _store.clear()
    yield
    _store.clear()


@pytest.fixture
def isolate():
    emails: list[str] = []

    def track(email: str) -> str:
        emails.append(email)
        _purge(email)
        return email

    yield track
    for email in emails:
        _purge(email)


def _request_reset_token(client: TestClient, email: str, monkeypatch) -> str:
    monkeypatch.setenv("TRUST_COPILOT_DEV_RETURN_RESET_URL", "true")
    response = client.post("/api/auth/forgot-password", json={"email": email})
    assert response.status_code == 200, response.status_code
    reset_url = response.json().get("reset_url")
    assert isinstance(reset_url, str) and reset_url
    token = parse_qs(urlsplit(reset_url).query).get("token", [None])[0]
    assert isinstance(token, str) and token
    return token


def test_successful_reset_rejects_every_other_unused_token(
    client: TestClient, mailbox: _Mailbox, isolate, monkeypatch
) -> None:
    """Three outstanding reset links: the one that succeeds retires the other two."""
    email = isolate(_address("owner"))
    old_password = _password()
    user_id = _register(client, mailbox, email, old_password)
    held = _login(client, email, old_password)

    bystander_email = isolate(_address("other"))
    bystander_password = _password()
    bystander_id = _register(client, mailbox, bystander_email, bystander_password)
    bystander = _browser()
    bystander_cookie = _login(bystander, bystander_email, bystander_password)
    bystander_token = _plant_reset_token(bystander_id)

    db = SessionLocal()
    try:
        db.add(
            EmailVerificationToken(
                user_id=user_id,
                token_hash=_digest("verification-row"),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        db.add(MfaRecoveryCode(user_id=user_id, code_hash=_digest("recovery-row")))
        db.commit()
    finally:
        db.close()

    requested = _request_reset_token(client, email, monkeypatch)
    sibling_b = _plant_reset_token(user_id)
    sibling_c = _plant_reset_token(user_id)
    assert _unused_reset_count(user_id) == 3

    too_short = client.post(
        "/api/auth/reset-password", json={"token": requested, "new_password": "short"}
    )
    assert too_short.status_code == 400, too_short.status_code
    assert _unused_reset_count(user_id) == 3

    replacement = _password()
    reset = client.post(
        "/api/auth/reset-password", json={"token": requested, "new_password": replacement}
    )
    assert reset.status_code == 200, reset.status_code
    for leftover in (sibling_b, sibling_c, requested):
        again = client.post(
            "/api/auth/reset-password",
            json={"token": leftover, "new_password": _password()},
        )
        assert again.status_code == 400, again.status_code
    assert _unused_reset_count(user_id) == 0

    _replay(client, held)
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.clear()
    assert (
        client.post("/api/auth/login", json={"email": email, "password": old_password}).status_code
        == 401
    )
    assert (
        client.post("/api/auth/login", json={"email": email, "password": replacement}).status_code
        == 200
    )

    db = SessionLocal()
    try:
        verification_left = (
            db.query(EmailVerificationToken)
            .filter(EmailVerificationToken.user_id == user_id)
            .count()
        )
        recovery_left = (
            db.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == user_id).count()
        )
    finally:
        db.close()
    assert verification_left == 1
    assert recovery_left == 1

    _replay(bystander, bystander_cookie)
    assert bystander.get("/api/auth/me").status_code == 200
    assert _unused_reset_count(bystander_id) == 1
    bystander_reset = bystander.post(
        "/api/auth/reset-password",
        json={"token": bystander_token, "new_password": _password()},
    )
    assert bystander_reset.status_code == 200, bystander_reset.status_code


@pytest.mark.parametrize(
    "flag",
    [False, True, None],
    ids=["keep-requested", "revoke-requested", "flag-omitted"],
)
def test_change_password_revokes_the_other_session(
    client: TestClient, mailbox: _Mailbox, isolate, flag: bool | None
) -> None:
    """The session that changed the password stays. Every other cookie is 401.

    ``flag is False`` is the client asking to keep other sessions. That request
    is still revoked.
    """
    email = isolate(_address("change"))
    current_password = _password()
    user_id = _register(client, mailbox, email, current_password)
    current_cookie = _login(client, email, current_password)

    other = _browser()
    other_cookie = _login(other, email, current_password)
    assert client.get("/api/auth/me").status_code == 200
    assert other.get("/api/auth/me").status_code == 200

    stranger_email = isolate(_address("stranger"))
    stranger_password = _password()
    _register(client, mailbox, stranger_email, stranger_password)
    stranger = _browser()
    stranger_cookie = _login(stranger, stranger_email, stranger_password)

    replacement = _password()
    body: dict = {"current_password": current_password, "new_password": replacement}
    if flag is not None:
        body["invalidate_other_sessions"] = flag
    changed = client.post("/api/auth/change-password", json=body)
    assert changed.status_code == 200, changed.status_code
    _replay(client, current_cookie)
    assert client.get("/api/auth/me").status_code == 200
    _replay(other, other_cookie)
    assert other.get("/api/auth/me").status_code == 401
    assert changed.json()["revoked"] >= 1
    _replay(stranger, stranger_cookie)
    assert stranger.get("/api/auth/me").status_code == 200
    assert _unused_reset_count(user_id) == 0

    client.cookies.clear()
    assert (
        client.post(
            "/api/auth/login", json={"email": email, "password": current_password}
        ).status_code
        == 401
    )
    assert (
        client.post("/api/auth/login", json={"email": email, "password": replacement}).status_code
        == 200
    )


def test_wrong_current_password_does_not_revoke_the_other_session(
    client: TestClient, mailbox: _Mailbox, isolate
) -> None:
    email = isolate(_address("wrong"))
    current_password = _password()
    _register(client, mailbox, email, current_password)
    current_cookie = _login(client, email, current_password)
    other = _browser()
    other_cookie = _login(other, email, current_password)

    refused = client.post(
        "/api/auth/change-password",
        json={
            "current_password": _password(),
            "new_password": _password(),
            "invalidate_other_sessions": False,
        },
    )
    assert refused.status_code == 400, refused.status_code
    _replay(client, current_cookie)
    assert client.get("/api/auth/me").status_code == 200
    _replay(other, other_cookie)
    assert other.get("/api/auth/me").status_code == 200
