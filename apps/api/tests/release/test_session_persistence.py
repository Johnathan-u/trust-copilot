"""Browser persistence and absolute reissue bounds through real stored HTTP auth.

SQLite controls run locally; the identical PostgreSQL cases qualify the migrated
database in CI. OAuth tests exercise the shared issuer, not a live provider.
"""

import copy
import time
from datetime import datetime, timedelta, timezone

import pyotp
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.routes import auth, workspaces
from app.core import session
from app.core.config import SIGNUP_POLICY_SELF_SIGNUP, get_settings
from app.core.database import get_db
from app.core.mfa import encrypt_totp_secret, generate_totp_secret
from app.core.password import hash_password
from app.models import User, UserMfa, UserSession, Workspace, WorkspaceMember
from tests.release import test_remember_policy
from tests.release.test_remember_policy import (
    PASSWORD,
    current_row,
    issued_cookie,
    password_login,
    prepare_login,
    snapshot,
)

pytestmark = pytest.mark.integration
authority = test_remember_policy.authority
policy_state = test_remember_policy.policy_state


def login(state, flow, remember):
    """Use real password/MFA handlers or the existing shared OAuth issuer."""
    client, db = state["client"], state["db"]
    if flow == "pending":
        user = db.get(User, state["users"][1])
        user.password_hash = hash_password(PASSWORD)
        db.commit()
        client.cookies.clear()
        response = password_login(state, user.email, remember)
    elif flow == "oauth":
        # No fake provider response or authentication override. This adapter
        # invokes the actual common issuer after the provider's identity step.
        @client.app.get("/persistence/oauth-issuer")
        def issuer(current: Session = Depends(get_db)):
            return auth._oauth_set_session_and_redirect(
                current.get(User, state["users"][0]), state["ws"][0], "admin", current
            )

        client.cookies.clear()
        response = client.get("/persistence/oauth-issuer", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"].endswith("/dashboard")
        return response
    else:
        email, secret = prepare_login(state, policy=86400, mfa=flow == "mfa")
        if flow == "reenrol":
            secret = generate_totp_secret()
            db.add(
                UserMfa(
                    user_id=state["users"][0],
                    enabled=False,
                    totp_secret_encrypted=encrypt_totp_secret(secret, reenrol_pending=True),
                )
            )
            db.commit()
        response = password_login(state, email, remember)
        assert response.status_code == 200, response.text
        if flow == "mfa":
            assert "set-cookie" not in response.headers
            response = client.post(
                "/api/auth/mfa/verify-login",
                json={
                    "mfa_token": response.json()["mfa_token"],
                    "code": pyotp.TOTP(secret).now(),
                    "remember_me": remember,
                },
            )
        elif flow == "reenrol":
            assert response.json()["requires_mfa_enrol"] is True
            enrollment = session.verify_token(issued_cookie(response).value)
            assert enrollment["cookie_persistent"] is False
            assert issued_cookie(response)["max-age"] == ""
            assert client.get("/authority/can_admin").status_code in (401, 403)
            response = client.post("/api/auth/mfa/confirm", json={"code": pyotp.TOTP(secret).now()})
            assert response.status_code == 200, response.text
            assert len(set(response.json()["recovery_codes"])) == 10
            assert db.query(UserSession).filter_by(session_id=enrollment["session_id"]).count() == 0
    assert response.status_code == 200, response.text
    return response


def reissue(state, action):
    client, db = state["client"], state["db"]
    if action == "switch":
        db.add(
            WorkspaceMember(user_id=state["users"][0], workspace_id=state["ws"][1], role="reviewer")
        )
        db.commit()
        response = client.post("/api/auth/switch-workspace", json={"workspace_id": state["ws"][1]})
    else:
        response = client.post("/api/workspaces", json={"name": f"created-{state['suffix']}"})
        if response.status_code == 200:
            state["ws"].append(response.json()["id"])
    return response


def assert_cookie(response, persistent):
    cookie = issued_cookie(response)
    assert bool(cookie["max-age"]) is persistent
    if persistent:
        assert int(cookie["max-age"]) > 0
    else:
        assert cookie["expires"] == ""
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "lax"
    assert cookie["path"] == "/"
    payload = session.verify_token(cookie.value)
    assert payload["cookie_persistent"] is persistent
    return payload


@pytest.mark.parametrize(
    "flow,remember,persistent,action",
    [
        (flow, remember, remember, action)
        for flow in ("password", "mfa")
        for remember in (False, True)
        for action in ("switch", "create")
    ]
    + [("pending", remember, False, "create") for remember in (False, True)]
    + [
        ("reenrol", remember, False, action)
        for remember in (False, True)
        for action in ("switch", "create")
    ]
    + [("oauth", True, True, action) for action in ("switch", "create")],
)
def test_each_human_issuer_preserves_its_cookie_choice_on_reissue(
    policy_state, monkeypatch, flow, remember, persistent, action
):
    state = policy_state
    monkeypatch.setattr(get_settings(), "signup_policy", SIGNUP_POLICY_SELF_SIGNUP)
    first = assert_cookie(login(state, flow, remember), persistent)
    _, row = current_row(state)
    state["db"].refresh(row)
    row_values = {
        column.name: getattr(row, column.name) for column in UserSession.__table__.columns
    }
    response = reissue(state, action)
    assert response.status_code == 200, response.text
    second = assert_cookie(response, persistent)
    assert second["session_id"] == first["session_id"]
    assert second["exp"] <= first["exp"]
    _, row = current_row(state)
    state["db"].refresh(row)
    assert {
        column.name: getattr(row, column.name) for column in UserSession.__table__.columns
    } == row_values
    info = state["client"].get("/api/auth/me")
    assert info.status_code == 200
    assert info.json()["workspace_id"] == second["workspace_id"]
    assert info.json()["role"] == ("reviewer" if action == "switch" else "admin")

    # A fresh HTTP client discards session cookies using the cookie jar's
    # metadata. This tests server cookie semantics, not a real browser restart.
    with TestClient(state["client"].app) as fresh:
        for cookie in state["client"].cookies.jar:
            fresh.cookies.jar.set_cookie(copy.copy(cookie))
        fresh.cookies.jar.clear_session_cookies()
        assert fresh.get("/api/auth/me").status_code == (200 if persistent else 401)


@pytest.mark.parametrize("action", ("switch", "create"))
@pytest.mark.parametrize("flag", ("absent", None, "true", "false", 1, 0, {}, [], False, True))
def test_only_exact_true_persists_and_legacy_metadata_does_not_invalidate_auth(
    policy_state, action, flag
):
    state = policy_state
    response = login(state, "password", True)
    payload = session.verify_token(issued_cookie(response).value)
    if flag == "absent":
        payload.pop("cookie_persistent", None)
    else:
        payload["cookie_persistent"] = flag
    state["client"].cookies.clear()
    state["client"].cookies.set("tc_session", session.sign_token(payload))
    before = snapshot(state)
    assert state["client"].get("/api/auth/me").status_code == 200
    assert snapshot(state) == before
    response = reissue(state, action)
    assert response.status_code == 200, response.text
    second = assert_cookie(response, flag is True)
    assert second["session_id"] == payload["session_id"]
    assert second["exp"] <= payload["exp"]


@pytest.mark.parametrize("bound", ("signed", "current-policy", "new-workspace-default"))
def test_creation_preserves_the_existing_and_target_absolute_deadlines(
    policy_state, monkeypatch, bound
):
    state = policy_state
    email, _ = prepare_login(state, policy=7776000 if bound == "new-workspace-default" else 86400)
    assert password_login(state, email, True).status_code == 200
    original, row = current_row(state)
    row.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=30)
    if bound == "current-policy":
        state["db"].get(Workspace, state["ws"][0]).session_max_age_seconds = 60
    elif bound == "signed":
        state["db"].get(Workspace, state["ws"][0]).session_max_age_seconds = 604800
    state["db"].commit()
    created = row.created_at.replace(tzinfo=timezone.utc).timestamp()
    deadline = {
        "signed": original["exp"],
        "current-policy": int(created + 60),
        "new-workspace-default": int(created + 604800),
    }[bound]
    response = reissue(state, "create")
    assert response.status_code == 200, response.text
    issued = assert_cookie(response, True)
    assert issued["exp"] == deadline
    assert issued["session_id"] == original["session_id"]
    assert int(issued_cookie(response)["max-age"]) <= deadline - int(time.time())
    assert state["client"].get("/api/auth/me").status_code == 200
    monkeypatch.setattr(session.time, "time", lambda: deadline)
    assert state["client"].get("/api/auth/me").status_code == 401


