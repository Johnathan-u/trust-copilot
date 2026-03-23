"""P14: focused tests for workspace invite verification code flow (AUTH-208)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.routes.auth import _token_hash
from app.core.database import SessionLocal
from app.core.invite_codes import generate_invite_code_pair, hash_invite_code, normalize_invite_code
from app.core.password import hash_password
from app.models import Invite, User, WorkspaceMember


def _promote_demo_admin() -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@trust.local").first()
        if not user:
            return
        mem = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == 1,
        ).first()
        if mem and mem.role != "admin":
            mem.role = "admin"
            db.commit()
    finally:
        db.close()


def _login_admin(client: TestClient) -> None:
    _promote_demo_admin()
    r = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert r.status_code == 200


def _cleanup_invite_email(email: str) -> None:
    db = SessionLocal()
    try:
        db.query(Invite).filter(Invite.email == email).delete()
        db.commit()
    finally:
        db.close()


def _delete_user(email: str) -> None:
    db = SessionLocal()
    try:
        db.query(User).filter(User.email == email).delete()
        db.commit()
    finally:
        db.close()


def test_generate_invite_code_pair_format_and_charset() -> None:
    formatted, raw = generate_invite_code_pair()
    assert len(raw) == 12
    allowed = set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
    assert all(c in allowed for c in raw)
    parts = formatted.split("-")
    assert len(parts) == 3
    assert all(len(p) == 4 for p in parts)
    assert "".join(parts) == raw


def test_normalize_invite_code_strips_noise() -> None:
    assert normalize_invite_code("  ab12-cd34-ef56  ") == "AB12CD34EF56"
    assert hash_invite_code("ab12cd34ef56") == hash_invite_code("AB12-CD34-EF56")


@pytest.mark.usefixtures("client")
class TestInviteP14Backend:
    def test_create_invite_persists_invite_code_hash(self, client: TestClient) -> None:
        _login_admin(client)
        email = "p14_hash@test.local"
        _cleanup_invite_email(email)
        _delete_user(email)

        captured: dict[str, str] = {}

        def _cap(to, inviter_name, workspace_name, verify_url, verification_code):
            captured["code"] = verification_code
            return True

        with patch("app.api.routes.members.send_invite_email", side_effect=_cap):
            r = client.post("/api/members/invites", json={"email": email, "role": "editor"})
        assert r.status_code == 200
        inv_id = r.json()["id"]
        assert len(captured["code"].replace("-", "")) == 12

        db = SessionLocal()
        try:
            inv = db.query(Invite).filter(Invite.id == inv_id).first()
            assert inv is not None
            assert inv.invite_code_hash is not None
            assert len(inv.invite_code_hash) == 64
            assert inv.invite_code_hash == hash_invite_code(captured["code"])
        finally:
            db.close()

    def test_verify_invite_code_accepts_lowercase_and_no_hyphens(self, client: TestClient) -> None:
        _login_admin(client)
        email = "p14_norm@test.local"
        _cleanup_invite_email(email)
        _delete_user(email)

        captured: dict[str, str] = {}

        def _cap(to, inviter_name, workspace_name, verify_url, verification_code):
            captured["code"] = verification_code
            return True

        with patch("app.api.routes.members.send_invite_email", side_effect=_cap):
            assert client.post("/api/members/invites", json={"email": email, "role": "editor"}).status_code == 200

        raw = captured["code"]
        loose = raw.replace("-", "").lower()
        rv = client.post("/api/auth/verify-invite-code", json={"email": email, "code": loose})
        assert rv.status_code == 200
        assert "token" in rv.json()

    def test_verify_invite_code_invalid_code_400(self, client: TestClient) -> None:
        _login_admin(client)
        email = "p14_bad@test.local"
        _cleanup_invite_email(email)
        _delete_user(email)

        with patch("app.api.routes.members.send_invite_email", return_value=True):
            assert client.post("/api/members/invites", json={"email": email, "role": "editor"}).status_code == 200

        rv = client.post(
            "/api/auth/verify-invite-code",
            json={"email": email, "code": "ZZZZ-ZZZZ-ZZZZ"},
        )
        assert rv.status_code == 400

    def test_verify_rotates_token_old_token_rejected(self, client: TestClient) -> None:
        """After verify-invite-code, the initial DB token (never emailed) must not accept."""
        email = "p14_rotate@test.local"
        _cleanup_invite_email(email)
        _delete_user(email)
        pre_token = "p14-pre-rotate-token-xxxxxxxx"
        code_plain = "ABCD-EFGH-JKLM"
        exp = datetime.now(timezone.utc) + timedelta(days=7)
        db = SessionLocal()
        try:
            db.add(
                Invite(
                    workspace_id=1,
                    email=email,
                    role="editor",
                    token_hash=_token_hash(pre_token),
                    invite_code_hash=hash_invite_code(code_plain),
                    expires_at=exp,
                )
            )
            db.commit()
        finally:
            db.close()

        rv = client.post("/api/auth/verify-invite-code", json={"email": email, "code": code_plain})
        assert rv.status_code == 200
        new_tok = rv.json()["token"]

        bad = client.post("/api/auth/accept-invite", json={"token": pre_token, "password": "rotatepass123"})
        assert bad.status_code == 400

        ok = client.post("/api/auth/accept-invite", json={"token": new_tok, "password": "rotatepass123"})
        assert ok.status_code == 200

    def test_legacy_invite_null_code_hash_accepts_token_directly(self, client: TestClient) -> None:
        """Invites with invite_code_hash NULL still work via POST accept-invite with raw token."""
        email = "p14_legacy@test.local"
        _cleanup_invite_email(email)
        _delete_user(email)
        raw_tok = "p14-legacy-url-token-yyyyyyyy"
        exp = datetime.now(timezone.utc) + timedelta(days=7)
        db = SessionLocal()
        try:
            db.add(
                Invite(
                    workspace_id=1,
                    email=email,
                    role="editor",
                    token_hash=_token_hash(raw_tok),
                    invite_code_hash=None,
                    expires_at=exp,
                )
            )
            db.commit()
        finally:
            db.close()

        r = client.post("/api/auth/accept-invite", json={"token": raw_tok, "password": "legacypass123"})
        assert r.status_code == 200
        login_r = client.post("/api/auth/login", json={"email": email, "password": "legacypass123"})
        assert login_r.status_code == 200

    def test_create_invite_succeeds_when_email_send_returns_false(self, client: TestClient) -> None:
        _login_admin(client)
        email = "p14_smtp_fail@test.local"
        _cleanup_invite_email(email)
        _delete_user(email)

        with patch("app.api.routes.members.send_invite_email", return_value=False):
            r = client.post("/api/members/invites", json={"email": email, "role": "editor"})
        assert r.status_code == 200
        db = SessionLocal()
        try:
            inv = db.query(Invite).filter(Invite.email == email).first()
            assert inv is not None
            assert inv.invite_code_hash is not None
        finally:
            db.close()

    def test_verify_invite_code_rate_limit_429(self, client: TestClient) -> None:
        email = "p14_rl@test.local"
        _cleanup_invite_email(email)
        _delete_user(email)
        with patch("app.api.routes.members.send_invite_email", return_value=True):
            _login_admin(client)
            assert client.post("/api/members/invites", json={"email": email, "role": "editor"}).status_code == 200

        for _ in range(10):
            r = client.post(
                "/api/auth/verify-invite-code",
                json={"email": email, "code": "WRONG-CODE-HERE"},
            )
            assert r.status_code == 400

        r11 = client.post(
            "/api/auth/verify-invite-code",
            json={"email": email, "code": "WRONG-CODE-HERE"},
        )
        assert r11.status_code == 429

    def test_accept_invite_existing_user_no_password_after_verify(self, client: TestClient) -> None:
        """Existing account: verify code then accept-invite with password omitted joins workspace."""
        email = "p14_exist@test.local"
        _cleanup_invite_email(email)
        db = SessionLocal()
        try:
            existing_u = db.query(User).filter(User.email == email).first()
            if existing_u:
                db.query(WorkspaceMember).filter(
                    WorkspaceMember.user_id == existing_u.id,
                    WorkspaceMember.workspace_id == 1,
                ).delete(synchronize_session=False)
            db.query(User).filter(User.email == email).delete()
            db.add(
                User(
                    email=email,
                    password_hash=hash_password("existingpw123"),
                    display_name="Existing",
                    email_verified=False,
                )
            )
            db.commit()
        finally:
            db.close()

        _login_admin(client)
        captured: dict[str, str] = {}

        def _cap(to, inviter_name, workspace_name, verify_url, verification_code):
            captured["code"] = verification_code
            return True

        with patch("app.api.routes.members.send_invite_email", side_effect=_cap):
            assert client.post("/api/members/invites", json={"email": email, "role": "reviewer"}).status_code == 200

        rv = client.post("/api/auth/verify-invite-code", json={"email": email, "code": captured["code"]})
        assert rv.status_code == 200
        tok = rv.json()["token"]
        ra = client.post("/api/auth/accept-invite", json={"token": tok})
        assert ra.status_code == 200
        login_r = client.post("/api/auth/login", json={"email": email, "password": "existingpw123"})
        assert login_r.status_code == 200
