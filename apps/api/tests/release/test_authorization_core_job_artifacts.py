"""Export-job artifact metadata with real stored auth and owned SQLite/PG rows."""

import hashlib
import json
import secrets
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.api.routes.jobs import router
from app.core.database import get_db
from app.core.session import sign_session
from app.models import (
    ApiKey,
    AuditEvent,
    CustomRole,
    Document,
    ExportRecord,
    Job,
    Questionnaire,
    User,
    UserMfa,
    UserSession,
    Workspace,
    WorkspaceMember,
)
from app.models.job_effect import JobEffect
from tests import _safety

MODELS = (
    User,
    Workspace,
    WorkspaceMember,
    UserSession,
    UserMfa,
    CustomRole,
    ApiKey,
    Document,
    Questionnaire,
    Job,
    ExportRecord,
    JobEffect,
    AuditEvent,
)
MISSING = 2147483647


def snapshot(db):
    return {
        model.__tablename__: hashlib.sha256(
            json.dumps(
                [
                    dict(row)
                    for row in db.execute(select(model.__table__).order_by(model.id)).mappings()
                ],
                default=str,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        for model in MODELS
    }


@pytest.fixture(params=("sqlite", "postgres"))
def artifacts(request):
    if request.param == "postgres":
        request.getfixturevalue("migrated_db")
        db = request.getfixturevalue("db_session")
        engine = db.get_bind()
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            for model in MODELS:
                connection.execute(CreateTable(model.__table__))
        db = Session(engine)
    baseline = snapshot(db)
    outbound_before = _safety.blocked_attempts()
    token = secrets.token_hex(8)
    ws_ids, user_ids = [], []
    client = None
    try:
        for name in ("own", "foreign"):
            while True:
                wid = 100000 + secrets.randbelow(1000000000)
                if wid not in ws_ids and db.get(Workspace, wid) is None:
                    break
            db.add(Workspace(id=wid, name=name, slug=f"artifact-{name}-{token}"))
            db.flush()
            ws_ids.append(wid)
        user = User(email=f"artifact-{token}@example.com", password_hash="synthetic-unused")
        db.add(user)
        db.flush()
        user_ids.append(user.id)
        sid = f"artifact-{token}"
        member = WorkspaceMember(user_id=user.id, workspace_id=ws_ids[0], role="reviewer")
        db.add_all([member, UserSession(user_id=user.id, session_id=sid)])
        rows = []
        for wid in ws_ids:
            qnr = Questionnaire(workspace_id=wid, filename="synthetic.xlsx", storage_key="original")
            db.add(qnr)
            db.flush()
            job = Job(
                workspace_id=wid,
                kind="export",
                status="completed",
                attempt=2,
                payload=json.dumps({"workspace_id": wid, "questionnaire_id": qnr.id}),
                completed_at=datetime(2026, 1, 2),
            )
            db.add(job)
            db.flush()
            record = ExportRecord(
                workspace_id=wid,
                questionnaire_id=qnr.id,
                job_id=job.id,
                storage_key=f"canonical-{wid}-{token}.xlsx",
                filename="synthetic-export.xlsx",
            )
            db.add(record)
            db.flush()
            job.result = json.dumps(
                {"export_record_id": record.id, "storage_key": record.storage_key}
            )
            rows.append((qnr, job, record))
        db.commit()
        assert all(db.get(model, MISSING) is None for model in (Job, Questionnaire, ExportRecord))
        app = FastAPI()
        app.include_router(router, prefix="/api")

        def database():
            with Session(engine) as current:
                yield current

        app.dependency_overrides[get_db] = database
        client = TestClient(app, raise_server_exceptions=False)
        # The stale admin claim is intentionally stronger than current membership.
        client.cookies.set(
            "tc_session",
            sign_session(user.id, user.email, ws_ids[0], "admin", sid, max_age_seconds=3600),
        )
        yield {
            "db": db,
            "client": client,
            "workspace": ws_ids[0],
            "foreign_workspace": ws_ids[1],
            "user": user,
            "member": member,
            "sid": sid,
            "qnr": rows[0][0],
            "job": rows[0][1],
            "record": rows[0][2],
            "foreign": rows[1],
        }
    finally:
        if client is not None:
            client.close()
        db.rollback()
        if ws_ids:
            db.query(AuditEvent).filter(
                or_(AuditEvent.workspace_id.in_(ws_ids), AuditEvent.user_id.in_(user_ids))
            ).delete(synchronize_session=False)
            for model in (
                ExportRecord,
                JobEffect,
                Job,
                Questionnaire,
                Document,
                ApiKey,
                CustomRole,
                WorkspaceMember,
            ):
                db.query(model).filter(model.workspace_id.in_(ws_ids)).delete(
                    synchronize_session=False
                )
        if user_ids:
            for model in (UserMfa, UserSession):
                db.query(model).filter(model.user_id.in_(user_ids)).delete(
                    synchronize_session=False
                )
            db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        if ws_ids:
            db.query(Workspace).filter(Workspace.id.in_(ws_ids)).delete(synchronize_session=False)
        db.commit()
        assert snapshot(db) == baseline, "Owned cleanup changed pre-existing full rows"
        assert _safety.blocked_attempts() == outbound_before
        if request.param == "sqlite":
            db.close()
            engine.dispose()


def read(state, *, job_id=None, workspace=None, expected=200, suffix="", method="GET"):
    db = state["db"]
    before = snapshot(db)
    statements = []

    def record_sql(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", record_sql)
    try:
        response = state["client"].request(
            method,
            f"/api/jobs/{job_id or state['job'].id}{suffix}?workspace_id={workspace or state['workspace']}",
        )
    finally:
        event.remove(engine, "before_cursor_execute", record_sql)
    db.expire_all()
    assert response.status_code == expected, response.text
    assert snapshot(db) == before, "Reading artifact metadata changed full rows"
    assert all(statement == "SELECT" for statement in statements), statements
    return response


def move_owned_parent(state, row, error_code):
    db = state["db"]
    if db.get_bind().dialect.name == "postgres":
        # Migrated PostgreSQL rejects this inconsistent write before any route
        # can see it. Prove that protection; never disable its trigger/FK.
        before = snapshot(db)
        with pytest.raises(IntegrityError) as rejected:
            with db.begin_nested():
                row.workspace_id = state["foreign_workspace"]
                db.flush()
        assert rejected.value.orig.pgcode == error_code
        assert snapshot(db) == before
        assert read(state).json()["result"] is not None
        # Detaching our nullable reference permits a real move. Its stale job
        # result must still not confer authority after the move.
        state["record"].questionnaire_id = None
        db.commit()
    row.workspace_id = state["foreign_workspace"]


@pytest.mark.parametrize("outcome", (None, "already_applied"))
def test_valid_worker_result_is_preserved_with_lifecycle_fields(artifacts, outcome):
    state = artifacts
    expected = {"export_record_id": state["record"].id, "storage_key": state["record"].storage_key}
    if outcome:
        expected["outcome"] = outcome
    state["job"].result = json.dumps(expected)
    state["db"].add(
        JobEffect(
            job_id=state["job"].id,
            workspace_id=state["workspace"],
            effect="provider:synthetic",
            attempt=1,
            state="uncertain",
        )
    )
    state["db"].commit()
    body = read(state).json()
    assert body["result"] == expected
    assert body["status"] == "completed" and body["attempt"] == 2
    assert body["completed_at"] == "2026-01-02T00:00:00"
    assert body["charge_uncertain"] is True
    assert {"max_attempts", "retryable", "next_attempt_at", "error_detail"} <= body.keys()


def test_artifact_projection_uses_canonical_record_and_no_arbitrary_result_fields(artifacts):
    state = artifacts
    state["job"].result = json.dumps(
        {
            "export_record_id": state["record"].id,
            "storage_key": "PRIVATE-forged-key",
            "download_url": "PRIVATE-forged-url",
            "outcome": "PRIVATE-outcome",
            "nested": {"text": "PRIVATE-content"},
        }
    )
    state["db"].commit()
    response = read(state)
    assert response.json()["result"] == {
        "export_record_id": state["record"].id,
        "storage_key": state["record"].storage_key,
    }
    assert "PRIVATE" not in response.text


@pytest.mark.parametrize("parent", ("foreign", "moved", "soft_deleted", "hard_deleted", "missing"))
def test_current_questionnaire_parent_is_required(artifacts, parent):
    state = artifacts
    payload = json.loads(state["job"].payload)
    if parent == "foreign":
        payload["questionnaire_id"] = state["foreign"][0].id
    elif parent == "moved":
        move_owned_parent(state, state["qnr"], "23514")
    elif parent == "soft_deleted":
        state["qnr"].deleted_at = datetime(2026, 1, 3)
    elif parent == "hard_deleted":
        state["db"].delete(state["qnr"])
    else:
        payload["questionnaire_id"] = MISSING
    state["job"].payload = json.dumps(payload)
    state["db"].commit()
    body = read(state).json()
    assert body["result"] is None
    assert body["status"] == "completed" and body["attempt"] == 2


@pytest.mark.parametrize(
    "mismatch",
    (
        "foreign_record",
        "foreign_workspace",
        "other_questionnaire",
        "other_job",
        "null_questionnaire",
        "null_job",
        "missing",
        "deleted",
    ),
)
def test_export_record_must_match_job_workspace_and_questionnaire(artifacts, mismatch):
    state = artifacts
    result = json.loads(state["job"].result)
    record = state["record"]
    if mismatch == "foreign_record":
        result["export_record_id"] = state["foreign"][2].id
    elif mismatch == "foreign_workspace":
        move_owned_parent(state, record, "23503")
    elif mismatch == "other_questionnaire":
        other = Questionnaire(workspace_id=state["workspace"], filename="other.xlsx")
        state["db"].add(other)
        state["db"].flush()
        record.questionnaire_id = other.id
    elif mismatch == "other_job":
        other = Job(workspace_id=state["workspace"], kind="export", status="completed")
        state["db"].add(other)
        state["db"].flush()
        record.job_id = other.id
    elif mismatch == "null_questionnaire":
        record.questionnaire_id = None
    elif mismatch == "null_job":
        record.job_id = None
    elif mismatch == "missing":
        result["export_record_id"] = MISSING
    else:
        state["db"].delete(record)
    state["job"].result = json.dumps(result)
    state["db"].commit()
    assert read(state).json()["result"] is None


@pytest.mark.parametrize("field", ("payload", "result"))
@pytest.mark.parametrize(
    "raw",
    (None, "", "{broken", "[]", "null", '"PRIVATE"', "[" * 1100 + "]" * 1100),
    ids=("none", "empty", "broken", "array", "null", "string", "deep"),
)
def test_malformed_artifact_json_has_no_result(artifacts, field, raw):
    setattr(artifacts["job"], field, raw)
    artifacts["db"].commit()
    assert read(artifacts).json()["result"] is None


@pytest.mark.parametrize("field", ("questionnaire_id", "export_record_id", "workspace_id"))
@pytest.mark.parametrize(
    "value", (None, True, False, 0, -1, "actual_id", [], {}, 2147483648, 2**100)
)
def test_artifact_ids_are_exact_database_integers(artifacts, field, value):
    attr = "result" if field == "export_record_id" else "payload"
    payload = json.loads(getattr(artifacts["job"], attr))
    payload[field] = str(payload[field]) if value == "actual_id" else value
    setattr(artifacts["job"], attr, json.dumps(payload))
    artifacts["db"].commit()
    assert read(artifacts).json()["result"] is None


def test_conflicting_payload_workspace_cannot_authorize_an_artifact(artifacts):
    payload = json.loads(artifacts["job"].payload)
    payload["workspace_id"] = artifacts["foreign_workspace"]
    artifacts["job"].payload = json.dumps(payload)
    artifacts["db"].commit()
    assert read(artifacts).json()["result"] is None


def test_foreign_and_missing_jobs_share_404_without_content(artifacts):
    foreign = read(artifacts, job_id=artifacts["foreign"][1].id, expected=404)
    missing = read(artifacts, job_id=MISSING, expected=404)
    assert foreign.json() == missing.json() == {"detail": "Job not found"}
    assert read(artifacts, workspace=artifacts["foreign_workspace"], expected=403).json() == {
        "detail": "Access denied"
    }


@pytest.mark.parametrize(
    "denial,status",
    (
        ("anonymous", 401),
        ("revoked", 401),
        ("suspended", 403),
        ("removed", 403),
        ("no_review", 403),
        ("foreign_role", 403),
    ),
)
def test_current_principal_is_required_on_every_read(artifacts, denial, status):
    state = artifacts
    assert read(state).json()["result"] is not None
    if denial == "anonymous":
        state["client"].cookies.clear()
    elif denial == "revoked":
        state["db"].query(UserSession).filter_by(session_id=state["sid"]).delete()
    elif denial == "suspended":
        state["member"].suspended = True
    elif denial == "removed":
        state["db"].delete(state["member"])
    else:
        state["member"].role = "artifact-role"
        state["db"].add(
            CustomRole(
                workspace_id=state["foreign_workspace"]
                if denial == "foreign_role"
                else state["workspace"],
                name="artifact-role",
                can_review=denial == "foreign_role",
                can_edit=False,
                can_export=False,
                can_admin=False,
            )
        )
    state["db"].commit()
    assert "storage_key" not in read(state, expected=status).text


@pytest.mark.parametrize(
    "raw,expected",
    (
        ('{"legacy_field":"synthetic legacy result"}', {"legacy_field": "synthetic legacy result"}),
        ("legacy text", "legacy text"),
        ("[]", []),
    ),
)
def test_parentless_non_export_legacy_result_contract_is_unchanged(artifacts, raw, expected):
    artifacts["job"].kind = "generate_answers"
    artifacts["job"].payload = "{}"
    artifacts["job"].result = raw
    artifacts["db"].commit()
    body = read(artifacts).json()
    assert body["result"] == expected
    assert "progress" not in body and "object_ref" not in body


def test_already_cancelled_response_shares_safe_projection_without_mutation(artifacts):
    artifacts["member"].role = "admin"
    artifacts["job"].status = "cancelled"
    artifacts["qnr"].deleted_at = datetime(2026, 1, 3)
    artifacts["db"].commit()
    body = read(artifacts, suffix="/cancel", method="POST").json()
    assert body["status"] == "cancelled" and body["result"] is None


def test_database_lookup_failure_cannot_fall_back_to_stored_artifact(artifacts):
    engine = artifacts["db"].get_bind()

    def fail_lookup(_connection, _cursor, statement, _parameters, _context, _many):
        if (
            statement.lstrip().upper().startswith("SELECT")
            and "FROM export_records" in statement
            and "WHERE" in statement
        ):
            raise RuntimeError("Synthetic artifact lookup failure")

    event.listen(engine, "before_cursor_execute", fail_lookup)
    try:
        response = read(artifacts, expected=500)
        assert "storage_key" not in response.text
    finally:
        event.remove(engine, "before_cursor_execute", fail_lookup)
