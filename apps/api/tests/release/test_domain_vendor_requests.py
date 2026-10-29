"""Outbound request boundary regressions on real PostgreSQL; synthetic data only."""

import hashlib
import secrets
from datetime import datetime

import pytest
from sqlalchemy import text

from app.models import ApiKey, Questionnaire, VendorRequest

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
