"""Outbound request boundary regressions on real PostgreSQL; synthetic data only."""

import hashlib
import secrets
from datetime import datetime

import pytest
from sqlalchemy import text

from app.models import ApiKey, AuditEvent, Questionnaire, VendorRequest

TABLES = ("vendor_requests", "questionnaires", "api_keys", "audit_events", "idempotency_keys")


def counts(db):
    return {name: db.execute(text(f"SELECT count(*) FROM {name}")).scalar() for name in TABLES}


@pytest.fixture
def domain(client, db_session):
    """Use real scoped API keys and restore every touched table's count."""
    before = counts(db_session)
    suffix = secrets.token_hex(8)
    keys = {}
    for role in ("admin", "editor", "reviewer"):
        raw = secrets.token_urlsafe(32)
        db_session.add(
            ApiKey(
                workspace_id=1,
                role=role,
                label=suffix,
                key_hash=hashlib.sha256(raw.encode()).hexdigest(),
            )
        )
        keys[role] = {"Authorization": f"Bearer {raw}"}
    qs = [
        Questionnaire(
            workspace_id=ws,
            filename=f"{suffix}-{kind}.xlsx",
            status="parsed",
            deleted_at=datetime.utcnow() if kind == "deleted" else None,
        )
        for ws, kind in ((1, "own"), (2, "foreign"), (1, "deleted"))
    ]
    db_session.add_all(qs)
    db_session.flush()
    own = VendorRequest(workspace_id=1, vendor_email=f"{suffix}@example.com", status="pending")
    foreign = VendorRequest(workspace_id=2, vendor_email=f"{suffix}@example.com", status="pending")
    db_session.add_all([own, foreign])
    db_session.commit()
    state = {
        "client": client,
        "db": db_session,
        "headers": keys,
        "suffix": suffix,
        "own": own.id,
        "foreign": foreign.id,
        "qs": [q.id for q in qs],
    }
    yield state
    db_session.rollback()
    request_ids = [
        row.id
        for row in db_session.query(VendorRequest)
        .filter(VendorRequest.vendor_email.contains(suffix))
        .all()
    ]
    db_session.query(AuditEvent).filter(
        AuditEvent.resource_type == "vendor_request",
        AuditEvent.resource_id.in_([str(i) for i in request_ids]),
    ).delete(synchronize_session=False)
    db_session.execute(
        text("DELETE FROM idempotency_keys WHERE idempotency_key LIKE :key"),
        {"key": "%" + suffix + "%"},
    )
    db_session.query(VendorRequest).filter(VendorRequest.vendor_email.contains(suffix)).delete(
        synchronize_session=False
    )
    db_session.query(Questionnaire).filter(Questionnaire.id.in_(state["qs"])).delete(
        synchronize_session=False
    )
    db_session.query(ApiKey).filter(ApiKey.label == suffix).delete(synchronize_session=False)
    db_session.commit()
    assert counts(db_session) == before


def actor(d):
    raw = d["headers"]["admin"]["Authorization"][7:]
    return {
        "user_id": None,
        "email": "api-key",
        "workspace_id": 1,
        "_api_key_hash": hashlib.sha256(raw.encode()).hexdigest(),
    }


def create(d, **overrides):
    body = {"vendor_email": f"{d['suffix']}@example.com", "message": "Please review."}
    body.update(overrides)
    return d["client"].post("/api/vendor-requests", json=body, headers=d["headers"]["admin"])


@pytest.mark.parametrize(
    "email", ["missing-at", "two@@example.com", "a@example.com\r\nBcc:x@y.com"]
)
def test_create_rejects_malformed_email_before_writing(domain, email):
    # Removing address validation would allow unsafe/unusable recipients to persist.
    before = counts(domain["db"])
    response = create(domain, vendor_email=domain["suffix"] + email)
    assert response.status_code == 422
    assert counts(domain["db"]) == before


def test_create_rejects_oversized_message_before_writing(domain):
    response = create(domain, message="x" * 10001)
    assert response.status_code == 422


