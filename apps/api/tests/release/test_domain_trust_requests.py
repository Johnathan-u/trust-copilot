"""Trust intake and tenant boundary regressions with complete synthetic-row cleanup."""

import hashlib
import secrets
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.models import ApiKey, AuditEvent, TrustRequest, TrustRequestNote, User, WorkspaceMember
from app.core.session import sign_session

TABLES = (
    "trust_requests",
    "trust_request_notes",
    "api_keys",
    "audit_events",
    "idempotency_keys",
    "users",
    "workspace_members",
)


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
    person = User(email=f"{suffix}-reviewer@example.com", password_hash=secrets.token_hex(32))
    db_session.add(person)
    db_session.flush()
    db_session.add(
        WorkspaceMember(workspace_id=1, user_id=person.id, role="reviewer", suspended=False)
    )
    db_session.add(
        WorkspaceMember(workspace_id=2, user_id=person.id, role="reviewer", suspended=True)
    )
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
        "user": person.id,
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
    db_session.query(WorkspaceMember).filter(WorkspaceMember.user_id == person.id).delete(
        synchronize_session=False
    )
    db_session.query(User).filter(User.id == person.id).delete(synchronize_session=False)
    db_session.commit()
    client.cookies.clear()
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


def submit(d, headers=None):
    return d["client"].post(
        "/api/trust-requests/submit",
        data={
            "requester_email": f"{d['suffix']}@example.com",
            "message": "Review?",
            "workspace_id": "1",
        },
        files={"document": ("request.txt", b"Synthetic request", "text/plain")},
        headers=headers,
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


def test_attachment_is_durable_downloadable_and_retry_does_not_reupload(domain):
    from app.core.database import SessionLocal
    from app.main import app
    from app.services.storage import get_storage

    class Storage:
        bucket_raw = "synthetic"
        objects = {}
        uploads = 0

        def upload(self, bucket, key, content, **kwargs):
            self.objects[key] = content
            self.uploads += 1

        def download_stream(self, bucket, key):
            return iter([self.objects[key]])

    storage = Storage()
    previous = app.dependency_overrides.get(get_storage)
    app.dependency_overrides[get_storage] = lambda: storage
    try:
        headers = {"Idempotency-Key": domain["suffix"] + "-attachment"}
        first, retry = submit(domain, headers), submit(domain, headers)
        assert first.status_code == retry.status_code == 200
        assert first.json() == retry.json()
        assert storage.uploads == 1
        rid = first.json()["id"]
        with SessionLocal() as fresh:
            row = fresh.get(TrustRequest, rid)
            assert row.attachment_filename == "request.txt"
            assert row.attachment_size == len(b"Synthetic request")
            assert storage.objects[row.attachment_storage_key] == b"Synthetic request"
        download = domain["client"].get(
            f"/api/trust-requests/{rid}/attachment", headers=domain["headers"]["admin"]
        )
        assert download.status_code == 200
        assert download.content == b"Synthetic request"
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_storage, None)
        else:
            app.dependency_overrides[get_storage] = previous


def test_post_upload_database_failure_compensates_blob_and_releases_retry(domain):
    before = counts(domain["db"])
    key = f"trust-requests/1/{domain['own']}/synthetic.txt"
    with (
        patch(
            "app.api.routes.trust_requests.FileService.upload_trust_request_attachment",
            return_value=(key, "request.txt", 17),
        ),
        patch("app.api.routes.trust_requests.FileService.delete_raw") as delete,
        patch(
            "app.services.trust_request_service.finish_intake", side_effect=RuntimeError("PRIVATE")
        ),
    ):
        response = submit(domain, {"Idempotency-Key": domain["suffix"] + "-failure"})
    assert response.status_code == 502
    assert "PRIVATE" not in response.text
    delete.assert_called_once_with(key)
    assert counts(domain["db"]) == before


def test_invalid_retry_header_is_422_without_rows(domain):
    before = counts(domain["db"])
    response = submit(domain, {"Idempotency-Key": "invalid key"})
    assert response.status_code == 422
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


def _human(domain):
    domain["client"].cookies.set(
        "tc_session", sign_session(domain["user"], "reviewer@example.com", 1, "reviewer")
    )
    return domain["client"]


