"""Verified registration, isolated workspace creation, and the rejected shortcuts.

Password signup must verify through the mailed code or link and, under self-signup,
receive a new workspace. Provider sign-in must not join workspace 1. An unverified
provider email is rejected. A password chosen before verification cannot survive an
invite or be attached to a provider. Verification codes are bound to the account,
expire, and lock out.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.routes.auth import _oauth_create_signed_state
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.invite_codes import generate_invite_code_pair, hash_invite_code
from app.core.password import hash_password
from app.models import (
    AuditEvent,
    EmailVerificationToken,
    Invite,
    PasswordResetToken,
    User,
    UserOAuthAccount,
    UserSession,
    Workspace,
    WorkspaceMember,
)
from app.services.email_service import set_email_provider

PROVIDERS = ("google", "github", "microsoft", "oidc", "idme")
SEEDED_WORKSPACES = (1, 2, 3)
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
    return f"reg-{label}-{secrets.token_hex(4)}@example.test"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _policy(monkeypatch, policy: str) -> None:
    monkeypatch.setenv("SIGNUP_POLICY", policy)
    get_settings.cache_clear()


def _mailed(box: _Mailbox) -> tuple[str, str, str]:
    assert box.messages, "verification message was not sent"
    body = box.messages[-1].body_text
    code = _CODE_RE.search(body)
    link = _LINK_RE.search(body)
    assert code is not None and link is not None
    return code.group(1), link.group(1), link.group(2)


def _register(client: TestClient, box: _Mailbox, email: str, password: str) -> tuple[str, str, str]:
    before = len(box.messages)
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "display_name": "Synthetic"},
    )
    assert response.status_code == 200, response.status_code
    assert response.json()["message"] == _GENERIC
    assert len(box.messages) == before + 1
    return _mailed(box)


def _account(email: str) -> dict | None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one_or_none()
        if user is None:
            return None
        memberships = (
            db.query(WorkspaceMember.workspace_id, WorkspaceMember.role)
            .filter(WorkspaceMember.user_id == user.id)
            .order_by(WorkspaceMember.workspace_id)
            .all()
        )
        providers = [
            row[0]
            for row in db.query(UserOAuthAccount.provider)
            .filter(UserOAuthAccount.user_id == user.id)
            .order_by(UserOAuthAccount.provider)
            .all()
        ]
        sessions = db.query(UserSession).filter(UserSession.user_id == user.id).count()
        return {
            "id": user.id,
            "verified": bool(user.email_verified),
            "memberships": [(int(workspace_id), role) for workspace_id, role in memberships],
            "providers": providers,
            "sessions": int(sessions),
        }
    finally:
        db.close()


def _purge(email: str) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one_or_none()
        db.query(Invite).filter(Invite.email == email).delete(synchronize_session=False)
        db.query(AuditEvent).filter(AuditEvent.email == email).delete(synchronize_session=False)
        if user is not None:
            workspace_ids = [
                int(row[0])
                for row in db.query(WorkspaceMember.workspace_id)
                .filter(WorkspaceMember.user_id == user.id)
                .all()
            ]
            extra = [wid for wid in workspace_ids if wid not in SEEDED_WORKSPACES]
            db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).delete(
                synchronize_session=False
            )
            if extra:
                db.query(Workspace).filter(Workspace.id.in_(extra)).delete(
                    synchronize_session=False
                )
            db.query(UserOAuthAccount).filter(UserOAuthAccount.user_id == user.id).delete(
                synchronize_session=False
            )
            db.query(EmailVerificationToken).filter(
                EmailVerificationToken.user_id == user.id
            ).delete(synchronize_session=False)
            db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).delete(
                synchronize_session=False
            )
            db.query(UserSession).filter(UserSession.user_id == user.id).delete(
                synchronize_session=False
            )
            db.query(AuditEvent).filter(AuditEvent.user_id == user.id).delete(
                synchronize_session=False
            )
            db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _deny_workspace_one(client: TestClient) -> None:
    response = client.get("/api/documents", params={"workspace_id": 1})
    assert response.status_code == 403, response.status_code


def _callback_target(client: TestClient, provider: str) -> tuple[str, str]:
    client.cookies.clear()
    if provider in ("google", "github"):
        state = _oauth_create_signed_state(provider)
        return f"/api/auth/oauth/{provider}/callback", state
    state = secrets.token_urlsafe(16)
    if provider == "microsoft":
        client.cookies.set("oauth_state", f"{state}|microsoft")
        return "/api/auth/oauth/microsoft/callback", state
    if provider == "oidc":
        client.cookies.set("sso_state", state)
        return "/api/auth/sso/callback", state
    client.cookies.set("idme_state", state)
    return "/api/auth/idme/callback", state


def _callback(
    client: TestClient,
    provider: str,
    *,
    email: str,
    verified: bool,
    provider_user_id: str | None = None,
):
    info = {
        "provider_user_id": provider_user_id or f"{provider}-{secrets.token_hex(8)}",
        "email": email,
        "name": "Synthetic Person",
        "email_verified": verified,
    }

    async def _exchange(*_args, **_kwargs):
        return info

    async def _discover(*_args, **_kwargs):
        return {
            "authorization_endpoint": "https://idp.example.test/authorize",
            "token_endpoint": "https://idp.example.test/token",
            "userinfo_endpoint": "https://idp.example.test/userinfo",
        }

    targets = {
        "google": "app.api.routes.auth.google_exchange_code",
        "github": "app.api.routes.auth.github_exchange_code",
        "microsoft": "app.api.routes.auth.microsoft_exchange_code",
        "oidc": "app.api.routes.auth.oidc_exchange_code",
        "idme": "app.api.routes.auth.idme_exchange_code",
    }
    path, state = _callback_target(client, provider)
    with ExitStack() as stack:
        stack.enter_context(patch(targets[provider], _exchange))
        if provider == "oidc":
            stack.enter_context(patch("app.api.routes.auth.oidc_discover", _discover))
        return client.get(
            path,
            params={"code": "synthetic-code", "state": state},
            follow_redirects=False,
        )


def _expire(user_id: int, secret: str) -> None:
    db = SessionLocal()
    try:
        row = (
            db.query(EmailVerificationToken)
            .filter(
                EmailVerificationToken.user_id == user_id,
                EmailVerificationToken.token_hash == _digest(secret),
            )
            .one()
        )
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def mailbox():
    box = _Mailbox()
    set_email_provider(box)
    yield box
    set_email_provider(None)


@pytest.fixture(autouse=True)
def _workspace_ids_follow_seed(_ensure_test_data):
    """Seeded workspace ids are inserted explicitly, so the sequence can still point at them."""
    if not _ensure_test_data:
        return
    db = SessionLocal()
    try:
        db.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('workspaces', 'id'), "
                "(SELECT COALESCE(MAX(id), 1) FROM workspaces))"
            )
        )
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch):
    monkeypatch.setenv("OIDC_DEFAULT_WORKSPACE_ID", "1")
    monkeypatch.delenv("SIGNUP_POLICY", raising=False)
    get_settings.cache_clear()
    from app.core.rate_limit import _store

    _store.clear()
    yield
    get_settings.cache_clear()
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


def test_unset_oidc_workspace_is_not_workspace_one(monkeypatch) -> None:
    monkeypatch.delenv("OIDC_DEFAULT_WORKSPACE_ID", raising=False)
    get_settings.cache_clear()
    assert get_settings().oidc_default_workspace_id is None
    monkeypatch.setenv("OIDC_DEFAULT_WORKSPACE_ID", "default")
    get_settings.cache_clear()
    assert get_settings().oidc_default_workspace_id is None
    monkeypatch.setenv("OIDC_DEFAULT_WORKSPACE_ID", "1")
    get_settings.cache_clear()
    assert get_settings().oidc_default_workspace_id == 1


def test_mail_verify_code_creates_isolated_workspace(
    client: TestClient, mailbox: _Mailbox, isolate, monkeypatch
) -> None:
    """TC-04-001-AC1: register, mailed code, verify-code, login, own workspace."""
    _policy(monkeypatch, "self_signup")
    email = isolate(_address("code"))
    password = _password()
    code, _link, _user_id = _register(client, mailbox, email, password)
    verified = client.post("/api/auth/verify-code", json={"email": email, "code": code})
    assert verified.status_code == 200, verified.status_code
    reused = client.post("/api/auth/verify-code", json={"email": email, "code": code})
    assert reused.status_code == 400, reused.status_code
    assert _account(email)["verified"] is True
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.status_code
    assert login.json().get("needs_onboarding") is True
    _deny_workspace_one(client)
    created = client.post("/api/workspaces", json={"name": f"Isolated {secrets.token_hex(4)}"})
    assert created.status_code == 200, created.status_code
    workspace_id = created.json()["id"]
    assert workspace_id not in SEEDED_WORKSPACES
    assert _account(email)["memberships"] == [(workspace_id, "admin")]
    _deny_workspace_one(client)
    own = client.get("/api/documents", params={"workspace_id": workspace_id})
    assert own.status_code == 200, own.status_code


def test_mail_verify_email_creates_isolated_workspace(
    client: TestClient, mailbox: _Mailbox, isolate, monkeypatch
) -> None:
    """TC-04-001-AC1: the mailed link is bound to the user and leads to a new workspace."""
    _policy(monkeypatch, "self_signup")
    email = isolate(_address("link"))
    password = _password()
    _code, link, user_id = _register(client, mailbox, email, password)
    verified = client.post("/api/auth/verify-email", params={"token": link, "user": user_id})
    assert verified.status_code == 200, verified.status_code
    reused = client.post("/api/auth/verify-email", params={"token": link, "user": user_id})
    assert reused.status_code == 400, reused.status_code
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.status_code
    assert login.json().get("needs_onboarding") is True
    created = client.post("/api/workspaces", json={"name": f"Linked {secrets.token_hex(4)}"})
    assert created.status_code == 200, created.status_code
    workspace_id = created.json()["id"]
    assert workspace_id not in SEEDED_WORKSPACES
    assert _account(email)["memberships"] == [(workspace_id, "admin")]
    _deny_workspace_one(client)


def test_invitation_only_verified_signup_cannot_join_workspace_one(
    client: TestClient, mailbox: _Mailbox, isolate, monkeypatch
) -> None:
    """TC-04-001-AC2: a verified password signup still follows invitation-only."""
    _policy(monkeypatch, "invitation_only")
    email = isolate(_address("invite-only"))
    password = _password()
    code, _link, _user_id = _register(client, mailbox, email, password)
    assert (
        client.post("/api/auth/verify-code", json={"email": email, "code": code}).status_code == 200
    )
    assert (
        client.post("/api/auth/login", json={"email": email, "password": password}).status_code
        == 200
    )
    created = client.post("/api/workspaces", json={"name": f"Denied {secrets.token_hex(4)}"})
    assert created.status_code == 403, created.status_code
    assert _account(email)["memberships"] == []
    _deny_workspace_one(client)


def test_duplicate_registration_does_not_replace_password(
    client: TestClient, mailbox: _Mailbox, isolate
) -> None:
    """TC-04-001-AC2: a second registration leaves the first password and sends nothing."""
    email = isolate(_address("duplicate"))
    first = _password()
    second = _password()
    code, _link, _user_id = _register(client, mailbox, email, first)
    again = client.post(
        "/api/auth/register",
        json={"email": email, "password": second, "display_name": "Other"},
    )
    assert again.status_code == 200, again.status_code
    assert again.json()["message"] == _GENERIC
    assert len(mailbox.messages) == 1
    account = _account(email)
    assert account is not None
    assert account["verified"] is False
    assert account["memberships"] == []
    assert (
        client.post("/api/auth/verify-code", json={"email": email, "code": code}).status_code == 200
    )
    denied = client.post("/api/auth/login", json={"email": email, "password": second})
    assert denied.status_code == 401, denied.status_code
    allowed = client.post("/api/auth/login", json={"email": email, "password": first})
    assert allowed.status_code == 200, allowed.status_code
    assert _account(email)["memberships"] == []


def test_pre_registered_invite_replaces_password_and_revokes_session(
    client: TestClient, mailbox: _Mailbox, isolate
) -> None:
    """Attacker password and session die when the invited person claims the account."""
    email = isolate(_address("takeover"))
    attacker = _password()
    _register(client, mailbox, email, attacker)
    assert _account(email)["memberships"] == []
    signed_in = client.post("/api/auth/login", json={"email": email, "password": attacker})
    assert signed_in.status_code == 200, signed_in.status_code
    assert signed_in.json().get("needs_onboarding") is True
    _deny_workspace_one(client)
    held = client.cookies.get("tc_session")
    assert held
    formatted, _normalized = generate_invite_code_pair()
    db = SessionLocal()
    try:
        db.add(
            Invite(
                workspace_id=1,
                email=email,
                role="editor",
                token_hash=_digest(secrets.token_urlsafe(16)),
                invite_code_hash=hash_invite_code(formatted),
                expires_at=datetime.now(timezone.utc) + timedelta(days=2),
            )
        )
        db.commit()
    finally:
        db.close()
    verified = client.post("/api/auth/verify-invite-code", json={"email": email, "code": formatted})
    assert verified.status_code == 200, verified.status_code
    token = verified.json()["token"]
    missing = client.post("/api/auth/accept-invite", json={"token": token})
    assert missing.status_code == 400, missing.status_code
    assert _account(email)["verified"] is False
    assert _account(email)["memberships"] == []
    chosen = _password()
    accepted = client.post("/api/auth/accept-invite", json={"token": token, "password": chosen})
    assert accepted.status_code == 200, accepted.status_code
    client.cookies.clear()
    client.cookies.set("tc_session", held)
    stale = client.get("/api/auth/me")
    assert stale.status_code == 401, stale.status_code
    client.cookies.clear()
    denied = client.post("/api/auth/login", json={"email": email, "password": attacker})
    assert denied.status_code == 401, denied.status_code
    allowed = client.post("/api/auth/login", json={"email": email, "password": chosen})
    assert allowed.status_code == 200, allowed.status_code
    assert allowed.json().get("workspace_id") == 1
    assert _account(email)["memberships"] == [(1, "editor")]
    assert _account(email)["verified"] is True


def test_verify_code_lockout_rejects_the_correct_code(
    client: TestClient, mailbox: _Mailbox, isolate
) -> None:
    email = isolate(_address("lockout"))
    code, _link, _user_id = _register(client, mailbox, email, _password())
    wrong = "000000" if code != "000000" else "000001"
    for _ in range(5):
        failed = client.post("/api/auth/verify-code", json={"email": email, "code": wrong})
        assert failed.status_code == 400, failed.status_code
    locked = client.post("/api/auth/verify-code", json={"email": email, "code": code})
    assert locked.status_code == 429, locked.status_code
    assert _account(email)["verified"] is False


def test_verify_email_is_bound_to_the_user(client: TestClient, mailbox: _Mailbox, isolate) -> None:
    """A code is not a global credential, and one user's link does not verify another."""
    first = isolate(_address("bound-a"))
    second = isolate(_address("bound-b"))
    code_a, link_a, user_a = _register(client, mailbox, first, _password())
    code_b, _link_b, user_b = _register(client, mailbox, second, _password())
    cross_code = client.post("/api/auth/verify-code", json={"email": second, "code": code_a})
    assert cross_code.status_code == 400, cross_code.status_code
    code_as_link = client.post("/api/auth/verify-email", params={"token": code_a, "user": user_a})
    assert code_as_link.status_code == 400, code_as_link.status_code
    code_alone = client.post("/api/auth/verify-email", params={"token": code_a})
    assert code_alone.status_code == 400, code_alone.status_code
    other_user = client.post("/api/auth/verify-email", params={"token": link_a, "user": user_b})
    assert other_user.status_code == 400, other_user.status_code
    assert _account(first)["verified"] is False
    assert _account(second)["verified"] is False
    own = client.post("/api/auth/verify-email", params={"token": link_a, "user": user_a})
    assert own.status_code == 200, own.status_code
    assert _account(first)["verified"] is True
    assert _account(second)["verified"] is False
    still = client.post("/api/auth/verify-code", json={"email": second, "code": code_b})
    assert still.status_code == 200, still.status_code


