"""TC-04-006d: expose the already-enforced deadline without renewing authority."""

import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from app.core.mfa import encrypt_totp_secret, generate_totp_secret
from app.core.session import sign_session, verify_token
from app.models import UserMfa, UserSession, Workspace
from tests.release import test_principal_contract
from tests.release.test_remember_policy import snapshot


authority = test_principal_contract.authority


def read(state, status=200):
    before = snapshot(state)
    statements = []

    def capture(_connection, _cursor, sql, _parameters, _context, _many):
        statements.append(sql)

    engine = state["db"].get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    started = time.time()
    try:
        response = state["client"].get("/api/auth/me")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    finished = time.time()
    assert response.status_code == status
    assert "set-cookie" not in response.headers
    assert snapshot(state) == before
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
    if status == 200:
        body = response.json()
        assert started <= body["server_time"] <= finished
        assert body["session_expires_at"] > body["server_time"]
    else:
        assert "session_expires_at" not in response.json()
        assert "server_time" not in response.json()
    return response.json()


@pytest.mark.parametrize("policy", (None, 60, 7200))
@pytest.mark.parametrize("remember", (False, True))
def test_me_reports_earlier_signed_or_current_policy_deadline_without_renewal(
    authority, policy, remember
):
    state = authority
    payload = verify_token(state["cookie"]())
    row = state["db"].query(UserSession).filter_by(session_id=payload["session_id"]).one()
    row.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=10)
    state["db"].get(Workspace, state["ws"][0]).session_max_age_seconds = policy
    state["db"].commit()
    created = row.created_at.replace(tzinfo=timezone.utc).timestamp()
    token = sign_session(
        payload["user_id"],
        payload["email"],
        payload["workspace_id"],
        payload["role"],
        session_id=payload["session_id"],
        expires_at=payload["exp"],
        cookie_persistent=remember,
    )
    state["client"].cookies.set("tc_session", token)
    body = read(state)
    assert body["session_expires_at"] == min(payload["exp"], created + (policy or 604800))
    assert body["id"] == payload["user_id"] and body["workspace_id"] == state["ws"][0]
    assert state["client"].cookies.get("tc_session") == token
    assert read(state)["session_expires_at"] == body["session_expires_at"]


@pytest.mark.parametrize("principal", ("pending", "mfa_enrol"))
def test_account_only_and_mfa_principals_keep_their_existing_restricted_deadlines(
    authority, principal
):
    state = authority
    if principal == "mfa_enrol":
        state["db"].add(
            UserMfa(
                user_id=state["users"][0],
                enabled=False,
                totp_secret_encrypted=encrypt_totp_secret(
                    generate_totp_secret(), reenrol_pending=True
                ),
            )
        )
        state["db"].commit()
    payload = verify_token(
        state["cookie"](principal, pending=principal == "pending", enrol=principal == "mfa_enrol")
    )
    body = read(state)
    assert body["session_expires_at"] == payload["exp"]
    assert body["role"] == principal
    assert not any(body["permissions"].values())


def test_refresh_observes_shorter_policy_and_never_extends_signed_deadline(authority):
    state = authority
    first = read(state)
    state["db"].get(Workspace, state["ws"][0]).session_max_age_seconds = 300
    state["db"].commit()
    shorter = read(state)
    assert shorter["session_expires_at"] < first["session_expires_at"]
    state["db"].get(Workspace, state["ws"][0]).session_max_age_seconds = 7776000
    state["db"].commit()
    assert read(state)["session_expires_at"] == first["session_expires_at"]


@pytest.mark.parametrize("denial,status", (("expired", 401), ("revoked", 401), ("suspended", 403)))
def test_timing_refresh_cannot_revive_expired_or_revoked_authority(authority, denial, status):
    state = authority
    read(state)
    payload = verify_token(state["client"].cookies.get("tc_session"))
    row = state["db"].query(UserSession).filter_by(session_id=payload["session_id"]).one()
    if denial == "expired":
        row.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=8)
    elif denial == "revoked":
        state["db"].delete(row)
    else:
        state["actor"].suspended = True
    state["db"].commit()
    read(state, status)