def _draft(domain):
    response = domain["client"].post(
        f"/api/trust-requests/{domain['own']}/replies",
        json={"body": "Exact reviewed body"},
        headers=domain["headers"]["admin"],
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _reply_url(d, note, action=""):
    return f"/api/trust-requests/{d['own']}/replies/{note}" + ("/" + action if action else "")


def test_approved_revision_delivery_and_retry_survive_new_db_session(domain):
    from app.core.database import SessionLocal

    calls = []

    class Provider:
        def send(self, message):
            assert message.body_text == "Exact reviewed body"
            calls.append(message.to)
            return True

    note_id = _draft(domain)
    client = _human(domain)
    unreviewed = client.post(_reply_url(domain, note_id, "send"), json={"revision": 1})
    assert unreviewed.status_code == 409
    approved = client.post(_reply_url(domain, note_id, "approve"), json={"revision": 1})
    assert approved.status_code == 200, approved.text
    assert approved.json()["approved_by"] == domain["user"]
    assert approved.json()["approved_revision"] == 1
    assert approved.json()["approved_at"]
    with patch("app.services.trust_request_service.get_email_provider", return_value=Provider()):
        sent = client.post(_reply_url(domain, note_id, "send"), json={"revision": 1})
        retried = client.post(_reply_url(domain, note_id, "send"), json={"revision": 1})
    assert sent.status_code == retried.status_code == 200
    assert sent.json()["delivery_status"] == "accepted"
    assert sent.json()["delivery_attempts"] == 1
    assert retried.json()["delivery_accepted_at"] == sent.json()["delivery_accepted_at"]
    assert calls == [f"{domain['suffix']}@example.com"]
    with SessionLocal() as fresh:
        row = fresh.get(TrustRequestNote, note_id)
        assert row.delivery_status == "accepted"
        assert row.approved_by == domain["user"]
        assert row.body == "Exact reviewed body"
    response = client.patch(f"/api/trust-requests/{domain['own']}", json={"status": "completed"})
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_edit_invalidates_approval_and_stale_revision_cannot_send(domain):
    note = _draft(domain)
    client = _human(domain)
    assert client.post(_reply_url(domain, note, "approve"), json={"revision": 1}).status_code == 200
    edited = client.patch(_reply_url(domain, note), json={"revision": 1, "body": "Changed answer"})
    assert edited.status_code == 200
    assert edited.json()["body_revision"] == 2
    assert edited.json()["approved_at"] is None
    for revision in (1, 2):
        assert (
            client.post(_reply_url(domain, note, "send"), json={"revision": revision}).status_code
            == 409
        )
    assert (
        client.patch(
            _reply_url(domain, note), json={"revision": 1, "body": "Stale overwrite"}
        ).status_code
        == 409
    )


@pytest.mark.parametrize("state", ["sending", "tampered_body"])
def test_uncertain_intent_and_unreviewed_text_cannot_trigger_delivery(domain, state):
    note_id = _draft(domain)
    client = _human(domain)
    assert (
        client.post(_reply_url(domain, note_id, "approve"), json={"revision": 1}).status_code == 200
    )
    row = domain["db"].get(TrustRequestNote, note_id)
    if state == "sending":
        row.delivery_status = "sending"
        row.delivery_attempts = 1
    else:
        row.body = "Changed outside the approved revision"
    domain["db"].commit()
    with patch("app.services.trust_request_service.get_email_provider") as provider:
        response = client.post(_reply_url(domain, note_id, "send"), json={"revision": 1})
    assert response.status_code == (200 if state == "sending" else 409)
    provider.assert_not_called()
    if state == "sending":
        assert response.json()["delivery_status"] == "sending"


@pytest.mark.parametrize("mode", ["exception", "false", "console", "disabled"])
def test_delivery_failure_or_stub_is_never_confirmed_or_repeated(domain, mode):
    from app.services.email_service import ConsoleEmailProvider, DisabledEmailProvider

    calls = []

    class Provider:
        def send(self, message):
            calls.append(message.body_text)
            if mode == "exception":
                raise RuntimeError("SYNTHETIC-PRIVATE-PROVIDER-ERROR")
            return False

    provider = (
        ConsoleEmailProvider()
        if mode == "console"
        else DisabledEmailProvider()
        if mode == "disabled"
        else Provider()
    )
    note = _draft(domain)
    client = _human(domain)
    assert client.post(_reply_url(domain, note, "approve"), json={"revision": 1}).status_code == 200
    with patch("app.services.trust_request_service.get_email_provider", return_value=provider):
        first = client.post(_reply_url(domain, note, "send"), json={"revision": 1})
        second = client.post(_reply_url(domain, note, "send"), json={"revision": 1})
    expected = "unavailable" if mode in ("console", "disabled") else "uncertain"
    assert first.status_code == second.status_code == 200
    assert first.json()["delivery_status"] == second.json()["delivery_status"] == expected
    assert first.json()["delivery_accepted_at"] is None
    assert "SYNTHETIC-PRIVATE" not in first.text
    assert len(calls) == (0 if expected == "unavailable" else 1)
    assert (
        client.patch(
            f"/api/trust-requests/{domain['own']}", json={"status": "completed"}
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "action,method,payload",
    [
        ("approve", "post", {"revision": 1}),
        ("send", "post", {"revision": 1}),
        ("", "patch", {"revision": 1, "body": "Change"}),
    ],
)
def test_reply_mutations_enforce_permission_and_tenant(domain, action, method, payload):
    note = _draft(domain)
    url = _reply_url(domain, note, action)
    assert (
        domain["client"]
        .request(method, url, json=payload, headers=domain["headers"]["denied"])
        .status_code
        == 403
    )
    bad = []
    for req_id in (domain["foreign"], 2147483647):
        other_url = url.replace(f"trust-requests/{domain['own']}/", f"trust-requests/{req_id}/")
        response = domain["client"].request(
            method, other_url, json=payload, headers=domain["headers"]["admin"]
        )
        assert response.status_code == 404
        bad.append(response.json())
    assert bad[0] == bad[1]


@pytest.mark.parametrize("member_change", ["removed", "suspended", "demoted"])
@pytest.mark.parametrize("action", ["create", "edit", "approve", "send", "assign"])
def test_stale_human_session_cannot_mutate(domain, member_change, action):
    note = _draft(domain)
    client = _human(domain)
    assert client.post(_reply_url(domain, note, "approve"), json={"revision": 1}).status_code == 200
    member = (
        domain["db"].query(WorkspaceMember).filter_by(workspace_id=1, user_id=domain["user"]).one()
    )
    if member_change == "removed":
        domain["db"].delete(member)
    elif member_change == "suspended":
        member.suspended = True
    else:
        member.role = "denied"
    domain["db"].commit()
    before = counts(domain["db"])
    method, url, body = {
        "create": ("post", f"/api/trust-requests/{domain['own']}/replies", {"body": "Draft"}),
        "edit": ("patch", _reply_url(domain, note), {"revision": 1, "body": "Edited"}),
        "approve": ("post", _reply_url(domain, note, "approve"), {"revision": 1}),
        "send": ("post", _reply_url(domain, note, "send"), {"revision": 1}),
        "assign": ("patch", f"/api/trust-requests/{domain['own']}", {"status": "in_progress"}),
    }[action]
    with patch("app.services.trust_request_service.get_email_provider") as provider:
        response = client.request(method, url, json=body)
    assert response.status_code == 403
    provider.assert_not_called()
    assert counts(domain["db"]) == before
    domain["db"].expire_all()
    assert domain["db"].get(TrustRequestNote, note).body == "Exact reviewed body"
    assert domain["db"].get(TrustRequestNote, note).delivery_status == "approved"
    assert domain["db"].get(TrustRequest, domain["own"]).status == "new"


@pytest.mark.parametrize("action", ["approve", "send"])
def test_expired_human_session_cannot_approve_or_send(domain, action):
    note = _draft(domain)
    domain["client"].cookies.set(
        "tc_session",
        sign_session(domain["user"], "reviewer@example.com", 1, "reviewer", max_age_seconds=-1),
    )
    before = counts(domain["db"])
    response = domain["client"].post(_reply_url(domain, note, action), json={"revision": 1})
    assert response.status_code == 401
    assert counts(domain["db"]) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("body", "x" * 10001),
        ("body_revision", 1000001),
        ("approved_revision", 2),
        ("delivery_attempts", 11),
        ("delivery_status", "invented"),
        ("delivery_error", "x" * 129),
        ("approved_body_hash", "x" * 65),
    ],
)
def test_database_enforces_reply_bounds(domain, field, value):
    from sqlalchemy.exc import IntegrityError, DataError

    note = _draft(domain)
    with pytest.raises((IntegrityError, DataError)):
        with domain["db"].begin_nested():
            domain["db"].execute(
                text(f"UPDATE trust_request_notes SET {field}=:value WHERE id=:id"),
                {"id": note, "value": value},
            )


