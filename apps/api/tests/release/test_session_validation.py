"""Strict signed human-session boundaries with real HTTP and owned DB fixtures."""

import base64
import json
import os
import sqlite3
import subprocess
import sys
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.session import sign_token, verify_token
from app.models import UserSession
from tests.release import test_principal_contract

# Reuse the reviewed real-HTTP fixture and its exact owned-row cleanup.
authority = test_principal_contract.authority
counts = test_principal_contract.counts


def malformed_claims():
    future = int(time.time()) + 3600
    return [
        ("missing-exp", {"exp": "__remove__"}),
        ("null-exp", {"exp": None}),
        ("string-exp", {"exp": str(future)}),
        ("fractional-exp", {"exp": future + 0.5}),
        ("boolean-exp", {"exp": True}),
        ("array-exp", {"exp": [future]}),
        ("object-exp", {"exp": {"value": future}}),
        ("expired", {"exp": int(time.time()) - 1}),
        ("missing-sid", {"session_id": "__remove__"}),
        ("null-sid", {"session_id": None}),
        ("empty-sid", {"session_id": ""}),
        ("blank-sid", {"session_id": "  \t"}),
        ("numeric-sid", {"session_id": 1}),
        ("array-sid", {"session_id": []}),
        ("object-sid", {"session_id": {"value": "invalid"}}),
    ]


def put_cookie(state, payload):
    token = sign_token(payload)
    state["client"].cookies.clear()
    state["client"].cookies.set("tc_session", token)
    return token


def assert_no_human_authority(state):
    before = counts(state["db"])
    for path in ("/authority/required", "/authority/can_admin", "/api/auth/me"):
        assert state["client"].get(path).status_code == 401
    assert state["client"].get("/api/trust-articles").status_code == 401
    assert state["client"].get(f"/api/trust-articles/{state['private']}").status_code == 404
    assert state["client"].get(f"/api/trust-articles/{state['public']}").status_code == 200
    assert counts(state["db"]) == before


@pytest.mark.parametrize(
    "label,updates", malformed_claims(), ids=lambda value: value if isinstance(value, str) else None
)
def test_malformed_and_expired_credentials_fail_required_optional_and_me(authority, label, updates):
    state = authority
    payload = verify_token(state["cookie"]())
    for field, value in updates.items():
        if value == "__remove__":
            payload.pop(field)
        else:
            payload[field] = value
    token = put_cookie(state, payload)
    assert_no_human_authority(state)
    assert verify_token(token) is None


@pytest.mark.parametrize("kind", ("deleted", "other-user", "string-user", "boolean-user"))
def test_session_record_must_belong_to_the_exact_human_user(authority, kind):
    state = authority
    payload = verify_token(state["cookie"]())
    if kind == "deleted":
        state["db"].query(UserSession).filter_by(session_id=payload["session_id"]).delete()
        state["db"].commit()
    elif kind == "other-user":
        payload["session_id"] = (
            state["db"].query(UserSession).filter_by(user_id=state["users"][1]).one().session_id
        )
    elif kind == "string-user":
        payload["user_id"] = str(payload["user_id"])
    else:
        payload["user_id"] = True
    put_cookie(state, payload)
    assert_no_human_authority(state)


def test_valid_session_is_rejected_on_next_request_after_revocation(authority):
    state = authority
    token = state["cookie"]()
    payload = verify_token(token)
    assert state["client"].get("/authority/can_admin").status_code == 200
    assert state["client"].get("/api/auth/me").status_code == 200
    state["db"].query(UserSession).filter_by(session_id=payload["session_id"]).delete()
    state["db"].commit()
    assert_no_human_authority(state)


@pytest.mark.parametrize("kind", ("other-user", "missing-exp", "missing-sid", "expired"))
def test_invalid_logout_clears_cookie_without_deleting_any_session(authority, kind):
    state = authority
    payload = verify_token(state["cookie"]())
    if kind == "other-user":
        payload["session_id"] = (
            state["db"].query(UserSession).filter_by(user_id=state["users"][1]).one().session_id
        )
    elif kind == "expired":
        payload["exp"] = int(time.time()) - 1
    else:
        payload.pop("exp" if kind == "missing-exp" else "session_id")
    put_cookie(state, payload)
    before = counts(state["db"])
    response = state["client"].post("/api/auth/logout")
    assert response.status_code == 200
    assert 'tc_session=""' in response.headers["set-cookie"]
    assert counts(state["db"]) == before


def test_expiry_boundary_is_exclusive_and_booleans_are_not_integer_expiries(monkeypatch):
    from app.core import session

    monkeypatch.setattr(session.time, "time", lambda: 1)
    payload = {"user_id": 1, "session_id": "synthetic-session", "exp": 1}
    assert verify_token(sign_token(payload)) is None
    payload["exp"] = True
    assert verify_token(sign_token(payload)) is None
    payload["exp"] = 2
    assert verify_token(sign_token(payload)) == payload


_PROCESS_HTTP = r"""
import json, os, sys
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.api.routes import auth
from app.core.auth_deps import require_session
from app.core.database import get_db

engine = create_engine(os.environ["TC_SESSION_TEST_DB_URL"])
app = FastAPI()
app.include_router(auth.router, prefix="/api")
@app.get("/required")
def required(session=Depends(require_session)):
    return {"user_id": session["user_id"]}
def database():
    with Session(engine) as db:
        yield db
app.dependency_overrides[get_db] = database
request = json.load(sys.stdin)
with TestClient(app) as client:
    client.cookies.set("tc_session", request["token"])
    result = {"required": client.get("/required").status_code,
              "me": client.get("/api/auth/me").status_code}
    if request["logout"]:
        result["logout"] = client.post("/api/auth/logout").status_code
engine.dispose()
print(json.dumps(result))
"""


def test_session_and_logout_revocation_survive_fresh_processes(authority, tmp_path, monkeypatch):
    state = authority
    keyring = (
        "session-test:" + base64.urlsafe_b64encode(b"synthetic-session-test-key-32byte!").decode()
    )
    monkeypatch.setenv("SESSION_KEYRING", keyring)
    token = state["cookie"]()
    payload = verify_token(token)
    engine = state["db"].get_bind()
    local_path = None
    if engine.dialect.name == "sqlite":
        # Each interpreter uses this private on-disk copy. The original fixture
        # still checks its full owned-row cleanup independently.
        local_path = tmp_path / "sessions.sqlite"
        with sqlite3.connect(local_path) as destination:
            state["db"].connection().connection.driver_connection.backup(destination)
        database_url = f"sqlite:///{local_path}"
    else:
        database_url = engine.url.render_as_string(hide_password=False)
    child_env = {
        **os.environ,
        "TC_SESSION_TEST_DB_URL": database_url,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    try:
        results = []
        for logout in (False, True, False):
            child = subprocess.run(
                [sys.executable, "-c", _PROCESS_HTTP],
                input=json.dumps({"token": token, "logout": logout}),
                text=True,
                capture_output=True,
                env=child_env,
                timeout=30,
                check=True,
            )
            results.append(json.loads(child.stdout))
        assert results == [
            {"required": 200, "me": 200},
            {"required": 200, "me": 200, "logout": 200},
            {"required": 401, "me": 401},
        ]
        inspection = create_engine(database_url)
        try:
            with Session(inspection) as db:
                assert (
                    db.query(UserSession).filter_by(session_id=payload["session_id"]).count() == 0
                )
                assert db.query(UserSession).filter_by(user_id=state["users"][1]).count() == 1
        finally:
            inspection.dispose()
    finally:
        if local_path is not None:
            local_path.unlink(missing_ok=True)
            assert not local_path.exists()
