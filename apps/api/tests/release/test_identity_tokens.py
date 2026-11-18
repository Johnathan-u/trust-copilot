"""TC-04-002: password-reset send failures stay recoverable, and one reset token
is single-use under a concurrent redeem.

A failed provider call must not delete a previously delivered unused link, and
the HTTP response stays the same sentence for a known address and an unknown
one. Two overlapping redeems of that same token must produce one success.
SQLite drops ``FOR UPDATE``, so the overlap test runs on PostgreSQL only.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

import app.api.routes.auth as auth_routes
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

_GENERIC = "If that email is registered, you will receive a reset link."
_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_USER_RE = re.compile(r"[?&]user=(\d+)")


class _ScriptedMail:
    def __init__(self) -> None:
        self.messages: list = []
        self.accept = True
        self.error: BaseException | None = None

    def send(self, message) -> bool:
        self.messages.append(message)
        if self.error is not None:
            raise self.error
        return self.accept


def _password() -> str:
    return secrets.token_urlsafe(18)


def _address(label: str) -> str:
    return f"reset-token-{label}-{secrets.token_hex(4)}@example.test"


def _register(client: TestClient, box: _ScriptedMail, email: str, password: str) -> int:
    before = len(box.messages)
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "display_name": "Synthetic"},
    )
    assert response.status_code == 200, response.text
    assert len(box.messages) == before + 1
    body = box.messages[-1].body_text
    match = _CODE_RE.search(body)
    assert match is not None
    verified = client.post("/api/auth/verify-code", json={"email": email, "code": match.group(1)})
    assert verified.status_code == 200, verified.text
    user = _USER_RE.search(body)
    assert user is not None
    return int(user.group(1))


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


def _unused(user_id: int) -> list[str]:
    db = SessionLocal()
    try:
        rows = (
            db.query(PasswordResetToken)
            .filter(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used_at.is_(None),
            )
            .order_by(PasswordResetToken.id)
            .all()
        )
        return [row.token_hash for row in rows]
    finally:
        db.close()


def _reset_audits(email: str) -> list[tuple[str, str | None]]:
    db = SessionLocal()
    try:
        rows = (
            db.query(AuditEvent)
            .filter(AuditEvent.email == email, AuditEvent.action.like("auth.reset%"))
            .order_by(AuditEvent.id)
            .all()
        )
        return [(row.action, row.details) for row in rows]
    finally:
        db.close()


def _browser() -> TestClient:
    from app.main import app

    return TestClient(
        app, base_url=TEST_ORIGIN, headers=TEST_HEADERS, raise_server_exceptions=False
    )


def _token_from(response) -> str:
    reset_url = response.json().get("reset_url")
    assert isinstance(reset_url, str) and reset_url
    token = parse_qs(urlsplit(reset_url).query).get("token", [None])[0]
    assert isinstance(token, str) and token
    return token


def _postgres() -> bool:
    db = SessionLocal()
    try:
        return db.get_bind().dialect.name == "postgresql"
    finally:
        db.close()


@pytest.fixture
def box():
    scripted = _ScriptedMail()
    set_email_provider(scripted)
    yield scripted
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


def _issue(client: TestClient, email: str, monkeypatch):
    monkeypatch.setenv("TRUST_COPILOT_DEV_RETURN_RESET_URL", "true")
    response = client.post("/api/auth/forgot-password", json={"email": email})
    assert response.status_code == 200, response.text
    return response


@pytest.mark.parametrize("mode", ["rejected", "raised"])
def test_failed_reset_send_keeps_the_previous_token(
    client: TestClient, box: _ScriptedMail, isolate, monkeypatch, mode: str
) -> None:
    """A false or raised send leaves the delivered link usable and unsent row gone."""
    email = isolate(_address(mode))
    user_id = _register(client, box, email, _password())
    issued = _issue(client, email, monkeypatch)
    previous = _token_from(issued)
    assert _unused(user_id) == [_token_hash(previous)]

    if mode == "raised":
        box.error = RuntimeError("smtp down")
        reason = "provider_error"
    else:
        box.accept = False
        reason = "provider_rejected"
    failed = client.post("/api/auth/forgot-password", json={"email": email})
    unknown_address = isolate(_address(f"unknown-{mode}"))
    unknown = client.post("/api/auth/forgot-password", json={"email": unknown_address})

    assert failed.status_code == 200, failed.text
    assert unknown.status_code == 200, unknown.text
    assert _unused(user_id) == [_token_hash(previous)]
    assert failed.json() == unknown.json() == {"message": _GENERIC}
    assert "reset_url" not in failed.json()
    assert "smtp" not in failed.text.lower()
    assert email not in failed.text
    assert _reset_audits(unknown_address) == []

    audits = _reset_audits(email)
    assert [action for action, _details in audits] == [
        "auth.reset_requested",
        "auth.reset_send_failed",
    ]
    details = audits[-1][1] or ""
    parsed = json.loads(details)
    assert parsed == {"reason": reason}
    assert previous not in details

    replacement = _password()
    reset = client.post(
        "/api/auth/reset-password",
        json={"token": previous, "new_password": replacement},
    )
    assert reset.status_code == 200, reset.text
    client.cookies.clear()
    assert (
        client.post("/api/auth/login", json={"email": email, "password": replacement}).status_code
        == 200
    )


def test_failed_first_reset_send_leaves_no_token(
    client: TestClient, box: _ScriptedMail, isolate, monkeypatch
) -> None:
    """With no earlier link, a rejected send commits nothing the caller can use."""
    email = isolate(_address("first-fail"))
    user_id = _register(client, box, email, _password())
    monkeypatch.setenv("TRUST_COPILOT_DEV_RETURN_RESET_URL", "true")
    box.accept = False
    failed = client.post("/api/auth/forgot-password", json={"email": email})
    assert failed.status_code == 200, failed.text
    assert _unused(user_id) == []
    assert failed.json() == {"message": _GENERIC}
    audits = _reset_audits(email)
    assert [action for action, _details in audits] == ["auth.reset_send_failed"]
    assert json.loads(audits[0][1] or "") == {"reason": "provider_rejected"}

    box.accept = True
    issued = _issue(client, email, monkeypatch)
    token = _token_from(issued)
    assert _unused(user_id) == [_token_hash(token)]


def test_successful_resend_replaces_the_older_token(
    client: TestClient, box: _ScriptedMail, isolate, monkeypatch
) -> None:
    """A later accepted send is the only unused link. The earlier link is 400."""
    email = isolate(_address("resend"))
    user_id = _register(client, box, email, _password())
    first = _token_from(_issue(client, email, monkeypatch))
    second = _token_from(_issue(client, email, monkeypatch))
    assert first != second
    assert _unused(user_id) == [_token_hash(second)]
    stale = client.post(
        "/api/auth/reset-password",
        json={"token": first, "new_password": _password()},
    )
    assert stale.status_code == 400, stale.text
    assert _unused(user_id) == [_token_hash(second)]


def test_used_reset_token_cannot_be_reused(
    client: TestClient, box: _ScriptedMail, isolate, monkeypatch
) -> None:
    """The second submit of a token that already changed the password is 400."""
    email = isolate(_address("single-use"))
    old_password = _password()
    user_id = _register(client, box, email, old_password)
    token = _token_from(_issue(client, email, monkeypatch))
    first_password = _password()
    second_password = _password()
    assert first_password != second_password
    reset = client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": first_password},
    )
    assert reset.status_code == 200, reset.text
    again = client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": second_password},
    )
    assert again.status_code == 400, again.text
    assert _unused(user_id) == []
    client.cookies.clear()
    assert (
        client.post("/api/auth/login", json={"email": email, "password": old_password}).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login", json={"email": email, "password": second_password}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login", json={"email": email, "password": first_password}
        ).status_code
        == 200
    )


def test_forgot_password_response_matches_for_known_and_unknown(
    client: TestClient, box: _ScriptedMail, isolate, monkeypatch
) -> None:
    """Without the dev flag, a delivered send and an unknown address are the same body."""
    email = isolate(_address("same-body"))
    user_id = _register(client, box, email, _password())
    monkeypatch.delenv("TRUST_COPILOT_DEV_RETURN_RESET_URL", raising=False)
    known = client.post("/api/auth/forgot-password", json={"email": email})
    unknown_address = isolate(_address("missing"))
    unknown = client.post("/api/auth/forgot-password", json={"email": unknown_address})
    assert known.status_code == 200, known.text
    assert unknown.status_code == 200, unknown.text
    assert known.json() == unknown.json() == {"message": _GENERIC}
    assert _reset_audits(unknown_address) == []
    assert len(_unused(user_id)) == 1


def test_concurrent_redeem_of_one_reset_token_succeeds_once(
    client: TestClient, box: _ScriptedMail, isolate, monkeypatch
) -> None:
    """Two in-flight submits of one token: the request that holds the row wins.

    The pause is inside password hashing, which runs only after the unused row
    is locked. On PostgreSQL the other submit waits on ``SELECT ... FOR UPDATE``
    and then finds no row. SQLite compiles that clause away, so the overlap is
    not a lock test there.
    """
    if not _postgres():
        pytest.skip(
            "same-token reset race needs PostgreSQL row locks "
            "(SELECT ... FOR UPDATE); SQLite cannot make this race meaningful"
        )
    email = isolate(_address("race"))
    _register(client, box, email, _password())
    token = _token_from(_issue(client, email, monkeypatch))
    password_one = _password()
    password_two = _password()
    assert password_one != password_two
    targets = {password_one, password_two}
    arrived: list[str] = []
    release = threading.Event()
    guard = threading.Lock()
    original = auth_routes.hash_password

    def slow_hash(password: str) -> str:
        if password in targets:
            with guard:
                arrived.append(password)
                if len(arrived) >= 2:
                    release.set()
            # The lock holder must not wait for the other submit to enter this
            # function: that submit is blocked in the row lock. Two seconds is
            # long enough for it to be waiting, and long enough that an unlocked
            # pair both hash before either commit.
            release.wait(timeout=2)
        return original(password)

    http_one = _browser()
    http_two = _browser()
    start = threading.Barrier(2)
    found: list[tuple[str, int, str]] = []
    errors: list[BaseException] = []
    report_guard = threading.Lock()

    def post(http: TestClient, password: str) -> None:
        try:
            start.wait(timeout=10)
            response = http.post(
                "/api/auth/reset-password",
                json={"token": token, "new_password": password},
            )
            with report_guard:
                found.append((password, response.status_code, response.text))
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    try:
        with patch.object(auth_routes, "hash_password", slow_hash):
            threads = [
                threading.Thread(target=post, args=(http_one, password_one)),
                threading.Thread(target=post, args=(http_two, password_two)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
            assert [thread.is_alive() for thread in threads] == [False, False]
        assert errors == [], errors
        codes = sorted(item[1] for item in found)
        detail = {"codes": codes, "arrived": len(arrived), "bodies": [item[2] for item in found]}
        assert codes == [200, 400], detail
        assert len(arrived) == 1, detail
        winner = next(password for password, status, _body in found if status == 200)
        loser = next(password for password, status, _body in found if status == 400)
        check = _browser()
        try:
            assert (
                check.post("/api/auth/login", json={"email": email, "password": loser}).status_code
                == 401
            )
            assert (
                check.post("/api/auth/login", json={"email": email, "password": winner}).status_code
                == 200
            )
            replay = check.post(
                "/api/auth/reset-password",
                json={"token": token, "new_password": _password()},
            )
            assert replay.status_code == 400, replay.text
        finally:
            check.close()
    finally:
        http_one.close()
        http_two.close()