def test_database_enforces_versioned_intake_size(domain):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with domain["db"].begin_nested():
            domain["db"].execute(
                text("UPDATE trust_requests SET intake_version=1, message=:message WHERE id=:id"),
                {"id": domain["own"], "message": "x" * 10001},
            )


def test_migrated_reply_indexes_and_foreign_key_match_model(domain):
    from sqlalchemy import inspect

    inspector = inspect(domain["db"].bind)
    index = next(
        i
        for i in inspector.get_indexes("trust_request_notes")
        if i["name"] == "ix_trust_request_notes_approved_by"
    )
    assert index["column_names"] == ["approved_by"]
    foreign_key = next(
        f
        for f in inspector.get_foreign_keys("trust_request_notes")
        if f["name"] == "fk_trust_reply_approved_by"
    )
    assert foreign_key["constrained_columns"] == ["approved_by"]
    assert foreign_key["referred_table"] == "users"
    assert foreign_key["options"]["ondelete"] == "SET NULL"
    model_fk = next(iter(TrustRequestNote.__table__.c.approved_by.foreign_keys))
    assert model_fk.name == foreign_key["name"]
    assert model_fk.ondelete == foreign_key["options"]["ondelete"]
    model_checks = {
        c.name
        for c in TrustRequestNote.__table__.constraints
        if c.name and c.name.startswith("ck_trust_reply_")
    }
    actual_checks = {c["name"] for c in inspector.get_check_constraints("trust_request_notes")}
    assert model_checks <= actual_checks