def test_admin_cannot_mark_request_completed_without_submission(domain):
    response = domain["client"].patch(
        f"/api/vendor-requests/{domain['own']}",
        json={"status": "completed"},
        headers=domain["headers"]["admin"],
    )
    assert response.status_code == 409
    domain["db"].expire_all()
    assert domain["db"].get(VendorRequest, domain["own"]).status == "pending"


@pytest.mark.parametrize("role", ["editor", "reviewer"])
@pytest.mark.parametrize("method", ["post", "patch"])
def test_mutations_require_admin(domain, role, method):
    if method == "post":
        url, body = "/api/vendor-requests", {"vendor_email": f"{domain['suffix']}@example.com"}
    else:
        url, body = f"/api/vendor-requests/{domain['own']}", {"status": "in_progress"}
    before = counts(domain["db"])
    response = getattr(domain["client"], method)(url, json=body, headers=domain["headers"][role])
    assert response.status_code == 403
    assert counts(domain["db"]) == before
    domain["db"].expire_all()
    assert domain["db"].get(VendorRequest, domain["own"]).status == "pending"


def test_missing_foreign_and_deleted_questionnaires_are_indistinguishable(domain):
    responses = [create(domain, questionnaire_id=i) for i in (2147483647, *domain["qs"][1:])]
    assert [r.status_code for r in responses] == [404, 404, 404]
    assert responses[0].json() == responses[1].json() == responses[2].json()


def test_missing_and_foreign_requests_are_indistinguishable(domain):
    responses = [
        domain["client"].patch(
            f"/api/vendor-requests/{i}",
            json={"status": "in_progress"},
            headers=domain["headers"]["admin"],
        )
        for i in (2147483647, domain["foreign"])
    ]
    assert [r.status_code for r in responses] == [404, 404]
    assert responses[0].json() == responses[1].json()


