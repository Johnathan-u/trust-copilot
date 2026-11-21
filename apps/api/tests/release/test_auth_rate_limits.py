"""TC-04-007b: auth limits hold across processes, with Retry-After, and invite creation is capped.

The backlog command is ``python -m pytest tests/release/test_auth_rate_limits.py -q``
from ``apps/api``. REDIS_URL is unset. A second process must see the same counter
as this one. Login, reset, resend, and invite 429 responses carry Retry-After.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.rate_limit import DEFAULT_MAX_ATTEMPTS, DEFAULT_WINDOW_SECONDS
from app.models import Invite, User, WorkspaceMember

_API_ROOT = Path(__file__).resolve().parents[2]
_GENERIC_RESET = {"message": "If that email is registered, you will receive a reset link."}
_GENERIC_RESEND = {
    "message": "If that email is waiting for verification, a new message is on the way."
}
_RESEND_MAX = 3
_INVITE_VERIFY_MAX = 10
_INVITE_VERIFY_WINDOW = 900


def _address(label: str) -> str:
    return f"tc04007b-{label}-{secrets.token_hex(4)}@example.test"


def _assert_retry_after(response, window: float) -> int:
    raw = response.headers.get("Retry-After")
    assert raw is not None and raw.strip() != "", response.headers
    seconds = int(raw)
    assert 1 <= seconds <= int(window)
    return seconds


def _promote_demo_admin() -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@trust.local").one()
        mem = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == 1)
            .one()
        )
        if mem.role != "admin":
            mem.role = "admin"
            db.commit()
    finally:
        db.close()


def _delete_invites(emails: list[str]) -> None:
    db = SessionLocal()
    try:
        db.query(Invite).filter(Invite.email.in_(emails)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_auth_rate_limit_holds_across_processes(
    monkeypatch: pytest.MonkeyPatch, migrated_db: bool
) -> None:
    """A counter recorded in another process blocks this process on the same key."""
    import app.core.rate_limit as rate_limit

    assert migrated_db
    monkeypatch.delenv("REDIS_URL", raising=False)
    rate_limit._backend = None
    backend = rate_limit._get_backend()
    rate_limit._backend = backend
    rate_limit._store.clear()
    key = f"tc04007b-shared:{secrets.token_hex(8)}"
    script = """
import os
from app.core.rate_limit import is_rate_limited, record_attempt

key = os.environ["TC_RATE_KEY"]
limit = int(os.environ["TC_RATE_N"])
for _ in range(limit):
    record_attempt(key, max_attempts=limit, window_sec=60)