def test_assigning_suspended_member_fails_without_changing_status(domain):
    # The human is suspended in ws2, so an own request in ws2 cannot assign them.
    from app.core.session import sign_session

    domain["client"].cookies.set("tc_session", sign_session(None, "admin@example.com", 2, "admin"))
    response = domain["client"].patch(
        f"/api/trust-requests/{domain['foreign']}",
        json={"assignee_id": domain["user"], "status": "in_progress"},
    )
    assert response.status_code == 400
    domain["db"].expire_all()
    assert domain["db"].get(TrustRequest, domain["foreign"]).status == "new"


@pytest.mark.parametrize("changed_while_downgraded", [False, True])
def test_migration_restores_nondefault_reply_provenance(domain, changed_while_downgraded):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.core.database import engine
    from datetime import datetime, timezone

    note_id = _draft(domain)
    stamp = datetime(2020, 2, 3, 4, 5, tzinfo=timezone.utc)
    fields = {
        "body_revision": 3,
        "approved_revision": 3,
        "approved_by": domain["user"],
        "approved_at": stamp,
        "approved_body_hash": hashlib.sha256(b"Exact reviewed body").hexdigest(),
        "delivery_status": "uncertain",
        "delivery_attempts": 2,
        "delivery_started_at": stamp,
        "delivery_accepted_at": stamp,
        "delivery_error": "delivery_outcome_unknown",
    }
    row = domain["db"].get(TrustRequestNote, note_id)
    for key, value in fields.items():
        setattr(row, key, value)
    domain["db"].get(TrustRequest, domain["own"]).intake_version = 1
    domain["db"].commit()
    path = Path(__file__).parents[2] / "alembic/versions/tc18001_reviewed_replies.py"
    spec = importlib.util.spec_from_file_location("migration_reply", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
                held = connection.execute(
                    text(
                        "SELECT body_revision, delivery_error FROM tc18001_reply_hold WHERE note_id=:id"
                    ),
                    {"id": note_id},
                ).one()
                assert held == (3, "delivery_outcome_unknown")
                if changed_while_downgraded:
                    connection.execute(
                        text(
                            "UPDATE trust_request_notes SET body='Changed by old app' WHERE id=:id"
                        ),
                        {"id": note_id},
                    )
                migration.upgrade()
            restored = (
                connection.execute(
                    text("SELECT " + ",".join(fields) + " FROM trust_request_notes WHERE id=:id"),
                    {"id": note_id},
                )
                .mappings()
                .one()
            )
            assert dict(restored) == (
                {name: None for name in fields} if changed_while_downgraded else fields
            )
            # The hold table still retains the original provenance when old text changed.
            assert (
                connection.execute(
                    text("SELECT delivery_attempts FROM tc18001_reply_hold WHERE note_id=:id"),
                    {"id": note_id},
                ).scalar()
                == 2
            )
            assert (
                connection.execute(
                    text("SELECT intake_version FROM trust_requests WHERE id=:id"),
                    {"id": domain["own"]},
                ).scalar()
                == 1
            )
        finally:
            transaction.rollback()
    domain["db"].expire_all()


def test_revision_reaches_all_current_heads():
    from pathlib import Path
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[2] / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    for head in scripts.get_heads():
        assert any(
            r.revision == "tc18001_reviewed_replies"
            for r in scripts.iterate_revisions(head, "base")
        )