def test_create_normalizes_and_list_is_read_only(domain):
    response = create(
        domain,
        vendor_email=f" {domain['suffix'].upper()}@EXAMPLE.COM ",
        questionnaire_id=domain["qs"][0],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["vendor_email"] == f"{domain['suffix']}@example.com"
    assert body["status"] == "pending"
    assert body["share_url"].endswith(body["link_token"])
    before = counts(domain["db"])
    result = domain["client"].get("/api/vendor-requests", headers=domain["headers"]["reviewer"])
    assert result.status_code == 200
    assert body["id"] in [row["id"] for row in result.json()]
    assert domain["foreign"] not in [row["id"] for row in result.json()]
    assert counts(domain["db"]) == before


@pytest.mark.parametrize(
    "email", ["missing-at", "two@@example.com", "a@example.com\r\nBcc:x@y.com"]
)
def test_create_schema_rejects_malformed_addresses(email):
    from pydantic import ValidationError
    from app.api.routes.vendor_requests import VendorRequestCreate

    with pytest.raises(ValidationError):
        VendorRequestCreate(vendor_email=email)


def test_create_schema_bounds_message():
    from pydantic import ValidationError
    from app.api.routes.vendor_requests import VendorRequestCreate

    with pytest.raises(ValidationError):
        VendorRequestCreate(vendor_email="test@example.com", message="x" * 10001)


@pytest.mark.parametrize(
    "email",
    [
        "a\x00@example.com",
        "a\x01@example.com",
        "İ" * 243 + "@example.com",
        ".a@example.com",
        "a..b@example.com",
    ],
)
def test_create_schema_rejects_controls_and_unsafe_normalization(email):
    from pydantic import ValidationError
    from app.api.routes.vendor_requests import VendorRequestCreate

    with pytest.raises(ValidationError):
        VendorRequestCreate(vendor_email=email)


def test_create_stores_only_token_hash_and_has_expiry(domain):
    from app.core.database import SessionLocal

    created = create(domain).json()
    assert created["expires_at"]
    assert created["delivery_status"] == "not_sent"
    with SessionLocal() as fresh:
        row = fresh.get(VendorRequest, created["id"])
        assert row.link_token is None
        assert row.link_token_hash == hashlib.sha256(created["link_token"].encode()).hexdigest()
    listed = domain["client"].get("/api/vendor-requests", headers=domain["headers"]["admin"]).json()
    assert next(r for r in listed if r["id"] == created["id"])["link_token"] is None
    assert created["link_token"] not in str(listed)


def test_create_retry_does_not_persist_token_or_duplicate_request(domain):
    h = {**domain["headers"]["admin"], "Idempotency-Key": domain["suffix"] + ":create"}
    body = {"vendor_email": domain["suffix"] + "@example.com"}
    first = domain["client"].post("/api/vendor-requests", json=body, headers=h)
    second = domain["client"].post("/api/vendor-requests", json=body, headers=h)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["link_token"] is None
    stored = (
        domain["db"]
        .execute(
            text("SELECT response_body FROM idempotency_keys WHERE idempotency_key LIKE :key"),
            {"key": "%" + domain["suffix"] + "%"},
        )
        .scalars()
        .all()
    )
    assert first.json()["link_token"] not in str(stored)
    changed = domain["client"].post(
        "/api/vendor-requests", json={**body, "message": "Changed"}, headers=h
    )
    assert changed.status_code == 409


def test_final_submission_is_durable_and_idempotent(domain):
    from app.core.database import SessionLocal

    created = create(domain).json()
    payload = {"token": created["link_token"], "response": "Our reviewed vendor response."}
    first = domain["client"].post("/api/vendor-response/submit", json=payload)
    assert first.status_code == 200
    assert first.json()["status"] == "completed"
    again = domain["client"].post("/api/vendor-response/submit", json=payload)
    assert again.json() == first.json()
    with SessionLocal() as fresh:
        stored = fresh.get(VendorRequest, created["id"])
        assert stored.submitted_at is not None
        assert stored.response_payload == payload["response"]
        assert stored.response_digest == hashlib.sha256(payload["response"].encode()).hexdigest()
    changed = domain["client"].post(
        "/api/vendor-response/submit", json={**payload, "response": "Different"}
    )
    assert changed.status_code == 409
    listed = domain["client"].get("/api/vendor-requests", headers=domain["headers"]["admin"]).json()
    assert next(row for row in listed if row["id"] == created["id"])["status"] == "completed"


@pytest.mark.parametrize("operation", ["send", "resend", "revoke"])
@pytest.mark.parametrize("role", ["editor", "reviewer"])
def test_lifecycle_mutations_require_admin(domain, operation, role):
    before = counts(domain["db"])
    response = domain["client"].post(
        f"/api/vendor-requests/{domain['own']}/{operation}",
        headers={**domain["headers"][role], "Idempotency-Key": domain["suffix"] + ":deny"},
    )
    assert response.status_code == 403
    assert counts(domain["db"]) == before


@pytest.mark.parametrize("operation", ["send", "resend", "revoke"])
def test_lifecycle_mutations_hide_foreign_ids(domain, operation):
    responses = [
        domain["client"].post(
            f"/api/vendor-requests/{i}/{operation}",
            headers={
                **domain["headers"]["admin"],
                "Idempotency-Key": domain["suffix"] + ":foreign",
            },
        )
        for i in (2147483647, domain["foreign"])
    ]
    assert [r.status_code for r in responses] == [404, 404]
    assert responses[0].json() == responses[1].json()


@pytest.mark.parametrize("kind", ["revoked", "expired", "unknown"])
def test_invalid_grants_have_equal_public_get_and_submit_responses(domain, kind):
    from datetime import timedelta, timezone

    created = create(domain).json()
    assert created.get("expires_at") is not None
    token = created["link_token"]
    if kind == "revoked":
        revoked = domain["client"].post(
            f"/api/vendor-requests/{created['id']}/revoke", headers=domain["headers"]["admin"]
        )
        assert revoked.status_code == 200
    elif kind == "expired":
        domain["db"].get(VendorRequest, created["id"]).expires_at = datetime.now(
            timezone.utc
        ) - timedelta(seconds=1)
        domain["db"].commit()
    else:
        token = secrets.token_urlsafe(32)
    before = counts(domain["db"])
    response = domain["client"].get("/api/vendor-response", params={"token": token})
    submitted = domain["client"].post(
        "/api/vendor-response/submit", json={"token": token, "response": "Response"}
    )
    assert response.status_code == submitted.status_code == 404
    assert response.json() == submitted.json() == {"detail": "This link is invalid or has expired."}
    assert counts(domain["db"]) == before


@pytest.mark.parametrize("response", [" ", "x" * 20001, "contains\x00nul"])
def test_final_submission_rejects_bad_payload(domain, response):
    created = create(domain).json()
    result = domain["client"].post(
        "/api/vendor-response/submit", json={"token": created["link_token"], "response": response}
    )
    assert result.status_code == 422


def test_legacy_completion_is_not_treated_as_a_submission(domain):
    row = domain["db"].get(VendorRequest, domain["own"])
    row.status = "completed"
    domain["db"].commit()
    rows = domain["client"].get("/api/vendor-requests", headers=domain["headers"]["admin"]).json()
    assert next(r for r in rows if r["id"] == row.id)["status"] != "completed"


def test_console_provider_is_never_reported_as_delivery(domain):
    from unittest.mock import patch
    from app.services.email_service import ConsoleEmailProvider

    created = create(domain).json()
    with patch(
        "app.services.email_service.get_email_provider", return_value=ConsoleEmailProvider()
    ):
        result = domain["client"].post(
            f"/api/vendor-requests/{created['id']}/send",
            headers={**domain["headers"]["admin"], "Idempotency-Key": domain["suffix"] + ":stub"},
        )
    assert result.status_code == 200
    assert result.json()["delivery_status"] == "unavailable"
    assert result.json()["status"] == "pending"


def test_send_and_resend_rotate_grants_and_replay_without_delivery(domain):
    from unittest.mock import patch
    from app.services.email_service import SmtpEmailProvider

    class Provider(SmtpEmailProvider):
        def __init__(self):
            self.messages = []

        def send(self, message, *, sensitive=False):
            assert sensitive is True
            self.messages.append(message)
            return True

    provider = Provider()
    created = create(domain).json()
    url = f"/api/vendor-requests/{created['id']}/send"
    h = {**domain["headers"]["admin"], "Idempotency-Key": domain["suffix"] + ":send"}
    with patch("app.services.email_service.get_email_provider", return_value=provider):
        sent = domain["client"].post(url, headers=h)
        assert sent.status_code == 200
        assert sent.json()["delivery_status"] == "accepted"
        replay = domain["client"].post(url, headers=h)
        assert replay.status_code == 200
        assert len(provider.messages) == 1
        assert replay.json()["link_token"] is None
        resend = domain["client"].post(
            url.replace("/send", "/resend"),
            headers={**h, "Idempotency-Key": domain["suffix"] + ":resend"},
        )
    assert resend.status_code == 200
    assert len(provider.messages) == 2
    assert sent.json()["link_token"] != resend.json()["link_token"]
    assert (
        domain["client"]
        .get("/api/vendor-response", params={"token": sent.json()["link_token"]})
        .status_code
        == 404
    )
    assert (
        domain["client"]
        .get("/api/vendor-response", params={"token": resend.json()["link_token"]})
        .status_code
        == 200
    )


def test_uncertain_delivery_is_persisted_without_automatic_retry(domain):
    from unittest.mock import patch
    from app.services.email_service import SmtpEmailProvider
    from app.core.database import SessionLocal

    class Provider(SmtpEmailProvider):
        def __init__(self):
            self.calls = 0

        def send(self, message, *, sensitive=False):
            assert sensitive is True
            self.calls += 1
            raise TimeoutError("SYNTHETIC-PROVIDER-SECRET")

    provider = Provider()
    created = create(domain).json()
    h = {**domain["headers"]["admin"], "Idempotency-Key": domain["suffix"] + ":uncertain"}
    with patch("app.services.email_service.get_email_provider", return_value=provider):
        first = domain["client"].post(f"/api/vendor-requests/{created['id']}/send", headers=h)
        assert first.status_code == 200
        assert first.json()["delivery_status"] == "uncertain"
        again = domain["client"].post(f"/api/vendor-requests/{created['id']}/send", headers=h)
        other = domain["client"].post(
            f"/api/vendor-requests/{created['id']}/resend",
            headers={**h, "Idempotency-Key": domain["suffix"] + ":other"},
        )
    assert again.status_code == 200
    assert other.status_code == 409
    assert provider.calls == 1
    with SessionLocal() as fresh:
        stored = fresh.get(VendorRequest, created["id"])
        assert stored.delivery_status == "uncertain"
        assert "SECRET" not in str(stored.last_delivery_error)


@pytest.mark.parametrize("change", ["demoted", "removed", "suspended"])
@pytest.mark.parametrize("operation", ["create", "patch", "send", "resend", "revoke"])
def test_stale_admin_session_cannot_mutate(domain, change, operation):
    from app.core.session import sign_session
    from app.models import User, WorkspaceMember

    user = User(email=domain["suffix"] + "-actor@example.com", password_hash="synthetic-unused")
    domain["db"].add(user)
    domain["db"].flush()
    member = WorkspaceMember(workspace_id=1, user_id=user.id, role="admin", suspended=False)
    domain["db"].add(member)
    domain["db"].commit()
    user_id = user.id
    token = sign_session(user_id, user.email, 1, "admin")
    if change == "removed":
        domain["db"].delete(member)
    elif change == "demoted":
        member.role = "editor"
    else:
        member.suspended = True
    domain["db"].commit()
    try:
        domain["client"].cookies.set("tc_session", token)
        h = {"Idempotency-Key": domain["suffix"] + ":stale"}
        if operation == "create":
            response = domain["client"].post(
                "/api/vendor-requests",
                headers=h,
                json={"vendor_email": domain["suffix"] + "@example.com"},
            )
        elif operation == "patch":
            response = domain["client"].patch(
                f"/api/vendor-requests/{domain['own']}", json={"status": "in_progress"}, headers=h
            )
        else:
            response = domain["client"].post(
                f"/api/vendor-requests/{domain['own']}/{operation}", headers=h
            )
        assert response.status_code == 403
        domain["db"].expire_all()
        assert domain["db"].get(VendorRequest, domain["own"]).status == "pending"
    finally:
        domain["client"].cookies.clear()
        domain["db"].rollback()
        domain["db"].query(WorkspaceMember).filter(WorkspaceMember.user_id == user_id).delete(
            synchronize_session=False
        )
        domain["db"].query(User).filter(User.id == user_id).delete(synchronize_session=False)
        domain["db"].commit()
        assert (
            domain["db"].query(WorkspaceMember).filter(WorkspaceMember.user_id == user_id).count()
            == 0
        )
        assert domain["db"].get(User, user_id) is None


def test_migration_round_trip_preserves_non_default_lifecycle(domain):
    import os
    import subprocess
    import sys
    from datetime import timedelta, timezone
    from pathlib import Path
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from app.core.database import engine

    created = create(domain).json()
    assert created.get("expires_at") is not None
    row_id = created["id"]
    row = domain["db"].get(VendorRequest, row_id)
    now = datetime.now(timezone.utc)
    row.revoked_at = now
    row.delivery_status = "accepted"
    row.last_delivery_at = now
    row.last_delivery_error = "synthetic_safe_reason"
    row.submitted_at = now
    row.response_payload = "Synthetic non-default reply"
    row.response_digest = hashlib.sha256(row.response_payload.encode()).hexdigest()
    legacy_tokens = []
    for index, legacy_id in enumerate((domain["own"], domain["foreign"])):
        legacy = domain["db"].get(VendorRequest, legacy_id)
        legacy.link_token = "legacy-" + domain["suffix"] + str(index)
        legacy_tokens.append(legacy.link_token)
        if index == 0:
            legacy.created_at = datetime.utcnow() - timedelta(days=8)
        else:
            legacy.revoked_at = now
    domain["db"].commit()
    names = (
        "expires_at",
        "revoked_at",
        "delivery_status",
        "last_delivery_at",
        "last_delivery_error",
        "submitted_at",
        "response_payload",
        "response_digest",
        "link_token_hash",
    )
    columns = ", ".join(names)
    expected = tuple(
        domain["db"]
        .execute(text(f"SELECT {columns} FROM vendor_requests WHERE id=:id"), {"id": row_id})
        .one()
    )
    domain["db"].rollback()
    api_root = Path(__file__).resolve().parents[2]
    scripts = ScriptDirectory.from_config(Config(str(api_root / "alembic.ini")))
    revision = "tc18002_vendor_lifecycle"
    parent = scripts.get_revision(revision).down_revision

    def migrate(target, direction, succeeds=True):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", direction, target],
            cwd=api_root,
            env={**os.environ, "TRUST_COPILOT_TESTING": "1"},
            capture_output=True,
            text=True,
        )
        assert (result.returncode == 0) == succeeds, result.stdout[-2000:] + result.stderr[-2000:]
        engine.dispose()

    try:
        migrate(parent, "downgrade")
        with engine.begin() as connection:
            # Exact predicate used by the old app: neither expired nor revoked
            # raw token may become resolvable after rollback.
            for token in legacy_tokens:
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM vendor_requests WHERE link_token=:token"),
                        {"token": token},
                    ).scalar()
                    == 0
                )
                assert (
                    connection.execute(
                        text(
                            "SELECT count(*) FROM tc18002_vendor_hold WHERE legacy_link_token=:token"
                        ),
                        {"token": token},
                    ).scalar()
                    == 1
                )
            connection.execute(
                text("UPDATE vendor_requests SET message='changed during downtime' WHERE id=:id"),
                {"id": row_id},
            )
        migrate(revision, "upgrade", succeeds=False)
        with engine.begin() as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM tc18002_vendor_hold WHERE id=:id"), {"id": row_id}
                ).scalar()
                == 1
            )
            connection.execute(
                text("UPDATE vendor_requests SET message='Please review.' WHERE id=:id"),
                {"id": row_id},
            )
        migrate(revision, "upgrade")
        restored = tuple(
            domain["db"]
            .execute(text(f"SELECT {columns} FROM vendor_requests WHERE id=:id"), {"id": row_id})
            .one()
        )
        assert restored == expected
        for token in legacy_tokens:
            assert (
                domain["db"]
                .execute(
                    text("SELECT count(*) FROM vendor_requests WHERE link_token=:token"),
                    {"token": token},
                )
                .scalar()
                == 1
            )
            assert (
                domain["client"].get("/api/vendor-response", params={"token": token}).status_code
                == 404
            )
        assert domain["db"].execute(text("SELECT count(*) FROM tc18002_vendor_hold")).scalar() == 0
        domain["db"].rollback()
    finally:
        migrate("head", "upgrade")
        domain["db"].expire_all()
    for head in scripts.get_heads():
        assert revision in {rev.revision for rev in scripts.walk_revisions(base="base", head=head)}


