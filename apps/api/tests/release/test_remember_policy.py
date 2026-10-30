"""Current absolute lifetime and issuance caps through real stored HTTP auth."""

import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie

import pyotp
import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError

from app.api.routes import auth
from app.core import auth_deps, session
from app.core.mfa import encrypt_totp_secret, generate_totp_secret
from app.core.password import hash_password
from app.models import ApiKey, User, UserMfa, UserSession, Workspace, WorkspaceMember
from tests.release import test_principal_contract

authority = test_principal_contract.authority
pytestmark = pytest.mark.integration
PASSWORD = secrets.token_urlsafe(24)


def snapshot(state, *, external_only=False):
    """Full rows, not just counts; preserve all pre-existing unrelated data."""
    result = {}
    for model in test_principal_contract.MODELS:
        rows = []
        for row in state["db"].execute(select(model.__table__).order_by(model.id)).mappings():
            owned = (
                (model is User and row["id"] in state["users"])
                or (model is Workspace and row["id"] in state["ws"])
                or row.get("user_id") in state["users"]
                or row.get("workspace_id") in state["ws"]
            )
            if not external_only or not owned:
                rows.append(tuple(row.values()))
        result[model.__tablename__] = rows
    return result


@pytest.fixture
def policy_state(authority):
    # The reviewed authority fixture owns/deletes exact users/workspaces and
    # asserts final counts. Add full-row invariants for every external row.
    before = snapshot(authority, external_only=True)
    yield authority
    authority["db"].rollback()
    assert snapshot(authority, external_only=True) == before


def prepare_login(state, *, policy=86400, mfa=False):
    db = state["db"]
    user = db.get(User, state["users"][0])
    user.password_hash = hash_password(PASSWORD)
    db.get(Workspace, state["ws"][0]).session_max_age_seconds = policy
    secret = generate_totp_secret() if mfa else None
    if secret:
        db.add(
            UserMfa(
                user_id=user.id, enabled=True, totp_secret_encrypted=encrypt_totp_secret(secret)
            )
        )
    db.commit()
    state["client"].cookies.clear()
    return user.email, secret


def password_login(state, email, remember):
    return state["client"].post(
        "/api/auth/login",
        json={"email": email, "password": PASSWORD, "remember_me": remember},
    )


def issued_cookie(response):
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    return cookie["tc_session"]


def current_row(state):
    cookie = SimpleCookie()
    cookie.load(f"tc_session={state['client'].cookies.get('tc_session')}")
    payload = session.verify_token(cookie["tc_session"].value)
    row = state["db"].query(UserSession).filter_by(session_id=payload["session_id"]).one()
    return payload, row


@pytest.mark.parametrize("quoted", (False, True), ids=("unquoted", "quoted"))
def test_current_row_reads_real_login_cookie_encodings(policy_state, quoted):
    state = policy_state
    user = state["db"].get(User, state["users"][0])
    original_email = user.email
    # Payload lengths change base64 padding and therefore Set-Cookie quoting.
    # Exercise both actual server encodings without replacing cookies or signing.
    for padding in range(3):
        user.email = "x" * padding + original_email
        state["db"].commit()
        email, _ = prepare_login(state)
        response = password_login(state, email, False)
        assert response.status_code == 200
        raw = state["client"].cookies.get("tc_session")
        if (raw.startswith('"') and raw.endswith('"')) == quoted:
            break
    else:
        pytest.fail("Real login did not produce the requested cookie encoding")
    expected = session.verify_token(issued_cookie(response).value)
    assert expected is not None
    assert state["client"].get("/api/auth/me").status_code == 200
    payload, row = current_row(state)
    assert payload == expected
    assert row.session_id == expected["session_id"]
    assert row.user_id == state["users"][0]


def assert_expired_authority(state):
    before = snapshot(state)
    for path in ("/authority/required", "/authority/can_admin", "/api/auth/me"):
        assert state["client"].get(path).status_code == 401
    assert state["client"].get("/api/trust-articles").status_code == 401
    assert state["client"].get(f"/api/trust-articles/{state['private']}").status_code == 404
    assert state["client"].get(f"/api/trust-articles/{state['public']}").status_code == 200
    assert snapshot(state) == before