raise SystemExit(0 if is_rate_limited(key, max_attempts=limit, window_sec=60) else 2)
"""
    env = os.environ.copy()
    env.pop("REDIS_URL", None)
    env["TC_RATE_KEY"] = key
    env["TC_RATE_N"] = str(DEFAULT_MAX_ATTEMPTS)
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_API_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    seen = rate_limit.is_rate_limited(
        key, max_attempts=DEFAULT_MAX_ATTEMPTS, window_sec=DEFAULT_WINDOW_SECONDS
    )
    assert seen is True, f"parent did not see the other process; backend={type(backend).__name__}"


def test_login_429_sends_retry_after(client: TestClient) -> None:
    email = _address("login")
    body = {"email": email, "password": "not-the-password"}
    for _ in range(DEFAULT_MAX_ATTEMPTS):
        response = client.post("/api/auth/login", json=body)
        assert response.status_code == 401, response.text
    limited = client.post("/api/auth/login", json=body)
    assert limited.status_code == 429, limited.text
    assert limited.json()["detail"] == "Too many login attempts. Try again later."
    _assert_retry_after(limited, DEFAULT_WINDOW_SECONDS)


def test_forgot_password_429_sends_retry_after(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRUST_COPILOT_DEV_RETURN_RESET_URL", raising=False)
    email = _address("forgot")
    for _ in range(DEFAULT_MAX_ATTEMPTS):
        response = client.post("/api/auth/forgot-password", json={"email": email})
        assert response.status_code == 200, response.text
        assert response.json() == _GENERIC_RESET
    limited = client.post("/api/auth/forgot-password", json={"email": email})
    assert limited.status_code == 429, limited.text
    assert limited.json()["detail"] == "Too many requests. Try again later."
    _assert_retry_after(limited, DEFAULT_WINDOW_SECONDS)


def test_reset_password_429_sends_retry_after(client: TestClient) -> None:
    body = {"token": secrets.token_urlsafe(32), "new_password": "longenough"}
    for _ in range(DEFAULT_MAX_ATTEMPTS):
        response = client.post("/api/auth/reset-password", json=body)
        assert response.status_code == 400, response.text
    limited = client.post("/api/auth/reset-password", json=body)
    assert limited.status_code == 429, limited.text
    assert limited.json()["detail"] == "Too many attempts. Try again later."
    _assert_retry_after(limited, DEFAULT_WINDOW_SECONDS)


def test_resend_verification_429_sends_retry_after(client: TestClient) -> None:
    email = _address("resend")
    for _ in range(_RESEND_MAX):
        response = client.post("/api/auth/resend-verification", json={"email": email})
        assert response.status_code == 200, response.text
        assert response.json() == _GENERIC_RESEND
    limited = client.post("/api/auth/resend-verification", json={"email": email})
    assert limited.status_code == 429, limited.text
    assert limited.json()["detail"] == "Too many requests. Try again later."
    _assert_retry_after(limited, 900)


def test_invite_verify_429_sends_retry_after(client: TestClient) -> None:
    email = _address("verify")
    payload = {"email": email, "code": "WRONG-CODE-HERE"}
    for _ in range(_INVITE_VERIFY_MAX):
        response = client.post("/api/auth/verify-invite-code", json=payload)
        assert response.status_code == 400, response.text
    limited = client.post("/api/auth/verify-invite-code", json=payload)
    assert limited.status_code == 429, limited.text
    assert limited.json()["detail"] == "Too many attempts. Try again later."
    _assert_retry_after(limited, _INVITE_VERIFY_WINDOW)


def test_invite_creation_is_rate_limited(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.routes.members.send_invite_email", lambda *args, **kwargs: True)
    _promote_demo_admin()
    signed_in = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert signed_in.status_code == 200, signed_in.text
    emails = [_address(f"invite-{index}") for index in range(DEFAULT_MAX_ATTEMPTS + 1)]
    _delete_invites(emails)
    try:
        for email in emails[:DEFAULT_MAX_ATTEMPTS]:
            created = client.post("/api/members/invites", json={"email": email, "role": "editor"})
            assert created.status_code == 200, created.text
        blocked_email = emails[-1]
        blocked = client.post(
            "/api/members/invites", json={"email": blocked_email, "role": "editor"}
        )
        assert blocked.status_code == 429, blocked.text
        assert blocked.json()["detail"] == "Too many invites. Try again later."
        _assert_retry_after(blocked, DEFAULT_WINDOW_SECONDS)
        db = SessionLocal()
        try:
            assert db.query(Invite).filter(Invite.email == blocked_email).count() == 0
        finally:
            db.close()
    finally:
        _delete_invites(emails)


def test_rate_limit_bucket_migration_downgrade_and_upgrade(migrated_db: bool) -> None:
    """Downgrade drops the shared table. Upgrade creates it again, empty."""
    if not migrated_db:
        pytest.skip("Postgres test DB unavailable")
    import importlib.util

    from sqlalchemy import inspect

    from app.core.database import engine

    mig_path = _API_ROOT / "alembic" / "versions" / "tc04007b_rate_buckets.py"
    spec = importlib.util.spec_from_file_location("tc04007b_mig", mig_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    env = {**os.environ, "DATABASE_URL": os.environ["DATABASE_URL"], "TRUST_COPILOT_TESTING": "1"}

    def alembic(*args: str) -> str:
        engine.dispose()
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=str(_API_ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr[-2000:]
        return result.stdout

    # Later revisions may sit on this one, so relative "-1" is no longer this file.
    # Downgrade to its parent to drop the table, then return to the current head.
    assert mod.down_revision
    alembic("downgrade", mod.down_revision)
    try:
        engine.dispose()
        assert "rate_limit_buckets" not in inspect(engine).get_table_names()
    finally:
        alembic("upgrade", "head")
    engine.dispose()
    assert "rate_limit_buckets" in inspect(engine).get_table_names()