def test_database_rejects_oversized_response_and_invalid_delivery_state(domain):
    from sqlalchemy.exc import DataError, IntegrityError

    created = create(domain).json()
    assert created.get("expires_at") is not None
    for assignment, value in (("response_payload", "x" * 20001), ("delivery_status", "invented")):
        with pytest.raises((DataError, IntegrityError)):
            domain["db"].execute(
                text(f"UPDATE vendor_requests SET {assignment} = :value WHERE id=:id"),
                {"value": value, "id": created["id"]},
            )
            domain["db"].commit()
        domain["db"].rollback()


@pytest.mark.parametrize("operation", ["send", "resend", "revoke"])
def test_lifecycle_requires_credentials_before_database_access(operation):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes.vendor_requests import router

    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        result = client.post(f"/vendor-requests/123/{operation}")
    assert result.status_code == 401


def test_final_submit_validates_body_before_database_access():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes.vendor_response import router

    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        result = client.post(
            "/vendor-response/submit", json={"token": "long-enough-token", "response": " "}
        )
    assert result.status_code == 422


@pytest.mark.parametrize("field", ["message", "response"])
def test_schema_rejects_non_utf8_text(field):
    from pydantic import ValidationError
    from app.api.routes.vendor_requests import VendorRequestCreate
    from app.api.routes.vendor_response import FinalVendorResponse

    with pytest.raises(ValidationError):
        if field == "message":
            VendorRequestCreate(vendor_email="vendor@example.com", message="\ud800")
        else:
            FinalVendorResponse(token="valid-token-value", response="\ud800")


