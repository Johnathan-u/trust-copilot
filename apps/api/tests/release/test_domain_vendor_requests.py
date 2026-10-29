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

        def send(self, message):
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

        def send(self, message):
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
    token = sign_session(user.id, user.email, 1, "admin")
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
        domain["db"].query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).delete(
            synchronize_session=False
        )
        domain["db"].query(User).filter(User.id == user.id).delete(synchronize_session=False)
        domain["db"].commit()
        assert (
            domain["db"].query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).count()
            == 0
        )
        assert domain["db"].get(User, user.id) is None
