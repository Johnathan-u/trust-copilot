"""Trust intake and tenant boundary regressions with complete synthetic-row cleanup."""

import hashlib
import secrets
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.models import ApiKey, AuditEvent, TrustRequest, TrustRequestNote

TABLES = ("trust_requests", "trust_request_notes", "api_keys", "audit_events", "idempotency_keys")


def counts(db):
    return {name: db.execute(text(f"SELECT count(*) FROM {name}")).scalar() for name in TABLES}


@pytest.fixture
def domain(client, db_session):
    before = counts(db_session)
    suffix = secrets.token_hex(8)
    headers = {}
    for role in ("admin", "denied"):
        raw = secrets.token_urlsafe(32)
        db_session.add(
            ApiKey(
                workspace_id=1,
                role=role,
                label=suffix,
                key_hash=hashlib.sha256(raw.encode()).hexdigest(),
            )
        )
        headers[role] = {"Authorization": f"Bearer {raw}"}
    rows = [
        TrustRequest(
            workspace_id=ws,
            requester_email=f"{suffix}@example.com",
            message="Review?",
            status="new",
        )
        for ws in (1, 2, None)
    ]
    db_session.add_all(rows)
    db_session.commit()
    state = {
        "client": client,
        "db": db_session,
        "suffix": suffix,
        "headers": headers,
        "own": rows[0].id,
        "foreign": rows[1].id,
        "unscoped": rows[2].id,
    }
    yield state
    db_session.rollback()
    ids = [
        r.id
        for r in db_session.query(TrustRequest)
        .filter(TrustRequest.requester_email.contains(suffix))
        .all()
    ]
    note_ids = [
        r.id
        for r in db_session.query(TrustRequestNote)
        .filter(TrustRequestNote.trust_request_id.in_(ids))
        .all()
    ]
    for kind, values in (("trust_request", ids), ("trust_request_note", note_ids)):
        db_session.query(AuditEvent).filter(
            AuditEvent.resource_type == kind, AuditEvent.resource_id.in_([str(i) for i in values])
        ).delete(synchronize_session=False)
    db_session.query(TrustRequestNote).filter(TrustRequestNote.trust_request_id.in_(ids)).delete(
        synchronize_session=False
    )
    db_session.query(TrustRequest).filter(TrustRequest.id.in_(ids)).delete(
        synchronize_session=False
    )
    db_session.execute(
        text("DELETE FROM idempotency_keys WHERE idempotency_key LIKE :key"),
        {"key": "%" + suffix + "%"},
    )
    db_session.query(ApiKey).filter(ApiKey.label == suffix).delete(synchronize_session=False)
    db_session.commit()
    assert counts(db_session) == before


@pytest.mark.parametrize(
    "method,tail,body",
    [
        ("get", "", None),
        ("get", "/notes", None),
        ("get", "/attachment", None),
        ("patch", "", {"status": "in_progress"}),
        ("post", "/notes", {"body": "A note"}),
        ("post", "/replies", {"body": "A reply"}),
        ("post", "/suggest-reply", None),
    ],
)
def test_missing_foreign_and_unscoped_ids_are_equal_404(domain, method, tail, body):
    responses = [
        domain["client"].request(
            method, f"/api/trust-requests/{i}{tail}", json=body, headers=domain["headers"]["admin"]
        )
        for i in (2147483647, domain["foreign"], domain["unscoped"])
    ]
    assert [r.status_code for r in responses] == [404, 404, 404]
    assert responses[0].json() == responses[1].json() == responses[2].json()


@pytest.mark.parametrize(
    "method,tail,body",
    [
        ("patch", "", {"status": "in_progress"}),
        ("delete", "?workspace_id=1", None),
        ("post", "/restore?workspace_id=1", {}),
        ("patch", "/metadata?workspace_id=1", {"frameworks": [], "subject_areas": []}),
        ("post", "/notes", {"body": "A note"}),
        ("post", "/replies", {"body": "A reply"}),
        ("post", "/suggest-reply", None),
    ],
)
def test_every_private_mutation_checks_permissions(domain, method, tail, body):
    before = counts(domain["db"])
    response = domain["client"].request(
        method,
        f"/api/trust-requests/{domain['own']}{tail}",
        json=body,
        headers=domain["headers"]["denied"],
    )
    assert response.status_code == 403
    assert counts(domain["db"]) == before


def test_bulk_delete_checks_permission(domain):
    response = domain["client"].post(
        "/api/trust-requests/bulk-delete?workspace_id=1",
        json={"ids": [domain["own"]]},
        headers=domain["headers"]["denied"],
    )
    assert response.status_code == 403