def test_schema_rejects_control_in_public_token():
    from pydantic import ValidationError
    from app.api.routes.vendor_response import FinalVendorResponse

    with pytest.raises(ValidationError):
        FinalVendorResponse(token="long-token\x00value", response="Valid reply")


def test_legacy_grant_expires_without_get_mutation(domain):
    from datetime import timedelta

    row = domain["db"].get(VendorRequest, domain["own"])
    token = "legacy-" + domain["suffix"]
    row.link_token = token
    row.created_at = datetime.utcnow() - timedelta(days=8)
    domain["db"].commit()
    before = counts(domain["db"])
    result = domain["client"].get("/api/vendor-response", params={"token": token})
    assert result.status_code == 404
    domain["db"].refresh(row)
    assert row.expires_at is None
    assert row.link_token == token
    assert counts(domain["db"]) == before


def test_delivery_intent_survives_post_send_commit_failure(domain):
    from unittest.mock import patch
    from fastapi import HTTPException
    from app.core.database import SessionLocal
    from app.services import vendor_request_service as service

    created = create(domain).json()
    db = domain["db"]
    real_commit = db.commit
    attempted = []

    class Provider:
        def send(self, message):
            with SessionLocal() as fresh:
                assert fresh.get(VendorRequest, created["id"]).delivery_status == "sending"
            attempted.append(message)
            return True

    def fail_outcome_commit():
        if attempted:
            raise RuntimeError("synthetic outcome persistence failure")
        real_commit()

    key = domain["suffix"] + ":crash"
    with patch("app.services.email_service.get_email_provider", return_value=Provider()):
        with patch.object(db, "commit", side_effect=fail_outcome_commit):
            with pytest.raises(RuntimeError, match="synthetic outcome"):
                service.send(db, 1, created["id"], key, False, actor(domain))
        with SessionLocal() as fresh:
            assert fresh.get(VendorRequest, created["id"]).delivery_status == "sending"
        replay = service.send(db, 1, created["id"], key, False, actor(domain))
        assert replay["delivery_status"] == "sending"
        with pytest.raises(HTTPException) as conflict:
            service.send(
                db, 1, created["id"], domain["suffix"] + ":crash-retry", True, actor(domain)
            )
        assert conflict.value.status_code == 409
    assert len(attempted) == 1


