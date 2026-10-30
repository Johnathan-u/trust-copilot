"""Self logout-all through independent real-auth clients and stored session rows."""

import hashlib
import json
import secrets
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.routes import auth
from app.core import session
from app.core.config import SIGNUP_POLICY_SELF_SIGNUP, get_settings
from app.core.mfa import encrypt_totp_secret, generate_totp_secret
from app.core.password import hash_password
from app.models import ApiKey, AuditEvent, User, UserMfa, UserSession, WorkspaceMember
from tests.release import test_remember_policy
from tests.release.test_remember_policy import PASSWORD, issued_cookie, snapshot

pytestmark = pytest.mark.integration
authority = test_remember_policy.authority
policy_state = test_remember_policy.policy_state
PATH = "/api/auth/sessions/revoke-all"


@pytest.fixture
def devices(policy_state):
    state = policy_state
    db = state["db"]
    for user_id in state["users"]:
        db.get(User, user_id).password_hash = hash_password(PASSWORD)
    db.add_all(
        [
            WorkspaceMember(
                user_id=state["users"][0], workspace_id=state["ws"][1], role="reviewer"
            ),
            WorkspaceMember(user_id=state["users"][1], workspace_id=state["ws"][1], role="editor"),
        ]
    )
    db.commit()
    clients = []
    credentials = []
    try:
        for user_id, remember in (
            (state["users"][0], False),
            (state["users"][0], True),
            (state["users"][1], False),
        ):
            client = TestClient(state["client"].app)
            clients.append(client)
            response = client.post(
                "/api/auth/login",
                json={
                    "email": db.get(User, user_id).email,
                    "password": PASSWORD,
                    "remember_me": remember,
                },
            )
            assert response.status_code == 200, response.text
            cookie = issued_cookie(response)
            assert bool(cookie["max-age"]) is remember
            credentials.append(session.verify_token(cookie.value))
            assert client.get("/api/auth/me").status_code == 200
        assert credentials[0]["session_id"] != credentials[1]["session_id"]
        switched = clients[1].post(
            "/api/auth/switch-workspace", json={"workspace_id": state["ws"][1]}
        )
        assert switched.status_code == 200
        assert (
            session.verify_token(issued_cookie(switched).value)["session_id"]
            == credentials[1]["session_id"]
        )
        yield state, clients, credentials
    finally:
        for client in clients:
            client.close()


def stored_sessions(state, user_id):
    return list(
        state["db"]
        .execute(
            select(UserSession.__table__)
            .where(UserSession.user_id == user_id)
            .order_by(UserSession.id)
        )
        .mappings()
    )


@pytest.mark.parametrize("caller", (0, 1), ids=("session-only", "remembered"))
@pytest.mark.parametrize("foreign_target_body", (False, True))
@pytest.mark.parametrize("secure", (False, True), ids=("development-cookie", "production-cookie"))
def test_revoke_all_removes_every_own_session_and_preserves_foreign_access(
    devices, monkeypatch, caller, foreign_target_body, secure
):
    state, clients, credentials = devices
    own_id, foreign_id = state["users"]
    before = snapshot(state)
    foreign = stored_sessions(state, foreign_id)
    own_count = len(stored_sessions(state, own_id))
    assert own_count == 3  # two independently authenticated clients plus the fixture's session
    # Control only the cookie environment flag; auth, signing and storage stay real.
    monkeypatch.setattr(auth, "is_production_env", lambda: secure)
    response = clients[caller].post(
        PATH,
        json={"user_id": foreign_id, "session_id": credentials[2]["session_id"]}
        if foreign_target_body
        else None,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "revoked": own_count}
    cleared = issued_cookie(response)
    assert cleared.value == ""
    assert cleared["max-age"] == "0"
    assert cleared["expires"]
    assert cleared["httponly"] is True
    assert cleared["samesite"] == "lax"
    assert cleared["path"] == "/"
    assert bool(cleared["secure"]) is secure
    assert stored_sessions(state, own_id) == []
    assert stored_sessions(state, foreign_id) == foreign
    assert clients[0].get("/api/auth/me").status_code == 401
    assert clients[1].get("/api/auth/me").status_code == 401
    assert clients[2].get("/api/auth/me").status_code == 200
    after = snapshot(state)
    for table in before.keys() - {"user_sessions", "audit_events"}:
        assert after[table] == before[table]
    audit = (
        state["db"]
        .query(AuditEvent)
        .filter_by(action="auth.sessions_revoked_all", user_id=own_id)
        .all()
    )
    assert len(audit) == 1
    assert json.loads(audit[0].details) == {"count": own_count}
    assert audit[0].workspace_id == (state["ws"][0] if caller == 0 else state["ws"][1])
    # The second caller cannot replay revoked authority to mutate anything else.
    before = snapshot(state)
    assert clients[1 - caller].post(PATH).status_code == 401
    assert snapshot(state) == before