@pytest.mark.parametrize("policy,want", ((None, 604800), (86400, 86400), (7776000, 7776000)))
@pytest.mark.parametrize("mfa", (False, True), ids=("password", "mfa"))
@pytest.mark.parametrize("remember", (False, True), ids=("browser-session", "remembered"))
def test_real_login_never_issues_beyond_existing_workspace_or_default_cap(
    policy_state, policy, want, mfa, remember
):
    state = policy_state
    email, secret = prepare_login(state, policy=policy, mfa=mfa)
    started = int(time.time())
    response = password_login(state, email, remember)
    assert response.status_code == 200, response.text
    if mfa:
        assert response.json()["requires_mfa"] is True
        assert "set-cookie" not in response.headers
        response = state["client"].post(
            "/api/auth/mfa/verify-login",
            json={
                "mfa_token": response.json()["mfa_token"],
                "code": pyotp.TOTP(secret).now(),
                "remember_me": remember,
            },
        )
        assert response.status_code == 200, response.text
    cookie = issued_cookie(response)
    payload = session.verify_token(cookie.value)
    assert started + want <= payload["exp"] <= int(time.time()) + want
    assert cookie["max-age"] == (str(want) if remember else "")
    _, row = current_row(state)
    assert row.user_id == state["users"][0]
    assert state["client"].get("/api/auth/me").status_code == 200


@pytest.mark.parametrize("remember", (False, True))
def test_tightening_current_policy_immediately_denies_an_older_real_login(policy_state, remember):
    state = policy_state
    email, _ = prepare_login(state, policy=604800)
    assert password_login(state, email, remember).status_code == 200
    payload, row = current_row(state)
    row.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
    state["db"].commit()
    assert state["client"].get("/authority/can_admin").status_code == 200
    updated = state["client"].patch(
        "/api/workspaces/current", json={"session_max_age_seconds": 86400}
    )
    assert updated.status_code == 200
    assert updated.json()["session_max_age_seconds"] == 86400
    assert payload["exp"] > time.time()
    assert_expired_authority(state)


@pytest.mark.parametrize("remaining,want", ((-1, 401), (0, 401), (1, 200)))
def test_persisted_creation_deadline_has_an_exclusive_boundary(
    policy_state, monkeypatch, remaining, want
):
    state = policy_state
    now = datetime.now(timezone.utc).replace(microsecond=0)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(auth_deps, "datetime", Clock, raising=False)
    _, row = current_row(state)
    row.created_at = (now - timedelta(seconds=60 - remaining)).replace(tzinfo=None)
    state["db"].get(Workspace, state["ws"][0]).session_max_age_seconds = 60
    state["db"].commit()
    before = snapshot(state)
    for path in ("/authority/can_admin", "/api/auth/me"):
        assert state["client"].get(path).status_code == want
    assert snapshot(state) == before


@pytest.mark.parametrize("kind", ("missing", "future", "older-than-default"))
def test_unusable_or_expired_stored_creation_time_denies_without_writes(policy_state, kind):
    state = policy_state
    _, row = current_row(state)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row.created_at = {
        "missing": None,
        "future": now + timedelta(days=1),
        "older-than-default": now - timedelta(days=8),
    }[kind]
    state["db"].commit()
    assert_expired_authority(state)


def test_longer_current_policy_does_not_override_signed_expiry(policy_state):
    state = policy_state
    payload, _ = current_row(state)
    state["db"].get(Workspace, state["ws"][0]).session_max_age_seconds = 7776000
    state["db"].commit()
    payload["exp"] = int(time.time()) - 1
    state["client"].cookies.clear()
    state["client"].cookies.set("tc_session", session.sign_token(payload))
    assert_expired_authority(state)


@pytest.mark.parametrize("kind", ("expired-target", "target-bound", "signed-bound"))
def test_switch_checks_target_deadline_before_acknowledging_and_cannot_renew_age(
    policy_state, kind
):
    state = policy_state
    payload, row = current_row(state)
    target = state["db"].get(Workspace, state["ws"][1])
    state["db"].add(
        WorkspaceMember(user_id=state["users"][0], workspace_id=target.id, role="reviewer")
    )
    target.session_max_age_seconds = 86400 if kind == "expired-target" else 60
    age = timedelta(days=2) if kind == "expired-target" else timedelta(seconds=30)
    row.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - age
    if kind == "signed-bound":
        target.session_max_age_seconds = 604800
    state["db"].commit()
    target_deadline = (
        row.created_at.replace(tzinfo=timezone.utc).timestamp() + target.session_max_age_seconds
    )
    before = snapshot(state)
    response = state["client"].post("/api/auth/switch-workspace", json={"workspace_id": target.id})
    if kind == "expired-target":
        assert response.status_code == 401
        assert "set-cookie" not in response.headers
        assert snapshot(state) == before
        assert state["client"].get("/authority/can_admin").status_code == 200
    else:
        assert response.status_code == 200, response.text
        switched = session.verify_token(issued_cookie(response).value)
        assert switched["exp"] <= min(payload["exp"], int(target_deadline))
        assert switched["session_id"] == payload["session_id"]
        info = state["client"].get("/api/auth/me")
        assert info.status_code == 200
        assert info.json()["workspace_id"] == target.id
        assert info.json()["role"] == "reviewer"


