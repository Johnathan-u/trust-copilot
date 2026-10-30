"""TC-04-007a: proof-bound verification and account-independent reset limits."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from queue import Queue
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import auth
from app.core import rate_limit
from app.core.config import get_settings
from app.core.database import Base, get_db
from app.models import AuditEvent, EmailVerificationToken, PasswordResetToken, User, UserSession
from app.services import email_service
from tests import _safety

MODELS = (User, UserSession, EmailVerificationToken, PasswordResetToken, AuditEvent)
NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
RESET_MESSAGE = {"message": "If that email is registered, you will receive a reset link."}


def snapshot(db):
    db.expire_all()
    return {
        model.__tablename__: [
            dict(row) for row in db.execute(select(model.__table__).order_by(model.id)).mappings()
        ]
        for model in MODELS
    }


class Outbox:
    """Local transport boundary; the real mail builder and background thread run."""

    def __init__(self):
        self.messages = Queue()

    def send(self, message):
        self.messages.put(message)
        return True


@pytest.fixture(params=("sqlite", "postgres"))
def accounts(request, monkeypatch):
    if request.param == "postgres":
        request.getfixturevalue("migrated_db")
        db = request.getfixturevalue("db_session")
        engine = db.get_bind()
        assert engine.dialect.name == "postgresql"
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        Base.metadata.create_all(engine, tables=[model.__table__ for model in MODELS])
        db = Session(engine)
    original = snapshot(db)
    outbound = _safety.blocked_attempts()
    owned = {model: set() for model in MODELS}
    client = None
    outbox = Outbox()
    monkeypatch.setattr(email_service, "_default_provider", outbox)
    monkeypatch.delenv("TRUST_COPILOT_DEV_RETURN_RESET_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("TRUSTED_PROXY_IPS", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()
    clock = [1000.0]
    monkeypatch.setattr(rate_limit, "_now", lambda: clock[0])

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(auth, "datetime", FixedDatetime)

    def remember(current, _context):
        for row in current.new:
            if type(row) in owned:
                owned[type(row)].add(row.id)

    event.listen(db, "after_flush", remember)

    def add(model, **values):
        row = model(**values)
        db.add(row)
        db.flush()
        return row

    try:
        suffix = secrets.token_hex(8)
        users, codes, tokens = {}, {}, {}
        for state in ("unverified", "verified", "unrelated"):
            users[state] = add(
                User,
                email=f"enumeration-{state}-{suffix}@example.com",
                password_hash="synthetic-unused",
                email_verified=state == "verified",
            )
            code = f"{secrets.randbelow(10**6):06d}"
            while code in codes.values():
                code = f"{secrets.randbelow(10**6):06d}"
            codes[state] = code
            tokens[state] = add(
                EmailVerificationToken,
                user_id=users[state].id,
                token_hash=hashlib.sha256(code.encode()).hexdigest(),
                expires_at=(NOW + timedelta(minutes=15)).replace(tzinfo=None),
            ).id
            add(UserSession, user_id=users[state].id, session_id=secrets.token_hex(24))
            for used in (False, True):
                add(
                    PasswordResetToken,
                    user_id=users[state].id,
                    token_hash=hashlib.sha256(secrets.token_bytes(24)).hexdigest(),
                    expires_at=(NOW + timedelta(hours=1)).replace(tzinfo=None),
                    used_at=NOW.replace(tzinfo=None) if used else None,
                )
        db.commit()
        app = FastAPI()
        app.include_router(auth.router, prefix="/api")

        def database():
            with Session(engine) as current:
                event.listen(current, "after_flush", remember)
                yield current

        app.dependency_overrides[get_db] = database
        client = TestClient(app)
        yield {
            "db": db,
            "users": users,
            "codes": codes,
            "tokens": tokens,
            "missing": f"enumeration-missing-{suffix}@example.com",
            "client": client,
            "clock": clock,
            "outbox": outbox.messages,
        }
    finally:
        if client:
            client.close()
        db.rollback()
        for model in reversed(MODELS):
            if owned[model]:
                db.query(model).filter(model.id.in_(owned[model])).delete(synchronize_session=False)
        db.commit()
        assert snapshot(db) == original, "Fixture cleanup changed pre-existing rows"
        assert _safety.blocked_attempts() == outbound
        event.remove(db, "after_flush", remember)
        if request.param == "sqlite":
            db.close()
            engine.dispose()
        get_settings.cache_clear()


def email_for(state, account):
    return state["missing"] if account == "missing" else state["users"][account].email


def post(state, path, body, *, read_only=False):
    before = snapshot(state["db"])
    writes = []

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    engine = state["db"].get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        response = state["client"].post(f"/api/auth/{path}", json=body)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert "set-cookie" not in response.headers
    if read_only:
        assert not writes, "Denied or missing-account requests must not write"
        assert snapshot(state["db"]) == before
    return response


@pytest.mark.parametrize("account", ("missing", "unverified", "verified"))
@pytest.mark.parametrize("normalized", (False, True))
def test_wrong_code_never_discloses_account_or_verification_state(accounts, account, normalized):
    email = email_for(accounts, account)
    if normalized:
        email = f"  {email.upper()}  "
    response = post(accounts, "verify-code", {"email": email, "code": "wrong-code"}, read_only=True)
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid code"}


@pytest.mark.parametrize("account", ("unverified", "verified"))
def test_another_users_valid_code_is_not_proof_for_this_email(accounts, account):
    response = post(
        accounts,
        "verify-code",
        {"email": email_for(accounts, account), "code": accounts["codes"]["unrelated"]},
        read_only=True,
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid code"}


@pytest.mark.parametrize("account", ("unverified", "verified"))
@pytest.mark.parametrize("normalized", (False, True))
def test_valid_user_bound_proof_is_consumed_and_cannot_be_replayed(accounts, account, normalized):
    before = snapshot(accounts["db"])
    user = accounts["users"][account]
    email, code = user.email, accounts["codes"][account]
    if normalized:
        email, code = f" {email.upper()} ", f" {code} "
    body = {"email": email, "code": code}
    response = post(accounts, "verify-code", body)
    assert response.status_code == 200
    assert response.json() == {
        "message": "Email already verified." if account == "verified" else "Email verified."
    }
    after = snapshot(accounts["db"])
    assert after["email_verification_tokens"] == [
        row
        for row in before["email_verification_tokens"]
        if row["id"] != accounts["tokens"][account]
    ]
    assert after["password_reset_tokens"] == before["password_reset_tokens"]
    assert after["user_sessions"] == before["user_sessions"]
    for old, new in zip(before["users"], after["users"], strict=True):
        if old["id"] == user.id:
            assert new["email_verified"] is True
            assert {k: v for k, v in new.items() if k not in {"email_verified", "updated_at"}} == {
                k: v for k, v in old.items() if k not in {"email_verified", "updated_at"}
            }
        else:
            assert new == old
    added_audits = after["audit_events"][len(before["audit_events"]) :]
    assert after["audit_events"][: len(before["audit_events"])] == before["audit_events"]
    assert len(added_audits) == (0 if account == "verified" else 1)
    if added_audits:
        assert added_audits[0]["action"] == "auth.email_verified"
        assert added_audits[0]["user_id"] == user.id
    replay = post(accounts, "verify-code", body, read_only=True)
    assert replay.status_code == 400
    assert replay.json() == {"detail": "Invalid code"}


@pytest.mark.parametrize("account", ("unverified", "verified"))
def test_expired_proof_keeps_expiry_denial_and_deletes_only_that_token(accounts, account):
    db = accounts["db"]
    token_id = accounts["tokens"][account]
    db.get(EmailVerificationToken, token_id).expires_at = (NOW - timedelta(seconds=1)).replace(
        tzinfo=None
    )
    db.commit()
    before = snapshot(db)
    response = post(
        accounts,
        "verify-code",
        {"email": email_for(accounts, account), "code": accounts["codes"][account]},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Code expired. Please register again."}
    before["email_verification_tokens"] = [
        row for row in before["email_verification_tokens"] if row["id"] != token_id
    ]
    assert snapshot(db) == before


@pytest.mark.parametrize("account", ("missing", "unverified", "verified"))
@pytest.mark.parametrize("production", (False, True))
def test_forgot_password_same_limit_and_window_regardless_of_account(
    accounts, account, production, monkeypatch
):
    monkeypatch.setenv("APP_ENV", "production" if production else "development")
    get_settings.cache_clear()
    state = accounts
    original = snapshot(state["db"])
    email = email_for(state, account)
    user_id = None if account == "missing" else state["users"][account].id
    for attempt in range(11):
        if attempt == 10:
            for elapsed in (0, 59.999):
                state["clock"][0] = 1000.0 + elapsed
                blocked = post(state, "forgot-password", {"email": email}, read_only=True)
                assert blocked.status_code == 429
                assert blocked.json() == {"detail": "Too many requests. Try again later."}
            state["clock"][0] = 1060.0
        response = post(
            state,
            "forgot-password",
            {"email": f" {email.upper()} "},
            read_only=account == "missing",
        )
        assert response.status_code == 200
        assert response.json() == RESET_MESSAGE
        after = snapshot(state["db"])
        if account == "missing":
            assert after == original
            assert state["outbox"].empty()
            continue
        delivered = state["outbox"].get(timeout=2)
        assert delivered.to == email
        reset_url = delivered.body_text.splitlines()[0].rsplit(" ", 1)[1]
        raw_token = parse_qs(urlsplit(reset_url).query)["token"][0]
        reset_rows = after["password_reset_tokens"]
        active = [row for row in reset_rows if row["user_id"] == user_id and row["used_at"] is None]
        assert len(active) == 1
        assert active[0]["token_hash"] == hashlib.sha256(raw_token.encode()).hexdigest()
        assert active[0]["expires_at"] == (NOW + timedelta(hours=1)).replace(tzinfo=None)

        def unchanged(row):
            return row["user_id"] != user_id or row["used_at"] is not None

        assert [row for row in reset_rows if unchanged(row)] == [
            row for row in original["password_reset_tokens"] if unchanged(row)
        ]
        for table in ("users", "user_sessions", "email_verification_tokens"):
            assert after[table] == original[table]
        new_audits = after["audit_events"][len(original["audit_events"]) :]
        assert len(new_audits) == attempt + 1
        assert all(
            row["action"] == "auth.reset_requested" and row["user_id"] == user_id
            for row in new_audits
        )
        assert state["outbox"].empty()


@pytest.mark.parametrize("field", ("email", "code"))
def test_missing_verification_fields_keep_existing_validation(accounts, field):
    body = {"email": email_for(accounts, "verified"), "code": accounts["codes"]["verified"]}
    body[field] = " "
    response = post(accounts, "verify-code", body, read_only=True)
    assert response.status_code == 400
    assert response.json() == {"detail": "Email and code are required"}
