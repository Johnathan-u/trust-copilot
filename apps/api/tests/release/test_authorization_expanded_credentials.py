"""TC-06-003e: real credential routes, stored sessions and current grants.

SQLite provides local controls; the same cases on migrated PostgreSQL qualify
the actual database. Credential values and complete-row comparisons stay hashed.
"""

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.api.routes.credentials import router
from app.core.database import get_db
from app.core.session import sign_session
from app.models import CustomRole, User, UserMfa, UserSession, Workspace, WorkspaceMember
from app.models.credential_store import CredentialStore
from app.services import credential_store_service as service
from app.services.credential_store_service import decrypt, encrypt

MODELS = (User, Workspace, WorkspaceMember, UserSession, UserMfa, CustomRole, CredentialStore)
PUBLIC_FIELDS = {
    "id",
    "workspace_id",
    "source_type",
    "credential_type",
    "status",
    "expires_at",
    "last_rotated_at",
    "rotation_interval_days",
    "created_at",
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def rows(db):
    """All columns, including ciphertext and metadata; no plaintext in failures."""
    return {
        model.__tablename__: {
            row["id"]: digest(dict(row))
            for row in db.execute(select(model.__table__).order_by(model.id)).mappings()
        }
        for model in MODELS
    }


@pytest.fixture(params=("sqlite", "postgres"))
def credentials(request):
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
    before = rows(db)
    owned = {model: [] for model in MODELS}
    client = None

    def add(model, **values):
        row = model(**values)
        db.add(row)
        db.flush()
        owned[model].append(row.id)
        return row

    try:
        suffix = secrets.token_hex(8)
        workspaces = []
        for label in ("own", "foreign"):
            while True:
                wid = 100000 + secrets.randbelow(1000000000)
                if db.get(Workspace, wid) is None:
                    break
            workspaces.append(
                add(Workspace, id=wid, name=label, slug=f"credential-{label}-{suffix}")
            )
        own, foreign = workspaces
        user = add(User, email=f"credential-{suffix}@example.com", password_hash="synthetic-unused")
        member = add(WorkspaceMember, user_id=user.id, workspace_id=own.id, role="admin")
        sid = add(UserSession, user_id=user.id, session_id=f"credential-{suffix}")
        role = add(
            CustomRole,
            workspace_id=own.id,
            name="credential-manager",
            can_admin=True,
            can_edit=False,
            can_review=False,
            can_export=False,
        )
        add(CustomRole, workspace_id=foreign.id, name="credential-manager", can_admin=True)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        records = {}
        values = []
        # Insert the foreign duplicate first: dropping an upsert's workspace
        # predicate must not accidentally find the own row by insertion order.
        for workspace in reversed(workspaces):
            for label, status, rotated, interval, expires in (
                ("due", "active", now - timedelta(days=10), 1, now + timedelta(days=3)),
                ("expired", "active", now - timedelta(days=10), 1, now - timedelta(days=3)),
                ("future", "active", now, 30, now + timedelta(days=30)),
                ("revoked", "revoked", now - timedelta(days=10), 1, now + timedelta(days=3)),
                ("unscheduled", "active", now, None, None),
            ):
                value = secrets.token_urlsafe(32)
                values.append(value)
                records[workspace.id, label] = add(
                    CredentialStore,
                    workspace_id=workspace.id,
                    source_type=f"{suffix}-{label}",
                    credential_type="synthetic",
                    encrypted_value=encrypt(value),
                    status=status,
                    last_rotated_at=rotated,
                    rotation_interval_days=interval,
                    expires_at=expires,
                    metadata_json=json.dumps({"fixture": suffix, "workspace": workspace.id}),
                )
        foreign_only = add(
            CredentialStore,
            workspace_id=foreign.id,
            source_type=f"{suffix}-foreign-only",
            credential_type="synthetic",
            encrypted_value=encrypt(secrets.token_urlsafe(32)),
            metadata_json=json.dumps({"fixture": suffix}),
        )
        db.commit()
        app = FastAPI()
        app.include_router(router, prefix="/api")

        def database():
            with Session(engine) as current:
                yield current

        # Only the test-owned DB connection is substituted. Authentication,
        # current permissions, routes, encryption and storage queries are real.
        app.dependency_overrides[get_db] = database
        client = TestClient(app)

        def cookie(**overrides):
            fields = {"session_id": sid.session_id, "max_age_seconds": 3600}
            fields.update(overrides)
            client.cookies.clear()
            client.cookies.set(
                "tc_session", sign_session(user.id, user.email, own.id, "admin", **fields)
            )

        cookie()
        yield {
            "db": db,
            "engine": engine,
            "client": client,
            "owned": owned,
            "own": own,
            "foreign": foreign,
            "member": member,
            "sid": sid,
            "role": role,
            "records": records,
            "foreign_only": foreign_only,
            "values": values,
            "cookie": cookie,
            "suffix": suffix,
            "now": now,
        }
    finally:
        if client is not None:
            client.close()
        db.rollback()
        # Also discover successful HTTP-created rows only inside these exact
        # fixture-owned workspace IDs; a failed assertion cannot leak them.
        if owned[Workspace]:
            owned[CredentialStore] = list(
                db.scalars(
                    select(CredentialStore.id).where(
                        CredentialStore.workspace_id.in_(owned[Workspace])
                    )
                )
            )
        for model in reversed(MODELS):
            if owned[model]:
                db.query(model).filter(model.id.in_(owned[model])).delete(synchronize_session=False)
        db.commit()
        assert rows(db) == before, "Cleanup changed pre-existing rows"
        if request.param == "sqlite":
            db.close()
            engine.dispose()


def request(state, method, path, *, unchanged=True, **kwargs):
    before = rows(state["db"])
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(state["engine"], "before_cursor_execute", record)
    try:
        response = state["client"].request(method, path, **kwargs)
    finally:
        event.remove(state["engine"], "before_cursor_execute", record)
    state["db"].expire_all()
    state["request_statements"] = statements
    if unchanged:
        assert rows(state["db"]) == before
        assert {sql.lstrip().split(None, 1)[0].upper() for sql in statements} <= {"SELECT"}
    return response


@pytest.mark.parametrize(
    "path,labels",
    (
        ("", {"due", "expired", "future", "revoked", "unscheduled"}),
        ("/rotation-due", {"due", "expired"}),
        ("/expiring", {"due", "expired"}),
    ),
)
def test_collections_include_only_current_workspace_credentials(credentials, path, labels):
    state = credentials
    response = request(state, "GET", "/api/credentials" + path)
    assert response.status_code == 200
    actual = response.json()["credentials"]
    assert {row["id"] for row in actual} == {
        state["records"][state["own"].id, label].id for label in labels
    }
    assert all(row["workspace_id"] == state["own"].id for row in actual)
    assert all(set(row) == PUBLIC_FIELDS for row in actual)
    assert not any(value in response.text for value in state["values"])


def payload(state, value=None, label="created"):
    return {
        "source_type": f"{state['suffix']}-{label}",
        "credential_type": "synthetic",
        "value": secrets.token_urlsafe(32) if value is None else value,
    }


def unchanged_except(before, after, credential_id):
    before = {table: dict(items) for table, items in before.items()}
    after = {table: dict(items) for table, items in after.items()}
    before["credential_store"].pop(credential_id, None)
    after["credential_store"].pop(credential_id, None)
    assert after == before, "Unrelated persisted columns changed"


def stored_columns(row):
    return {column.name: getattr(row, column.name) for column in CredentialStore.__table__.columns}


def test_create_is_encrypted_scoped_and_committed(credentials):
    state = credentials
    before = rows(state["db"])
    body = payload(state)
    response = request(state, "POST", "/api/credentials", json=body, unchanged=False)
    assert response.status_code == 200
    public = response.json()
    assert set(public) == PUBLIC_FIELDS
    assert public["workspace_id"] == state["own"].id
    assert public["source_type"] == body["source_type"]
    assert public["status"] == "active"
    row = state["db"].get(CredentialStore, public["id"])
    assert digest(row.encrypted_value) != digest(body["value"])
    assert digest(decrypt(row.encrypted_value)) == digest(body["value"])
    plaintext_exposed = body["value"] in response.text
    assert not plaintext_exposed, "Credential plaintext leaked"
    assert row.metadata_json is None
    unchanged_except(before, rows(state["db"]), row.id)
    # A separate session sees the HTTP commit, not only an ORM identity map.
    with Session(state["engine"]) as fresh:
        assert rows(fresh) == rows(state["db"])


@pytest.mark.parametrize("replace_options", (False, True))
def test_update_reactivates_only_own_matching_record(credentials, replace_options):
    state = credentials
    row = state["records"][state["own"].id, "revoked"]
    before = rows(state["db"])
    columns = stored_columns(row)
    body = payload(state, label="revoked")
    if replace_options:
        body.update(
            rotation_interval_days=17, expires_at=(state["now"] + timedelta(days=17)).isoformat()
        )
    response = request(state, "POST", "/api/credentials", json=body, unchanged=False)
    assert response.status_code == 200
    assert response.json()["id"] == row.id
    assert set(response.json()) == PUBLIC_FIELDS
    assert row.status == "active"
    assert digest(row.encrypted_value) != digest(columns["encrypted_value"])
    assert digest(decrypt(row.encrypted_value)) == digest(body["value"])
    plaintext_exposed = body["value"] in response.text
    assert not plaintext_exposed, "Credential plaintext leaked"
    assert row.last_rotated_at.replace(tzinfo=None) > columns["last_rotated_at"].replace(
        tzinfo=None
    )
    allowed = {"encrypted_value", "last_rotated_at", "status", "updated_at"}
    if replace_options:
        allowed |= {"rotation_interval_days", "expires_at"}
        assert row.rotation_interval_days == 17
        assert row.expires_at.replace(tzinfo=None) == (state["now"] + timedelta(days=17)).replace(
            tzinfo=None
        )
    assert digest({k: v for k, v in stored_columns(row).items() if k not in allowed}) == digest(
        {k: v for k, v in columns.items() if k not in allowed}
    )
    unchanged_except(before, rows(state["db"]), row.id)


def test_revoke_preserves_ciphertext_and_other_workspace(credentials):
    state = credentials
    row = state["records"][state["own"].id, "due"]
    before = rows(state["db"])
    columns = stored_columns(row)
    response = request(
        state, "DELETE", f"/api/credentials/{row.source_type}/synthetic", unchanged=False
    )
    assert response.status_code == 200 and response.json() == {"revoked": True}
    assert row.status == "revoked"
    assert digest(
        {k: v for k, v in stored_columns(row).items() if k not in {"status", "updated_at"}}
    ) == digest({k: v for k, v in columns.items() if k not in {"status", "updated_at"}})
    unchanged_except(before, rows(state["db"]), row.id)


@pytest.mark.parametrize("target", ("foreign-only", "missing"))
def test_foreign_or_missing_revoke_is_neutral_and_read_only(credentials, target):
    state = credentials
    response = request(state, "DELETE", f"/api/credentials/{state['suffix']}-{target}/synthetic")
    assert response.status_code == 404
    assert response.json() == {"detail": "Credential not found"}


@pytest.mark.parametrize("value", ("", "   "))
def test_empty_store_preserves_every_row(credentials, value):
    response = request(credentials, "POST", "/api/credentials", json=payload(credentials, value))
    assert response.status_code == 400


@pytest.mark.parametrize("days", (0, 91))
def test_invalid_expiry_window_is_read_only(credentials, days):
    response = request(credentials, "GET", f"/api/credentials/expiring?days={days}")
    assert response.status_code == 422


ENDPOINTS = ("list", "rotation", "expiring", "store", "revoke")


def invoke(state, endpoint, *, unchanged=True):
    if endpoint == "store":
        return request(state, "POST", "/api/credentials", json=payload(state), unchanged=unchanged)
    if endpoint == "revoke":
        return request(
            state,
            "DELETE",
            f"/api/credentials/{state['suffix']}-due/synthetic",
            unchanged=unchanged,
        )
    path = {"list": "", "rotation": "/rotation-due", "expiring": "/expiring"}[endpoint]
    return request(state, "GET", "/api/credentials" + path)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_current_custom_admin_grant_authorizes_existing_operations(credentials, endpoint):
    state = credentials
    state["member"].role = "credential-manager"
    state["db"].commit()
    response = invoke(state, endpoint, unchanged=endpoint not in {"store", "revoke"})
    assert response.status_code == 200
    if endpoint in {"list", "rotation", "expiring"}:
        assert all(row["workspace_id"] == state["own"].id for row in response.json()["credentials"])


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize(
    "authority,status",
    (
        ("anonymous", 401),
        ("expired", 401),
        ("revoked", 401),
        ("editor", 403),
        ("reviewer", 403),
        ("suspended", 403),
        ("removed", 403),
        ("missing_workspace", 403),
        ("custom_revoked", 403),
        ("custom_deleted", 403),
        ("custom_foreign_only", 403),
    ),
)
def test_current_authority_denial_never_reads_or_changes_credentials(
    credentials, endpoint, authority, status
):
    state = credentials
    member = state["member"]
    if authority == "anonymous":
        state["client"].cookies.clear()
    elif authority == "expired":
        state["cookie"](max_age_seconds=-1)
    elif authority == "revoked":
        state["db"].delete(state["sid"])
    elif authority in {"editor", "reviewer"}:
        member.role = authority
    elif authority == "suspended":
        member.suspended = True
    elif authority == "removed":
        state["db"].delete(member)
    elif authority == "missing_workspace":
        state["db"].delete(state["own"])
    else:
        member.role = "credential-manager"
        if authority == "custom_revoked":
            state["role"].can_admin = False
        elif authority == "custom_deleted":
            state["db"].delete(state["role"])
        else:
            state["role"].workspace_id = state["foreign"].id
    state["db"].commit()
    response = invoke(state, endpoint)
    assert response.status_code == status
    assert not any(
        "credential_store" in sql.lower() for sql in state["request_statements"]
    ), "Denied request reached credential storage"


@pytest.mark.parametrize("offset_seconds,expected", ((-1, True), (0, True), (1, False)))
def test_rotation_due_boundary_uses_the_stored_instant(
    credentials, monkeypatch, offset_seconds, expected
):
    state = credentials
    fixed = datetime(2026, 3, 4, 12, 0, 0, tzinfo=timezone.utc)
    row = state["records"][state["own"].id, "due"]
    row.last_rotated_at = fixed - timedelta(days=1) + timedelta(seconds=offset_seconds)
    row.rotation_interval_days = 1
    state["db"].commit()

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(service, "datetime", Clock)
    response = request(state, "GET", "/api/credentials/rotation-due")
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["credentials"]}
    assert (row.id in ids) is expected
    assert all(item["workspace_id"] == state["own"].id for item in response.json()["credentials"])