def test_delete_preview_get_is_read_only(domain):
    before = counts(domain["db"])
    response = domain["client"].get(
        f"/api/trust-requests/{domain['own']}/delete-preview?workspace_id=1",
        headers=domain["headers"]["admin"],
    )
    assert response.status_code == 200
    assert counts(domain["db"]) == before


def submit(d):
    return d["client"].post(
        "/api/trust-requests/submit",
        data={
            "requester_email": f"{d['suffix']}@example.com",
            "message": "Review?",
            "workspace_id": "1",
        },
        files={"document": ("request.txt", b"Synthetic request", "text/plain")},
    )


def test_attachment_storage_failure_is_honest_and_creates_no_orphan(domain):
    before = counts(domain["db"])
    with patch(
        "app.api.routes.trust_requests.FileService.upload_trust_request_attachment",
        side_effect=RuntimeError("SYNTHETIC-SENSITIVE-PROVIDER-DETAIL"),
    ):
        response = submit(domain)
    assert response.status_code == 502
    assert "SYNTHETIC-SENSITIVE" not in response.text
    assert counts(domain["db"]) == before


def test_rejected_attachment_creates_no_request(domain):
    before = counts(domain["db"])
    response = domain["client"].post(
        "/api/trust-requests/submit",
        data={
            "requester_email": f"{domain['suffix']}@example.com",
            "message": "Review?",
            "workspace_id": "1",
        },
        files={"document": ("request.exe", b"Synthetic", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert counts(domain["db"]) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("requester_email", "bad-address"),
        ("requester_email", "a@example.com\r\nInjected: yes"),
        ("message", "  "),
        ("message", "x" * 10001),
        ("subject", "s" * 256),
    ],
    ids=["invalid-address", "header-injection", "empty-message", "message-limit", "subject-limit"],
)
def test_intake_schema_rejects_invalid_and_oversized_input(field, value):
    from app.api.routes.trust_requests import TrustRequestCreate

    body = {"requester_email": "test@example.com", "message": "Review?", field: value}
    with pytest.raises(ValidationError):
        TrustRequestCreate(**body)


def test_reply_creation_is_draft_and_cannot_send_inline(domain):
    response = domain["client"].post(
        f"/api/trust-requests/{domain['own']}/replies",
        json={"body": "A reviewed answer", "send_email": True},
        headers=domain["headers"]["admin"],
    )
    assert response.status_code == 409
    assert (
        not domain["db"].query(TrustRequestNote).filter_by(trust_request_id=domain["own"]).count()
    )
    response = domain["client"].post(
        f"/api/trust-requests/{domain['own']}/replies",
        json={"body": "A draft answer"},
        headers=domain["headers"]["admin"],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["body_revision"] == 1
    assert body["approved_at"] is None
    assert body["delivery_status"] == "draft"


def test_api_key_cannot_fabricate_human_reply_approval(domain):
    response = domain["client"].post(
        f"/api/trust-requests/{domain['own']}/replies",
        json={"body": "A draft answer"},
        headers=domain["headers"]["admin"],
    )
    note_id = response.json()["id"]
    approval = domain["client"].post(
        f"/api/trust-requests/{domain['own']}/replies/{note_id}/approve",
        json={"revision": 1},
        headers=domain["headers"]["admin"],
    )
    assert approval.status_code == 403


def test_public_intake_retry_is_one_persisted_request(domain):
    headers = {"Idempotency-Key": domain["suffix"] + "-intake"}
    payload = {
        "requester_email": f"{domain['suffix']}@example.com",
        "message": "One request",
        "workspace_id": 1,
    }
    first = domain["client"].post("/api/trust-requests/", json=payload, headers=headers)
    second = domain["client"].post("/api/trust-requests/", json=payload, headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    conflict = domain["client"].post(
        "/api/trust-requests/", json={**payload, "message": "Different request"}, headers=headers
    )
    assert conflict.status_code == 409


@pytest.mark.parametrize(
    "field,value",
    [
        ("requester_email", "a\0@example.com"),
        ("requester_email", "İ" * 243 + "@example.com"),
        ("message", "hello\0there"),
    ],
    ids=["nul-email", "unicode-expansion", "nul-message"],
)
def test_intake_schema_rejects_unstorable_text(field, value):
    from app.api.routes.trust_requests import TrustRequestCreate

    with pytest.raises(ValidationError):
        TrustRequestCreate(
            **{"requester_email": "test@example.com", "message": "Review?", field: value}
        )