@pytest.mark.parametrize("bound", ("signed", "target"))
@pytest.mark.parametrize("expires_during_signing", (False, True))
def test_switch_preserves_absolute_deadline_when_real_signing_clock_advances(
    policy_state, monkeypatch, bound, expires_during_signing
):
    state = policy_state
    payload, row = current_row(state)
    target = state["db"].get(Workspace, state["ws"][1])
    target.session_max_age_seconds = 60 if bound == "target" else 604800
    row.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=30)
    state["db"].add(
        WorkspaceMember(user_id=state["users"][0], workspace_id=target.id, role="reviewer")
    )
    state["db"].commit()
    deadline = min(
        payload["exp"],
        int(row.created_at.replace(tzinfo=timezone.utc).timestamp())
        + target.session_max_age_seconds,
    )
    clock = {"now": int(time.time()) + 0.1}
    real_sign = auth.sign_session

    def advance_then_sign(*args, **kwargs):
        clock["now"] = deadline + 0.1 if expires_during_signing else clock["now"] + 1.1
        return real_sign(*args, **kwargs)

    # Only the clock advances; the production signer and HTTP auth remain real.
    monkeypatch.setattr(session.time, "time", lambda: clock["now"])
    monkeypatch.setattr(auth, "sign_session", advance_then_sign)
    before = snapshot(state)
    response = state["client"].post("/api/auth/switch-workspace", json={"workspace_id": target.id})
    if expires_during_signing:
        assert response.status_code == 401
        assert "set-cookie" not in response.headers
        assert snapshot(state) == before
    else:
        assert response.status_code == 200
        cookie = issued_cookie(response)
        switched = session.verify_token(cookie.value)
        assert switched["exp"] == deadline
        assert int(cookie["max-age"]) <= deadline - int(clock["now"])
        # The fixture's original domainless cookie must not survive alongside
        # the replacement server cookie and reappear when the latter expires.
        state["client"].cookies.clear()
        state["client"].cookies.set("tc_session", cookie.value)
        assert state["client"].get("/api/auth/me").status_code == 200
        clock["now"] = deadline
        assert state["client"].get("/api/auth/me").status_code == 401


def test_pending_mfa_policy_failure_preserves_enrollment_and_allows_retry(policy_state):
    state = policy_state
    email, _ = prepare_login(state)
    secret = generate_totp_secret()
    state["db"].add(
        UserMfa(
            user_id=state["users"][0],
            enabled=False,
            totp_secret_encrypted=encrypt_totp_secret(secret, reenrol_pending=True),
        )
    )
    state["db"].commit()
    login = password_login(state, email, False)
    assert login.status_code == 200
    assert login.json()["requires_mfa_enrol"] is True
    payload = session.verify_token(issued_cookie(login).value)
    assert payload is not None
    before = snapshot(state)
    engine = state["db"].get_bind()
    policy_reads = 0

    def fail_second_policy_read(conn, cursor, statement, parameters, context, executemany):
        nonlocal policy_reads
        if "FROM workspaces" in statement:
            policy_reads += 1
            if policy_reads == 2:
                raise OperationalError(
                    "synthetic policy lookup failure", {}, RuntimeError("offline")
                )

    event.listen(engine, "before_cursor_execute", fail_second_policy_read)
    try:
        response = state["client"].post(
            "/api/auth/mfa/confirm", json={"code": pyotp.TOTP(secret).now()}
        )
        assert response.status_code == 503
        assert "set-cookie" not in response.headers
    finally:
        event.remove(engine, "before_cursor_execute", fail_second_policy_read)
    assert snapshot(state) == before
    retry = state["client"].post("/api/auth/mfa/confirm", json={"code": pyotp.TOTP(secret).now()})
    assert retry.status_code == 200
    assert len(set(retry.json()["recovery_codes"])) == 10
    assert state["db"].query(UserSession).filter_by(session_id=payload["session_id"]).count() == 0
    assert session.verify_token(issued_cookie(retry).value)["session_id"] != payload["session_id"]
    info = state["client"].get("/api/auth/me")
    assert info.status_code == 200
    assert info.json()["role"] == "admin"