def test_expired_code_and_link_are_rejected(client: TestClient, mailbox: _Mailbox, isolate) -> None:
    email = isolate(_address("expired"))
    code, link, user_id = _register(client, mailbox, email, _password())
    account = _account(email)
    assert account is not None
    _expire(account["id"], code)
    expired_code = client.post("/api/auth/verify-code", json={"email": email, "code": code})
    assert expired_code.status_code == 400, expired_code.status_code
    assert _account(email)["verified"] is False
    _expire(account["id"], link)
    expired_link = client.post("/api/auth/verify-email", params={"token": link, "user": user_id})
    assert expired_link.status_code == 400, expired_link.status_code
    assert _account(email)["verified"] is False


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("policy", ("invitation_only", "self_signup"))
def test_provider_new_identity_is_isolated(
    client: TestClient, isolate, monkeypatch, provider: str, policy: str
) -> None:
    """A verified provider identity gets pending onboarding, never workspace 1."""
    _policy(monkeypatch, policy)
    assert get_settings().oidc_default_workspace_id == 1
    email = isolate(_address(f"{provider}-{policy}"))
    response = _callback(client, provider, email=email, verified=True)
    assert response.status_code == 302, response.status_code
    assert response.headers["location"].endswith("/onboarding")
    assert "@" not in response.text
    me = client.get("/api/auth/me")
    assert me.status_code == 200, me.status_code
    body = me.json()
    assert body["needs_onboarding"] is True
    assert body["workspace_id"] == 0
    assert body["role"] == "pending"
    account = _account(email)
    assert account is not None
    assert account["verified"] is True
    assert account["memberships"] == []
    assert account["providers"] == [provider]
    _deny_workspace_one(client)
    created = client.post("/api/workspaces", json={"name": f"Provider {secrets.token_hex(4)}"})
    if policy == "invitation_only":
        assert created.status_code == 403, created.status_code
        assert _account(email)["memberships"] == []
        return
    assert created.status_code == 200, created.status_code
    workspace_id = created.json()["id"]
    assert workspace_id not in SEEDED_WORKSPACES
    assert _account(email)["memberships"] == [(workspace_id, "admin")]
    _deny_workspace_one(client)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_rejects_unverified_email(client: TestClient, isolate, provider: str) -> None:
    email = isolate(_address(f"{provider}-unverified"))
    response = _callback(client, provider, email=email, verified=False)
    assert response.status_code == 400, response.status_code
    assert "@" not in response.text
    assert "tc_session" not in response.cookies
    assert _account(email) is None


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_does_not_attach_unverified_email_to_existing_account(
    client: TestClient, isolate, provider: str
) -> None:
    email = isolate(_address(f"{provider}-existing"))
    password = _password()
    db = SessionLocal()
    try:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                display_name="Existing",
                email_verified=True,
            )
        )
        db.commit()
    finally:
        db.close()
    response = _callback(client, provider, email=email, verified=False)
    assert response.status_code == 400, response.status_code
    account = _account(email)
    assert account is not None
    assert account["verified"] is True
    assert account["providers"] == []
    assert account["memberships"] == []
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.status_code
    _deny_workspace_one(client)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_refuses_unverified_pre_registered_account(
    client: TestClient, mailbox: _Mailbox, isolate, provider: str
) -> None:
    email = isolate(_address(f"{provider}-prereg"))
    password = _password()
    _register(client, mailbox, email, password)
    response = _callback(client, provider, email=email, verified=True)
    assert response.status_code == 400, response.status_code
    assert "@" not in response.text
    account = _account(email)
    assert account is not None
    assert account["verified"] is False
    assert account["providers"] == []
    assert account["memberships"] == []
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.status_code
    assert login.json().get("needs_onboarding") is True
    _deny_workspace_one(client)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_verified_member_keeps_existing_workspace(
    client: TestClient, isolate, provider: str
) -> None:
    """Linking a verified member does not move them and does not add workspace 1."""
    email = isolate(_address(f"{provider}-member"))
    password = _password()
    db = SessionLocal()
    try:
        user = User(
            email=email,
            password_hash=hash_password(password),
            display_name="Member",
            email_verified=True,
        )
        db.add(user)
        db.flush()
        db.add(WorkspaceMember(workspace_id=2, user_id=user.id, role="editor"))
        db.commit()
    finally:
        db.close()
    response = _callback(client, provider, email=email, verified=True)
    assert response.status_code == 302, response.status_code
    assert response.headers["location"].endswith("/dashboard")
    me = client.get("/api/auth/me")
    assert me.status_code == 200, me.status_code
    assert me.json()["workspace_id"] == 2
    assert _account(email)["memberships"] == [(2, "editor")]
    assert _account(email)["providers"] == [provider]
    denied = client.get("/api/documents", params={"workspace_id": 1})
    assert denied.status_code == 403, denied.status_code
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.status_code