@pytest.mark.parametrize("expired_during_signing", (False, True))
def test_creation_checks_deadline_after_real_signing_before_any_commit(
    policy_state, monkeypatch, expired_during_signing
):
    state = policy_state
    login(state, "password", False)
    original, _ = current_row(state)
    before = snapshot(state)
    real_sign = workspaces.sign_session
    clock = {"now": int(time.time()) + 0.1}

    def sign_after_clock_advance(*args, **kwargs):
        clock["now"] = original["exp"] + 0.1 if expired_during_signing else clock["now"] + 1.1
        return real_sign(*args, **kwargs)

    monkeypatch.setattr(session.time, "time", lambda: clock["now"])
    monkeypatch.setattr(workspaces, "sign_session", sign_after_clock_advance)
    response = reissue(state, "create")
    if expired_during_signing:
        assert response.status_code == 401
        assert "set-cookie" not in response.headers
        assert snapshot(state) == before
    else:
        assert response.status_code == 200
        assert assert_cookie(response, False)["exp"] == original["exp"]


@pytest.mark.parametrize("stage", ("current", "recheck-current", "new-workspace"))
def test_creation_policy_lookup_failure_has_no_cookie_or_persisted_mutation(policy_state, stage):
    state = policy_state
    login(state, "password", False)
    before = snapshot(state)
    engine = state["db"].get_bind()
    inserted = False
    current_reads = 0

    def fail_policy_read(conn, cursor, statement, parameters, context, executemany):
        nonlocal inserted, current_reads
        if statement.startswith("INSERT INTO workspaces"):
            inserted = True
        if "FROM workspaces" not in statement:
            return
        if "WHERE workspaces.id =" in statement and not inserted:
            current_reads += 1
        if stage == "current" or inserted or (stage == "recheck-current" and current_reads == 2):
            raise OperationalError("synthetic policy lookup failure", {}, RuntimeError("offline"))

    event.listen(engine, "before_cursor_execute", fail_policy_read)
    try:
        # A failed request must not be mistaken for a client-side exception.
        with TestClient(state["client"].app, raise_server_exceptions=False) as failing:
            failing.cookies.update(state["client"].cookies)
            response = failing.post("/api/workspaces", json={"name": f"created-{state['suffix']}"})
    finally:
        event.remove(engine, "before_cursor_execute", fail_policy_read)
    # Track any wrongly committed workspace as owned even when the server
    # returned an error, so the diagnostic's cleanup never treats it as foreign.
    state["ws"].extend(
        value
        for (value,) in state["db"].query(Workspace.id).filter_by(slug=f"created-{state['suffix']}")
        if value not in state["ws"]
    )
    assert snapshot(state) == before
    assert response.status_code == 503
    assert "set-cookie" not in response.headers
    if stage != "new-workspace":
        assert inserted is False


@pytest.mark.parametrize("reason", ("expired", "revoked", "suspended", "missing-membership"))
def test_denied_creation_keeps_all_rows_and_does_not_reissue_a_cookie(policy_state, reason):
    state = policy_state
    login(state, "password", False)
    payload, row = current_row(state)
    if reason == "expired":
        payload["exp"] = int(time.time()) - 1
        state["client"].cookies.clear()
        state["client"].cookies.set("tc_session", session.sign_token(payload))
    elif reason == "revoked":
        state["db"].delete(row)
    elif reason == "suspended":
        state["actor"].suspended = True
    else:
        state["db"].delete(state["actor"])
    state["db"].commit()
    before = snapshot(state)
    response = reissue(state, "create")
    assert response.status_code == (401 if reason in ("expired", "revoked") else 403)
    assert "set-cookie" not in response.headers
    assert snapshot(state) == before
