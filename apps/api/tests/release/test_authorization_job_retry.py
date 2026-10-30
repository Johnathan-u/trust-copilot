"""TC-06-002h: retry checks current payload references before any writes.

Real stored-auth HTTP, reference guards and database rows. SQLite controls use
actual FK-enforced model tables; PostgreSQL runs against the migrated schema.
"""

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.jobs import router
from app.core.database import Base, get_db
from app.core.session import sign_session
from app.models import (
    ApiKey,
    AuditEvent,
    CustomRole,
    Document,
    Job,
    Questionnaire,
    User,
    UserMfa,
    UserSession,
    Workspace,
    WorkspaceMember,
)
from app.models.job_effect import JobEffect
from app.services import job_control

MODELS = (
    AuditEvent,
    JobEffect,
    Job,
    Questionnaire,
    Document,
    UserMfa,
    UserSession,
    ApiKey,
    CustomRole,
    WorkspaceMember,
    User,
    Workspace,
)
FIELDS = ("workspace_id", "questionnaire_id", "document_id")
KINDS = ("parse_questionnaire", "generate_answers", "export", "index_document", "parse_evidence")
NOT_FOUND = {"detail": "Job not found"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def snapshot(db):
    return {
        model.__tablename__: {
            row["id"]: digest(dict(row))
            for row in db.execute(select(model.__table__).order_by(model.id)).mappings()
        }
        for model in MODELS
    }


@pytest.fixture(params=("sqlite", "postgres"))
def retry_store(request):
    if request.param == "postgres":
        request.getfixturevalue("migrated_db")
        from app.core.database import SessionLocal

        db = SessionLocal()
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
    owned = {model: set() for model in MODELS}
    client = None

    def add(model, **values):
        row = model(**values)
        db.add(row)
        db.flush()
        owned[model].add(row.id)
        return row

    def remember(current, _context):
        for row in current.new:
            if type(row) in owned:
                owned[type(row)].add(row.id)

    try:
        suffix = secrets.token_hex(8)
        workspaces = []
        for label in ("own", "foreign"):
            while True:
                wid = 100000 + secrets.randbelow(1000000000)
                if db.get(Workspace, wid) is None:
                    break
            workspaces.append(add(Workspace, id=wid, name=label, slug=f"retry-{label}-{suffix}"))
        own, foreign = workspaces
        user = add(User, email=f"retry-{suffix}@example.com", password_hash="unused")
        other_user = add(User, email=f"retry-other-{suffix}@example.com", password_hash="unused")
        member = add(WorkspaceMember, user_id=user.id, workspace_id=own.id, role="admin")
        sid = add(UserSession, user_id=user.id, session_id=secrets.token_hex(24))
        role = add(CustomRole, workspace_id=own.id, name=f"retry-admin-{suffix}", can_admin=True)
        add(CustomRole, workspace_id=foreign.id, name=role.name, can_admin=True)
        refs = {}
        for field, model in (("questionnaire_id", Questionnaire), ("document_id", Document)):
            refs[field] = {}
            for label in ("own", "foreign", "archived", "moved", "deleted"):
                values = {
                    "workspace_id": foreign.id if label == "foreign" else own.id,
                    "filename": f"synthetic-{suffix}",
                }
                if model is Document:
                    values["storage_key"] = f"synthetic/{suffix}/{label}"
                row = add(model, **values)
                refs[field][label] = row.id
                if label == "archived":
                    row.deleted_at = datetime.now(timezone.utc)
                elif label == "moved":
                    row.workspace_id = foreign.id
                elif label == "deleted":
                    db.delete(row)
                    db.flush()
            refs[field]["missing"] = 2147483647
            assert db.get(model, refs[field]["deleted"]) is None
            assert db.get(model, refs[field]["missing"]) is None
        db.commit()
        app = FastAPI()
        app.include_router(router, prefix="/api")

        def database():
            with Session(engine) as current:
                event.listen(current, "after_flush", remember)
                yield current

        app.dependency_overrides[get_db] = database
        client = TestClient(app)

        def cookie(**overrides):
            fields = {"session_id": sid.session_id, "max_age_seconds": 3600}
            fields.update(overrides)
            client.cookies.clear()
            client.cookies.set(
                "tc_session", sign_session(user.id, user.email, own.id, "admin", **fields)
            )

        def job(payload, **overrides):
            old = datetime.now(timezone.utc) - timedelta(hours=1)
            values = {
                "workspace_id": own.id,
                "kind": "generate_answers",
                "status": "failed",
                "payload": json.dumps(payload) if isinstance(payload, dict) else payload,
                "attempt": 2,
                "max_attempts": 3,
                "error_code": "timeout",
                "error": "Synthetic prior error",
                "result": '{"outcome":"superseded"}',
                "started_at": old,
                "completed_at": old,
                "next_attempt_at": old,
                "lease_owner": "synthetic-prior-owner",
                "lease_expires_at": old,
            }
            values.update(overrides)
            row = add(Job, **values)
            db.commit()
            return row

        cookie()
        yield dict(
            db=db,
            engine=engine,
            client=client,
            own=own,
            foreign=foreign,
            user=user,
            other_user=other_user,
            member=member,
            sid=sid,
            role=role,
            refs=refs,
            job=job,
            cookie=cookie,
        )
    finally:
        if client is not None:
            client.close()
        db.rollback()
        try:
            for model in MODELS:
                if owned[model]:
                    db.query(model).filter(model.id.in_(owned[model])).delete(
                        synchronize_session=False
                    )
            db.commit()
            assert snapshot(db) == original, "Cleanup changed pre-existing rows"
        finally:
            db.close()
            if request.param == "sqlite":
                engine.dispose()


def invoke(state, job_id, *, action="retry", status=404, unchanged=True, workspace_id=None):
    before = snapshot(state["db"])
    statements = []

    def capture(_connection, _cursor, sql, _parameters, _context, _many):
        statements.append(sql)

    event.listen(state["engine"], "before_cursor_execute", capture)
    try:
        workspace_id = state["own"].id if workspace_id is None else workspace_id
        response = state["client"].post(
            f"/api/jobs/{job_id}/{action}", params={"workspace_id": workspace_id}
        )
    finally:
        event.remove(state["engine"], "before_cursor_execute", capture)
    state["db"].expire_all()
    state["statements"] = statements
    assert response.status_code == status
    if unchanged:
        assert snapshot(state["db"]) == before
        assert {sql.lstrip().split(None, 1)[0].upper() for sql in statements} <= {"SELECT"}
    if status == 404:
        assert response.json() == NOT_FOUND
    return response


@pytest.mark.parametrize("field", ("questionnaire_id", "document_id"))
@pytest.mark.parametrize("reference", ("foreign", "moved", "missing", "archived", "deleted"))
def test_invalid_reference_denies_retry_without_any_mutation(retry_store, field, reference):
    state = retry_store
    row = state["job"]({field: state["refs"][field][reference]})
    invoke(state, row.id)


@pytest.mark.parametrize(
    "field,model", (("questionnaire_id", Questionnaire), ("document_id", Document))
)
@pytest.mark.parametrize("change", ("moved", "archived", "deleted"))
def test_parent_change_after_job_creation_is_rechecked(retry_store, field, model, change):
    state = retry_store
    reference = state["refs"][field]["own"]
    row = state["job"]({field: reference})
    parent = state["db"].get(model, reference)
    if change == "moved":
        parent.workspace_id = state["foreign"].id
    elif change == "archived":
        parent.deleted_at = datetime.now(timezone.utc)
    else:
        state["db"].delete(parent)
    state["db"].commit()
    invoke(state, row.id)


def test_explicit_workspace_mismatch_denies_retry_without_any_mutation(retry_store):
    state = retry_store
    row = state["job"](
        {
            "workspace_id": state["foreign"].id,
            "questionnaire_id": state["refs"]["questionnaire_id"]["own"],
        }
    )
    invoke(state, row.id)


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize(
    "value", (True, False, None, "1", "bad", 1.0, [], [1], {}, 0, -1, 2147483648)
)
def test_explicit_reference_types_are_not_coerced(retry_store, field, value):
    state = retry_store
    row = state["job"]({field: value})
    invoke(state, row.id)


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("representation", (str, float), ids=("numeric_string", "float"))
def test_matching_numeric_reference_is_not_coerced(retry_store, field, representation):
    state = retry_store
    reference = state["own"].id if field == "workspace_id" else state["refs"][field]["own"]
    row = state["job"]({field: representation(reference)})
    invoke(state, row.id)


@pytest.mark.parametrize("invalid_field", ("questionnaire_id", "document_id"))
def test_each_explicit_reference_is_checked_even_when_other_reference_is_owned(
    retry_store, invalid_field
):
    state = retry_store
    payload = {field: refs["own"] for field, refs in state["refs"].items()}
    payload[invalid_field] = state["refs"][invalid_field]["foreign"]
    row = state["job"](payload)
    invoke(state, row.id)


def successful_retry(state, row):
    before = snapshot(state["db"])
    columns = {column.name: getattr(row, column.name) for column in Job.__table__.columns}
    response = invoke(state, row.id, status=200, unchanged=False)
    assert response.json()["status"] == row.status == "queued"
    assert response.json()["attempt"] == row.attempt == 0
    assert row.next_attempt_at is None and row.completed_at is None
    assert row.lease_owner is None and row.lease_expires_at is None
    changed = {
        "status",
        "attempt",
        "next_attempt_at",
        "completed_at",
        "lease_owner",
        "lease_expires_at",
        "updated_at",
    }
    assert digest({key: value for key, value in columns.items() if key not in changed}) == digest(
        {key: getattr(row, key) for key in columns if key not in changed}
    )
    audits = (
        state["db"]
        .query(AuditEvent)
        .filter(
            AuditEvent.resource_type == "job",
            AuditEvent.resource_id == str(row.id),
            AuditEvent.workspace_id == state["own"].id,
        )
        .all()
    )
    assert len(audits) == 1
    audit = audits[0]
    assert audit.action == "job.manual_retry"
    assert audit.workspace_id == state["own"].id and audit.user_id == state["user"].id
    assert audit.email == state["user"].email
    assert json.loads(audit.details) == {
        "actor_user_id": state["user"].id,
        "prior_status": columns["status"],
        "prior_error_code": "timeout",
        "prior_error": "Synthetic prior error",
        "prior_attempt": 2,
    }
    after = snapshot(state["db"])
    del before["jobs"][row.id]
    del after["jobs"][row.id]
    del after["audit_events"][audit.id]
    assert after == before
    with Session(state["engine"]) as fresh:
        assert snapshot(fresh) == snapshot(state["db"])


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("prior_status", ("failed", "cancelled"))
def test_current_owned_references_preserve_retry_and_audit(retry_store, kind, prior_status):
    state = retry_store
    row = state["job"](
        {
            "workspace_id": state["own"].id,
            **{field: refs["own"] for field, refs in state["refs"].items()},
        },
        kind=kind,
        status=prior_status,
    )
    successful_retry(state, row)


@pytest.mark.parametrize(
    "payload", (None, "", "{}", '{"legacy":true}', "{", "[]", "null", '"legacy"', "3", "true")
)
def test_reference_free_and_malformed_legacy_retries_are_preserved(retry_store, payload):
    state = retry_store
    row = state["job"](payload, kind="parse_evidence")
    successful_retry(state, row)


@pytest.mark.parametrize(
    "authority,status",
    (
        ("editor", 403),
        ("reviewer", 403),
        ("suspended", 403),
        ("removed", 403),
        ("revoked", 401),
        ("expired", 401),
        ("custom_revoked", 403),
        ("custom_missing", 403),
        ("custom_foreign", 403),
        ("anonymous", 401),
    ),
)
def test_current_principal_denial_precedes_job_access(retry_store, authority, status):
    state = retry_store
    row = state["job"]({"questionnaire_id": state["refs"]["questionnaire_id"]["own"]})
    if authority in {"editor", "reviewer"}:
        state["member"].role = authority
    elif authority == "suspended":
        state["member"].suspended = True
    elif authority == "removed":
        state["db"].delete(state["member"])
    elif authority == "revoked":
        state["db"].delete(state["sid"])
    elif authority == "expired":
        state["cookie"](max_age_seconds=-1)
    elif authority == "anonymous":
        state["client"].cookies.clear()
    else:
        state["member"].role = state["role"].name
        if authority == "custom_revoked":
            state["role"].can_admin = False
        elif authority == "custom_missing":
            state["db"].delete(state["role"])
        else:
            state["role"].workspace_id = state["foreign"].id
    state["db"].commit()
    invoke(state, row.id, status=status)
    assert not any("FROM jobs" in sql for sql in state["statements"])


def test_current_custom_admin_grant_allows_retry(retry_store):
    state = retry_store
    state["member"].role = state["role"].name
    state["db"].commit()
    successful_retry(state, state["job"]({"document_id": state["refs"]["document_id"]["own"]}))


@pytest.mark.parametrize("target", ("foreign_job", "missing_job", "foreign_query"))
def test_foreign_and_missing_jobs_have_the_same_read_only_denial(retry_store, target):
    state = retry_store
    row = state["job"](
        {}, workspace_id=state["foreign"].id if target == "foreign_job" else state["own"].id
    )
    invoke(
        state,
        2147483647 if target == "missing_job" else row.id,
        workspace_id=state["foreign"].id if target == "foreign_query" else state["own"].id,
    )


@pytest.mark.parametrize("prior_status", ("queued", "running", "completed"))
def test_non_retryable_status_precedes_invalid_reference(retry_store, prior_status):
    state = retry_store
    row = state["job"](
        {"document_id": state["refs"]["document_id"]["foreign"]}, status=prior_status
    )
    response = invoke(state, row.id, status=409)
    assert response.json()["error"]["code"] == "job_not_retryable"


@pytest.mark.parametrize("retry_store", ("postgres",), indirect=True)
def test_existing_idempotency_conflict_precedes_invalid_reference(retry_store):
    # PostgreSQL's actual partial unique index supports this fixture. Do not
    # remove or replace the model index to emulate it in SQLite.
    state = retry_store
    key = f"synthetic-{secrets.token_hex(16)}"
    state["job"]({}, status="running", idempotency_key=key)
    row = state["job"](
        {"document_id": state["refs"]["document_id"]["foreign"]}, idempotency_key=key
    )
    response = invoke(state, row.id, status=409)
    assert response.json()["error"]["code"] == "idempotency_conflict"


@pytest.mark.parametrize("payload", ("{", '{"workspace_id":null}', '{"document_id":2147483647}'))
def test_cancel_own_malformed_job_still_works_and_is_idempotent(retry_store, payload):
    state = retry_store
    row = state["job"](payload, status="queued")
    invoke(state, row.id, action="cancel", status=200, unchanged=False)
    assert row.status == "cancelled" and row.attempt == 2
    audits = (
        state["db"]
        .query(AuditEvent)
        .filter(
            AuditEvent.resource_type == "job",
            AuditEvent.resource_id == str(row.id),
            AuditEvent.workspace_id == state["own"].id,
        )
        .all()
    )
    assert len(audits) == 1 and audits[0].action == "job.cancelled"
    invoke(state, row.id, action="cancel", status=200)


@pytest.mark.parametrize("failure", ("database", "unexpected_http"))
def test_unexpected_reference_failures_are_not_disguised_as_missing(
    retry_store, monkeypatch, failure
):
    state = retry_store
    row = state["job"]({"questionnaire_id": state["refs"]["questionnaire_id"]["own"]})
    before = snapshot(state["db"])
    statements = []

    def fail_query(_connection, _cursor, sql, _parameters, _context, _many):
        statements.append(sql.lstrip().split(None, 1)[0].upper())
        if "FROM questionnaires" in sql:
            raise OperationalError("synthetic reference outage", {}, RuntimeError("synthetic"))

    def unexpected_http(*_args):
        raise HTTPException(status_code=503, detail="Synthetic reference outage")

    if failure == "database":
        event.listen(state["engine"], "before_cursor_execute", fail_query)
        try:
            with pytest.raises(OperationalError):
                state["client"].post(f"/api/jobs/{row.id}/retry?workspace_id={state['own'].id}")
        finally:
            event.remove(state["engine"], "before_cursor_execute", fail_query)
        assert set(statements) <= {"SELECT"}
    else:
        monkeypatch.setattr(job_control, "require_in_workspace", unexpected_http)
        invoke(state, row.id, status=503)
    assert snapshot(state["db"]) == before