@pytest.mark.parametrize("path", ("", "/rotation-due", "/expiring"))
def test_empty_current_workspace_never_returns_foreign_collection(credentials, path):
    state = credentials
    state["db"].query(CredentialStore).filter(
        CredentialStore.workspace_id == state["own"].id
    ).delete(synchronize_session=False)
    state["db"].commit()
    response = request(state, "GET", "/api/credentials" + path)
    assert response.status_code == 200
    assert response.json() == {"credentials": []}


@pytest.mark.parametrize("offset", (None, 0, 330, -240))
@pytest.mark.parametrize("seconds,expected", ((-1, True), (0, True), (1, False)))
def test_rotation_comparison_preserves_naive_utc_and_aware_instants(
    monkeypatch, offset, seconds, expected
):
    """Compare actual ORM datetime inputs, independent of DB timezone codecs.

    This local service control intentionally retains supplied ORM values;
    the HTTP matrix above separately checks fresh SQLite/PostgreSQL sessions.
    """
    fixed = datetime(2026, 3, 4, 12, 0, 0, tzinfo=timezone.utc)
    rotated = fixed - timedelta(days=1) + timedelta(seconds=seconds)
    rotated = (
        rotated.replace(tzinfo=None)
        if offset is None
        else rotated.astimezone(timezone(timedelta(minutes=offset)))
    )

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(service, "datetime", Clock)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            for model in (Workspace, CredentialStore):
                connection.execute(CreateTable(model.__table__))
        with Session(engine, expire_on_commit=False) as db:
            workspace = Workspace(name="Comparison control", slug="synthetic-comparison")
            db.add(workspace)
            db.flush()
            row = CredentialStore(
                workspace_id=workspace.id,
                source_type="synthetic",
                credential_type="synthetic",
                encrypted_value=encrypt(secrets.token_urlsafe(32)),
                last_rotated_at=rotated,
                rotation_interval_days=1,
                status="active",
            )
            db.add(row)
            db.commit()
            assert row.last_rotated_at is rotated
            before = digest(
                [dict(item) for item in db.execute(select(CredentialStore.__table__)).mappings()]
            )
            result = service.check_rotation_due(db, workspace.id)
            assert (row.id in {item["id"] for item in result}) is expected
            assert (
                digest(
                    [
                        dict(item)
                        for item in db.execute(select(CredentialStore.__table__)).mappings()
                    ]
                )
                == before
            )
            # No timestamp normalization or persistence change is permitted.
            assert row.last_rotated_at is rotated
    finally:
        engine.dispose()
