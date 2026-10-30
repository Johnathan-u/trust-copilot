"""Persisted job history: PostgreSQL acceptance and explicit SQLite control-path checks."""

import json
import uuid
from contextlib import contextmanager
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.jobs import router
from app.core.auth_deps import require_can_review
from app.core.database import Base, get_db
from app.models import Document, ExportRecord, Job, Questionnaire, Workspace
from app.models.job_effect import JobEffect


@pytest.fixture
def local_history():
    """Local SQL/control checks only; this does not qualify PostgreSQL or real auth."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    tables = [Workspace, Document, Questionnaire, Job, JobEffect, ExportRecord]
    Base.metadata.create_all(engine, tables=[model.__table__ for model in tables])
    with Session(engine) as db:
        db.add_all(
            [
                Workspace(id=1, name="Local", slug="local"),
                Workspace(id=2, name="Other", slug="other"),
            ]
        )
        db.commit()
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[require_can_review] = lambda: {
            "workspace_id": 1,
            "role": "reviewer",
        }
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            yield client, db
    engine.dispose()


def add_job(db, *, workspace_id=1, **values):
    fields = dict(
        workspace_id=workspace_id,
        kind="generate_answers",
        status="running",
        attempt=1,
        max_attempts=3,
        payload="{}",
        created_at=datetime(2026, 1, 1),
    )
    fields.update(values)
    row = Job(**fields)
    db.add(row)
    db.commit()
    return row.id


@pytest.mark.unit
def test_history_sql_control_scopes_and_cursors_after_insert(local_history):
    client, db = local_history
    ids = [add_job(db) for _ in range(4)]
    add_job(db, workspace_id=2)
    first = client.get("/api/jobs?workspace_id=1&limit=2")
    assert first.status_code == 200, first.text
    assert [item["id"] for item in first.json()["items"]] == ids[:1:-1]
    assert first.json()["next_before_id"] == ids[2]
    newer = add_job(db)
    next_page = client.get(f"/api/jobs?workspace_id=1&limit=2&before_id={ids[2]}")
    assert [item["id"] for item in next_page.json()["items"]] == ids[1::-1]
    assert next_page.json()["next_before_id"] is None
    assert client.get("/api/jobs?workspace_id=1").json()["items"][0]["id"] == newer
    foreign = client.get("/api/jobs?workspace_id=2")
    missing = client.get("/api/jobs?workspace_id=2000000000")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


@pytest.mark.unit
@pytest.mark.parametrize(
    "query",
    [
        "",
        "workspace_id=1&limit=0",
        "workspace_id=1&limit=101",
        "workspace_id=1&before_id=0",
        "workspace_id=1&before_id=-1",
    ],
)
def test_history_rejects_unbounded_or_invalid_page(local_history, query):
    client, _ = local_history
    assert client.get("/api/jobs?" + query).status_code == 422


@pytest.mark.unit
def test_history_positive_cursor_above_existing_id_range_is_valid(local_history):
    client, db = local_history
    job_id = add_job(db)
    response = client.get("/api/jobs?workspace_id=1&before_id=2147483648")
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [job_id]


@pytest.mark.unit
def test_history_projection_never_exposes_raw_stored_text(local_history):
    client, db = local_history
    job_id = add_job(
        db,
        status="failed",
        error="PRIVATE provider detail",
        error_code="PRIVATE unknown code",
        payload=json.dumps({"request_id": "PRIVATE request", "storage_key": "PRIVATE key"}),
        result=json.dumps(
            {
                "generated": 2,
                "total": 5,
                "count": 2,
                "stats": {"body": "PRIVATE"},
                "storage_key": "PRIVATE",
            }
        ),
        lease_owner="PRIVATE owner",
        idempotency_key="PRIVATE idempotency",
        input_version="PRIVATE version",
    )
    response = client.get("/api/jobs?workspace_id=1")
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert "PRIVATE" not in response.text
    assert item["id"] == job_id
    assert item["progress"] == {"generated": 2, "total": 5}
    assert item["error_detail"]["code"] == "job_failed"
    assert item["error_detail"]["retryable"] is False
    assert not {
        "result",
        "payload",
        "error",
        "lease_owner",
        "idempotency_key",
        "input_version",
    }.intersection(item)


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    [
        "{broken",
        "[]",
        "null",
        '"PRIVATE"',
        '{"generated":true,"total":-1}',
        '{"generated":"2","total":2.5}',
    ],
)
def test_history_malformed_result_has_no_fabricated_progress(local_history, raw):
    client, db = local_history
    add_job(db, payload=raw, result=raw)
    response = client.get("/api/jobs?workspace_id=1")
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["progress"] is None
    assert response.json()["items"][0]["object_ref"] is None


@pytest.mark.unit
def test_history_object_reference_is_current_and_authorized(local_history):
    client, db = local_history
    doc = Document(workspace_id=1, storage_key="PRIVATE key", filename="PRIVATE name")
    db.add(doc)
    db.commit()
    add_job(db, kind="index_document", payload=json.dumps({"document_id": doc.id}))
    item = client.get("/api/jobs?workspace_id=1").json()["items"][0]
    assert item["object_ref"] == {"type": "document", "id": doc.id}
    for field, value in (("deleted_at", datetime(2026, 1, 2)), ("workspace_id", 2)):
        doc.deleted_at = None
        setattr(doc, field, value)
        db.commit()
        assert client.get("/api/jobs?workspace_id=1").json()["items"][0]["object_ref"] is None


@pytest.mark.unit
def test_history_only_current_job_kinds_and_statuses_are_public(local_history):
    client, db = local_history
    add_job(db, kind="PRIVATE kind", status="PRIVATE status", result='{"generated":2,"total":3}')
    response = client.get("/api/jobs?workspace_id=1")
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["kind"] is None and item["status"] is None
    assert item["progress"] is None
    assert "PRIVATE" not in response.text


# All tables this fixture and the real permission/detail/mutation paths can touch,
# in foreign-key-safe deletion order. Compare full rows, not just counts.
TABLES = (
    "export_records",
    "job_effects",
    "jobs",
    "questionnaires",
    "documents",
    "audit_events",
    "in_app_notifications",
    "idempotency_keys",
    "user_sessions",
    "api_keys",
    "custom_roles",
    "workspace_members",
    "users",
    "workspaces",
)


def row_snapshot():
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        return {
            name: [tuple(row) for row in db.execute(text(f"SELECT * FROM {name} ORDER BY id"))]
            for name in TABLES
        }


@pytest.fixture
def history_db(_ensure_test_data):
    from app.core.database import SessionLocal
    from app.models import CustomRole, User, UserSession, WorkspaceMember

    if not _ensure_test_data:
        pytest.fail("PostgreSQL is required for job history acceptance")
    before = row_snapshot()
    actors = {}
    token = uuid.uuid4().hex
    try:
        with SessionLocal() as db:
            # Baseline fixtures allocate explicit workspace IDs. Use fresh explicit
            # IDs without changing a sequence or any pre-existing workspace row.
            first = db.execute(text("SELECT COALESCE(MAX(id), 0) + 1 FROM workspaces")).scalar_one()
            ws = Workspace(id=first, name="History", slug=f"history-{token}")
            other = Workspace(id=first + 1, name="Other history", slug=f"history-other-{token}")
            db.add_all([ws, other])
            db.flush()
            actors.update(ws=ws.id, other_ws=other.id)
            roles = ["admin", "editor", "reviewer", "missing-role", "foreign-role", "suspended"]
            for bits in range(16):
                role = f"history-{bits:04b}"
                roles.append(role)
                db.add(
                    CustomRole(
                        workspace_id=ws.id,
                        name=role,
                        can_review=bool(bits & 1),
                        can_edit=bool(bits & 2),
                        can_export=bool(bits & 4),
                        can_admin=bool(bits & 8),
                    )
                )
            db.add(CustomRole(workspace_id=other.id, name="foreign-role", can_review=True))
            for role in roles:
                user = User(
                    email=f"{role}-{token}@test.local",
                    password_hash="unused-signed-session",
                    display_name=role,
                )
                db.add(user)
                db.flush()
                effective_role = "reviewer" if role == "suspended" else role
                db.add(
                    WorkspaceMember(
                        workspace_id=ws.id,
                        user_id=user.id,
                        role=effective_role,
                        suspended=role == "suspended",
                    )
                )
                session_id = uuid.uuid4().hex
                db.add(UserSession(user_id=user.id, session_id=session_id))
                actors[role] = (user.id, user.email, effective_role, session_id)
            db.commit()
        yield actors
    finally:
        current = row_snapshot()
        with SessionLocal() as db:
            for name in TABLES:
                old_ids = {row[0] for row in before[name]}
                created = [row[0] for row in current[name] if row[0] not in old_ids]
                if created:
                    statement = text(f"DELETE FROM {name} WHERE id IN :ids").bindparams(
                        bindparam("ids", expanding=True)
                    )
                    db.execute(statement, {"ids": created})
            db.commit()
        assert row_snapshot() == before, "Fixture must restore every original full row and count"


@contextmanager
def history_client(actors, role="reviewer"):
    from app.core.session import sign_session
    from app.main import app
    from tests.conftest import TEST_HEADERS

    # No app startup is needed for this DB-only endpoint. Real auth, signing,
    # membership, custom-role lookup, routing and database dependencies are used.
    client = TestClient(app, headers=TEST_HEADERS)
    try:
        if role is not None:
            user_id, email, current_role, session_id = actors[role]
            client.cookies.set(
                "tc_session",
                sign_session(
                    user_id,
                    email,
                    workspace_id=actors["ws"],
                    role=current_role,
                    session_id=session_id,
                    max_age_seconds=3600,
                ),
            )
        yield client
    finally:
        client.close()


def get_unchanged(client, url):
    before = row_snapshot()
    response = client.get(url)
    assert row_snapshot() == before, "GET changed persisted rows"
    return response


@pytest.mark.integration
@pytest.mark.parametrize(
    "role,status",
    [
        (None, 401),
        ("admin", 200),
        ("editor", 200),
        ("reviewer", 200),
        ("missing-role", 403),
        ("foreign-role", 403),
        ("suspended", 403),
    ]
    + [(f"history-{bits:04b}", 200 if bits & 1 else 403) for bits in range(16)],
)
def test_postgres_history_uses_existing_permission_contract(history_db, role, status):
    with history_client(history_db, role) as client:
        response = get_unchanged(client, f"/api/jobs?workspace_id={history_db['ws']}")
        assert response.status_code == status, response.text
        if status == 200:
            assert response.json() == {"items": [], "next_before_id": None}


@pytest.mark.integration
def test_postgres_history_rechecks_custom_permission(history_db):
    from app.core.database import SessionLocal
    from app.models import CustomRole

    with history_client(history_db, "history-0001") as client:
        url = f"/api/jobs?workspace_id={history_db['ws']}"
        assert get_unchanged(client, url).status_code == 200
        with SessionLocal() as db:
            row = (
                db.query(CustomRole)
                .filter_by(workspace_id=history_db["ws"], name="history-0001")
                .one()
            )
            row.can_review = False
            db.commit()
        assert get_unchanged(client, url).status_code == 403


@pytest.mark.integration
def test_postgres_history_pagination_persists_across_new_client_and_insert(history_db):
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        own = [add_job(db, workspace_id=history_db["ws"]) for _ in range(102)]
        foreign_id = add_job(db, workspace_id=history_db["other_ws"])
    url = f"/api/jobs?workspace_id={history_db['ws']}"
    with history_client(history_db) as client:
        first = get_unchanged(client, url).json()
        assert [item["id"] for item in first["items"]] == own[-25:][::-1]
        assert first["next_before_id"] == own[-25]
        assert get_unchanged(client, url).json() == first
        maximum = get_unchanged(client, url + "&limit=100").json()
        assert len(maximum["items"]) == 100
        assert maximum["next_before_id"] == own[2]
        denied = get_unchanged(client, f"/api/jobs?workspace_id={history_db['other_ws']}")
        absent = get_unchanged(client, "/api/jobs?workspace_id=2000000000")
        assert denied.status_code == absent.status_code == 404
        assert denied.json() == absent.json()
    with SessionLocal() as db:
        newest = add_job(db, workspace_id=history_db["ws"])
    with history_client(history_db) as client:
        following = get_unchanged(
            client, url + f"&limit=100&before_id={first['next_before_id']}"
        ).json()
        assert [item["id"] for item in following["items"]] == own[:-25][::-1]
        assert following["next_before_id"] is None
        assert newest not in [item["id"] for item in following["items"]]
        assert foreign_id not in [item["id"] for item in following["items"]]
        assert get_unchanged(client, url).json()["items"][0]["id"] == newest
        assert get_unchanged(client, url + "&before_id=1").json() == {
            "items": [],
            "next_before_id": None,
        }


@pytest.mark.integration
@pytest.mark.parametrize(
    "kind,model,field,expected_type",
    [
        ("index_document", Document, "document_id", "document"),
        ("parse_evidence", Document, "document_id", "document"),
        ("parse_questionnaire", Questionnaire, "questionnaire_id", "questionnaire"),
        ("generate_answers", Questionnaire, "questionnaire_id", "questionnaire"),
        ("export", Questionnaire, "questionnaire_id", "questionnaire"),
    ],
)
def test_postgres_history_references_current_objects_only(
    history_db, kind, model, field, expected_type
):
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        own = model(
            workspace_id=history_db["ws"], storage_key="PRIVATE original", filename="PRIVATE name"
        )
        foreign = model(
            workspace_id=history_db["other_ws"],
            storage_key="PRIVATE foreign",
            filename="PRIVATE foreign",
        )
        db.add_all([own, foreign])
        db.commit()
        own_id, foreign_id = own.id, foreign.id
        good = add_job(
            db, workspace_id=history_db["ws"], kind=kind, payload=json.dumps({field: own_id})
        )
        bad = [
            add_job(
                db, workspace_id=history_db["ws"], kind=kind, payload=json.dumps({field: value})
            )
            for value in (foreign_id, 2000000000, -1, 0, True, str(own_id), 10**40)
        ]
    with history_client(history_db) as client:
        url = f"/api/jobs?workspace_id={history_db['ws']}"
        response = get_unchanged(client, url)
        assert response.status_code == 200
        items = {item["id"]: item for item in response.json()["items"]}
        assert items[good]["object_ref"] == {"type": expected_type, "id": own_id}
        assert all(items[job_id]["object_ref"] is None for job_id in bad)
        assert "PRIVATE" not in response.text
        with SessionLocal() as db:
            db.get(model, own_id).deleted_at = datetime(2026, 1, 2)
            db.commit()
        assert all(
            item["object_ref"] is None for item in get_unchanged(client, url).json()["items"]
        )
        with SessionLocal() as db:
            row = db.get(model, own_id)
            row.deleted_at = None
            row.workspace_id = history_db["other_ws"]
            db.commit()
        assert all(
            item["object_ref"] is None for item in get_unchanged(client, url).json()["items"]
        )


@pytest.mark.integration
def test_postgres_history_safe_lifecycle_projection_and_malformed_json(history_db):
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        retrying = add_job(
            db,
            workspace_id=history_db["ws"],
            status="queued",
            attempt=2,
            error_code="rate_limited",
            error="PRIVATE upstream",
            next_attempt_at=datetime(2026, 1, 2),
        )
        exhausted = add_job(
            db,
            workspace_id=history_db["ws"],
            status="failed",
            attempt=3,
            error_code="model_timeout",
            payload='{"request_id":"PRIVATE request"}',
            result='{"generated":2,"total":5,"storage_key":"PRIVATE"}',
            error="PRIVATE failure",
        )
        db.add(
            JobEffect(
                job_id=exhausted,
                workspace_id=history_db["ws"],
                effect="completions",
                attempt=3,
                state="uncertain",
                detail="PRIVATE provider",
            )
        )
        db.commit()
        malformed = [
            add_job(db, workspace_id=history_db["ws"], payload=raw, result=raw)
            for raw in ("{broken", "null", "[]", '"PRIVATE"')
        ]
        unknown = add_job(
            db,
            workspace_id=history_db["ws"],
            kind="PRIVATE kind",
            status="PRIVATE status",
            error_code="PRIVATE code",
        )
        completed = add_job(
            db,
            workspace_id=history_db["ws"],
            status="completed",
            result='{"outcome":"already_applied","effect":"PRIVATE"}',
            completed_at=datetime(2026, 1, 2),
        )
    with history_client(history_db) as client:
        response = get_unchanged(client, f"/api/jobs?workspace_id={history_db['ws']}")
        assert response.status_code == 200, response.text
        assert "PRIVATE" not in response.text
        items = {item["id"]: item for item in response.json()["items"]}
        assert items[retrying]["retry_scheduled"] is True
        assert items[retrying]["retryable"] is True
        assert items[retrying]["retries_exhausted"] is False
        assert items[exhausted]["retries_exhausted"] is True
        assert items[exhausted]["charge_uncertain"] is True
        assert items[exhausted]["progress"] == {"generated": 2, "total": 5}
        assert items[exhausted]["error_detail"]["code"] == "model_timeout"
        assert items[exhausted]["error_detail"]["retryable"] is True
        assert all(
            items[job_id]["progress"] is None and items[job_id]["object_ref"] is None
            for job_id in malformed
        )
        assert (
            items[unknown]["kind"]
            is items[unknown]["status"]
            is items[unknown]["error_code"]
            is None
        )
        assert items[completed]["outcome"] == "already_applied"
        assert items[completed]["completed_at"] == "2026-01-02T00:00:00"


@pytest.mark.integration
def test_postgres_existing_detail_cancel_retry_contracts_unchanged(history_db):
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        job_id = add_job(
            db,
            workspace_id=history_db["ws"],
            status="queued",
            result='{"legacy_field":"synthetic legacy result"}',
        )
    with history_client(history_db, "admin") as client:
        url = f"/api/jobs/{job_id}"
        query = f"?workspace_id={history_db['ws']}"
        detail = get_unchanged(client, url + query)
        assert detail.status_code == 200
        assert detail.json()["result"] == {"legacy_field": "synthetic legacy result"}
        assert "progress" not in detail.json() and "object_ref" not in detail.json()
        cancelled = client.post(url + "/cancel" + query)
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled.json().keys() == detail.json().keys()
        retried = client.post(url + "/retry" + query)
        assert retried.status_code == 200, retried.text
        assert retried.json()["status"] == "queued"
        assert retried.json()["attempt"] == 0
        assert retried.json().keys() == detail.json().keys()