@pytest.mark.parametrize("failure", ("delete", "audit", "commit"))
def test_failed_revocation_rolls_back_rows_and_keeps_cookie_for_a_real_retry(devices, failure):
    state, clients, _ = devices
    engine = state["db"].get_bind()
    before = snapshot(state)
    cookie_before = clients[0].cookies.get("tc_session")

    def fail_sql(conn, cursor, statement, parameters, context, executemany):
        if (failure == "delete" and statement.startswith("DELETE FROM user_sessions")) or (
            failure == "audit" and statement.startswith("INSERT INTO audit_events")
        ):
            raise OperationalError(
                "synthetic database failure", {}, RuntimeError("private diagnostic")
            )

    def fail_commit(db):
        if failure == "commit" and db.get_bind() is engine:
            raise OperationalError(
                "synthetic commit failure", {}, RuntimeError("private diagnostic")
            )

    event.listen(engine, "before_cursor_execute", fail_sql)
    event.listen(Session, "before_commit", fail_commit)
    try:
        response = clients[0].post(PATH)
    finally:
        event.remove(engine, "before_cursor_execute", fail_sql)
        event.remove(Session, "before_commit", fail_commit)
    assert response.status_code == 503
    assert "set-cookie" not in response.headers
    assert "private diagnostic" not in response.text
    assert clients[0].cookies.get("tc_session") == cookie_before
    assert snapshot(state) == before
    for client in clients:
        assert client.get("/api/auth/me").status_code == 200
    retry = clients[0].post(PATH)
    assert retry.status_code == 200
    assert retry.json()["revoked"] == 3
    assert clients[1].get("/api/auth/me").status_code == 401
    assert clients[2].get("/api/auth/me").status_code == 200


@pytest.mark.parametrize(
    "kind,status",
    (
        ("anonymous", 401),
        ("bad-signature", 401),
        ("expired", 401),
        ("revoked", 401),
        ("foreign-sid", 401),
        ("missing-sid", 401),
        ("missing-user", 403),
        ("boolean-user", 401),
        ("removed", 403),
        ("suspended", 403),
        ("pending", 403),
        ("mfa-enrollment", 401),
        ("api-key", 401),
        ("api-key-with-cookie", 401),
    ),
)
def test_invalid_or_restricted_authority_cannot_revoke_sessions(devices, monkeypatch, kind, status):
    state, clients, credentials = devices
    client, db = clients[0], state["db"]
    payload = dict(credentials[0])
    headers = {}
    if kind == "anonymous":
        client.cookies.clear()
    elif kind == "bad-signature":
        client.cookies.clear()
        client.cookies.set("tc_session", "invalid.signature")
    elif kind in {"expired", "foreign-sid", "missing-sid", "missing-user", "boolean-user"}:
        if kind == "expired":
            payload["exp"] = int(time.time()) - 1
        elif kind == "foreign-sid":
            payload["session_id"] = credentials[2]["session_id"]
        elif kind == "missing-sid":
            payload.pop("session_id")
        else:
            payload["user_id"] = None if kind == "missing-user" else True
        client.cookies.clear()
        client.cookies.set("tc_session", session.sign_token(payload))
    elif kind == "revoked":
        db.query(UserSession).filter_by(session_id=payload["session_id"]).delete()
    elif kind in {"removed", "suspended"}:
        if kind == "removed":
            db.delete(state["actor"])
        else:
            state["actor"].suspended = True
    elif kind == "pending":
        db.query(WorkspaceMember).filter_by(user_id=state["users"][0]).delete()
        db.commit()
        monkeypatch.setattr(get_settings(), "signup_policy", SIGNUP_POLICY_SELF_SIGNUP)
        response = client.post(
            "/api/auth/login",
            json={
                "email": db.get(User, state["users"][0]).email,
                "password": PASSWORD,
            },
        )
        assert response.status_code == 200
        assert response.json()["needs_onboarding"] is True
    elif kind == "mfa-enrollment":
        db.add(
            UserMfa(
                user_id=state["users"][0],
                enabled=False,
                totp_secret_encrypted=encrypt_totp_secret(
                    generate_totp_secret(), reenrol_pending=True
                ),
            )
        )
        db.commit()
        response = client.post(
            "/api/auth/login",
            json={
                "email": db.get(User, state["users"][0]).email,
                "password": PASSWORD,
            },
        )
        assert response.status_code == 200
        assert response.json()["requires_mfa_enrol"] is True
    else:
        raw = secrets.token_urlsafe(24)
        db.add(
            ApiKey(
                workspace_id=state["ws"][0],
                key_hash=hashlib.sha256(raw.encode()).hexdigest(),
                role="admin",
            )
        )
        if kind == "api-key":
            client.cookies.clear()
        headers = {"Authorization": f"Bearer {raw}"}
    db.commit()
    before = snapshot(state)
    cookie_before = client.cookies.get("tc_session")
    response = client.post(PATH, headers=headers)
    assert response.status_code == status, response.text
    assert "set-cookie" not in response.headers
    assert client.cookies.get("tc_session") == cookie_before
    assert snapshot(state) == before
    assert clients[2].get("/api/auth/me").status_code == 200


@pytest.mark.parametrize("action", ("logout", "sessions/revoke-others"))
def test_existing_current_and_other_session_actions_keep_their_distinct_meaning(devices, action):
    state, clients, _ = devices
    response = clients[0].post(f"/api/auth/{action}")
    assert response.status_code == 200
    assert clients[0].get("/api/auth/me").status_code == (401 if action == "logout" else 200)
    assert clients[1].get("/api/auth/me").status_code == (200 if action == "logout" else 401)
    assert clients[2].get("/api/auth/me").status_code == 200