def test_creation_lost_claim_rolls_back_request_and_preserves_new_owner(domain):
    from unittest.mock import patch
    from app.core import idempotency
    from app.core.database import SessionLocal
    from app.services import vendor_request_service as service

    key = domain["suffix"] + ":fenced"
    scoped = idempotency.scoped_key(1, "vendor-create", "new", key)
    before = domain["db"].query(VendorRequest).count()
    real_set = idempotency.set

    def take_claim(*args, **kwargs):
        with SessionLocal() as fresh:
            fresh.execute(
                text(
                    "UPDATE idempotency_keys SET owner_token='replacement' WHERE idempotency_key=:k"
                ),
                {"k": scoped},
            )
            fresh.commit()
        return real_set(*args, **kwargs)

    with patch("app.core.idempotency.set", side_effect=take_claim):
        with pytest.raises(idempotency.IdempotencyClaimLost):
            service.create_request(
                domain["db"],
                1,
                domain["suffix"] + "@example.com",
                None,
                None,
                7,
                key,
                actor(domain),
            )
    assert domain["db"].query(VendorRequest).count() == before
    assert (
        domain["db"]
        .execute(
            text("SELECT owner_token FROM idempotency_keys WHERE idempotency_key=:k"), {"k": scoped}
        )
        .scalar()
        == "replacement"
    )