@pytest.mark.parametrize(
    "entry", ("required", "me", "optional", "password", "mfa", "switch", "switch-target")
)
def test_policy_lookup_error_never_grants_authority_or_issues_a_cookie(policy_state, entry):
    state = policy_state
    code = token = email = None
    if entry in ("password", "mfa"):
        email, secret = prepare_login(state, mfa=entry == "mfa")
        if secret:
            challenge = password_login(state, email, True)
            assert challenge.status_code == 200
            token = challenge.json()["mfa_token"]
            code = pyotp.TOTP(secret).now()
    if entry.startswith("switch"):
        state["db"].add(
            WorkspaceMember(user_id=state["users"][0], workspace_id=state["ws"][1], role="reviewer")
        )
        state["db"].commit()
    before = snapshot(state)
    engine = state["db"].get_bind()

    def fail_policy_lookup(conn, cursor, statement, parameters, context, executemany):
        if "FROM workspaces" in statement:
            values = parameters.values() if isinstance(parameters, dict) else parameters
            if entry == "switch-target" and state["ws"][1] not in values:
                return
            raise OperationalError("synthetic policy lookup failure", {}, RuntimeError("offline"))

    event.listen(engine, "before_cursor_execute", fail_policy_lookup)
    try:
        if entry == "password":
            response = password_login(state, email, True)
        elif entry == "mfa":
            response = state["client"].post(
                "/api/auth/mfa/verify-login",
                json={"mfa_token": token, "code": code, "remember_me": True},
            )
        elif entry.startswith("switch"):
            response = state["client"].post(
                "/api/auth/switch-workspace", json={"workspace_id": state["ws"][1]}
            )
        else:
            response = state["client"].get(
                {
                    "required": "/authority/can_admin",
                    "me": "/api/auth/me",
                    "optional": f"/api/trust-articles/{state['private']}",
                }[entry]
            )
        assert response.status_code == (404 if entry == "optional" else 503)
        assert "set-cookie" not in response.headers
    finally:
        event.remove(engine, "before_cursor_execute", fail_policy_lookup)
    assert snapshot(state) == before


def test_longer_tenant_cap_accepts_an_older_session_without_read_side_effects(policy_state):
    state = policy_state
    _, row = current_row(state)
    row.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=20)
    state["db"].get(Workspace, state["ws"][0]).session_max_age_seconds = 7776000
    state["db"].commit()
    before = snapshot(state)
    assert state["client"].get("/authority/can_admin").status_code == 200
    assert state["client"].get("/api/auth/me").status_code == 200
    assert snapshot(state) == before


def test_api_key_authority_does_not_inherit_human_session_age(policy_state):
    state = policy_state
    _, row = current_row(state)
    row.created_at = None
    raw = secrets.token_urlsafe(24)
    state["db"].add(
        ApiKey(
            workspace_id=state["ws"][0],
            key_hash=hashlib.sha256(raw.encode()).hexdigest(),
            role="editor",
        )
    )
    state["db"].commit()
    before = snapshot(state)
    headers = {"Authorization": f"Bearer {raw}"}
    assert state["client"].get("/authority/can_edit", headers=headers).status_code == 200
    assert state["client"].get("/authority/can_admin", headers=headers).status_code == 403
    assert state["client"].get("/api/auth/me", headers=headers).status_code == 401
    assert snapshot(state) == before


@pytest.mark.parametrize("expired", (False, True))
def test_account_only_onboarding_keeps_default_cap_and_route_restrictions(policy_state, expired):
    state = policy_state
    state["cookie"](pending=True)
    if expired:
        _, row = current_row(state)
        row.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=8)
        state["db"].commit()
    before = snapshot(state)
    response = state["client"].get("/api/auth/me")
    assert response.status_code == (401 if expired else 200)
    if not expired:
        assert response.json()["needs_onboarding"] is True
        assert not any(response.json()["permissions"].values())
        assert state["client"].get("/authority/can_admin").status_code == 403
    assert snapshot(state) == before


@pytest.mark.parametrize("expired", (False, True))
def test_mfa_enrolment_remains_restricted_and_obeys_current_workspace_cap(policy_state, expired):
    state = policy_state
    state["db"].add(
        UserMfa(
            user_id=state["users"][0],
            enabled=False,
            totp_secret_encrypted=encrypt_totp_secret(generate_totp_secret(), reenrol_pending=True),
        )
    )
    state["db"].get(Workspace, state["ws"][0]).session_max_age_seconds = 60
    state["cookie"]("mfa_enrol", enrol=True)
    if expired:
        _, row = current_row(state)
        row.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=61)
    state["db"].commit()
    before = snapshot(state)
    response = state["client"].get("/api/auth/me")
    assert response.status_code == (401 if expired else 200)
    if not expired:
        assert not any(response.json()["permissions"].values())
        assert state["client"].get("/api/auth/mfa/status").status_code == 200
        assert state["client"].get("/authority/can_admin").status_code in (401, 403)
    assert snapshot(state) == before