@pytest.mark.parametrize(
    "change", ["removed", "demoted", "suspended", "custom_permission", "api_key"]
)
@pytest.mark.parametrize("operation", ["create", "send", "resend"])
def test_authorization_is_rechecked_after_idempotency_commit(
    domain, monkeypatch, change, operation
):
    from app.core import idempotency
    from app.core.database import SessionLocal
    from app.core.session import sign_session
    from app.models import CustomRole, User, WorkspaceMember
    from app.services import email_service

    db = domain["db"]
    models = (User, WorkspaceMember, CustomRole)
    before = {model: db.query(model).count() for model in models}
    custom = CustomRole(workspace_id=1, name=domain["suffix"], can_admin=True)
    user = User(
        email=domain["suffix"] + "-after-claim@example.com", password_hash="synthetic-unused"
    )
    db.add_all([custom, user])
    db.flush()
    user_id, custom_id = user.id, custom.id
    member = WorkspaceMember(
        workspace_id=1,
        user_id=user_id,
        role=custom.name if change == "custom_permission" else "admin",
    )
    db.add(member)
    db.commit()
    original_claim = idempotency.claim
    delivered = []

    class Provider:
        def send(self, message):
            delivered.append(message)
            return True

    def claim_then_revoke(*args, **kwargs):
        owner = original_claim(*args, **kwargs)
        if owner:
            with SessionLocal() as other:
                current = (
                    other.query(WorkspaceMember).filter_by(workspace_id=1, user_id=user_id).one()
                )
                if change == "removed":
                    other.delete(current)
                elif change == "demoted":
                    current.role = "editor"
                elif change == "suspended":
                    current.suspended = True
                elif change == "custom_permission":
                    other.get(CustomRole, custom_id).can_admin = False
                else:
                    other.query(ApiKey).filter_by(
                        key_hash=actor(domain)["_api_key_hash"]
                    ).one().role = "editor"
                other.commit()
        return owner

    monkeypatch.setattr(idempotency, "claim", claim_then_revoke)
    monkeypatch.setattr(email_service, "get_email_provider", lambda: Provider())
    headers = {"Idempotency-Key": domain["suffix"] + ":after-claim"}
    if change == "api_key":
        headers.update(domain["headers"]["admin"])
    else:
        domain["client"].cookies.set("tc_session", sign_session(user_id, user.email, 1, "admin"))
    request_count = db.query(VendorRequest).count()
    try:
        if operation == "create":
            result = domain["client"].post(
                "/api/vendor-requests",
                headers=headers,
                json={"vendor_email": domain["suffix"] + "@example.com"},
            )
        else:
            result = domain["client"].post(
                f"/api/vendor-requests/{domain['own']}/{operation}", headers=headers
            )
        assert result.status_code == 403
        assert delivered == []
        db.expire_all()
        assert db.query(VendorRequest).count() == request_count
        assert db.get(VendorRequest, domain["own"]).delivery_status is None
    finally:
        domain["client"].cookies.clear()
        db.rollback()
        db.query(WorkspaceMember).filter_by(user_id=user_id).delete(synchronize_session=False)
        db.query(User).filter_by(id=user_id).delete(synchronize_session=False)
        db.query(CustomRole).filter_by(id=custom_id).delete(synchronize_session=False)
        db.commit()
        assert {model: db.query(model).count() for model in models} == before
