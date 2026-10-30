"""TC-06-003d: acceptance of existing contract authorization, without a product change.

Stored-auth HTTP against FK-enforced SQLite and migrated PostgreSQL. Successful
ingestion/promise creation require PostgreSQL's actual Deal schema; SQLite never
substitutes that schema. Only get_db is wired to the owned test store.
"""

import hashlib
import json
import secrets

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import contracts, promises, proof_graph
from app.core.database import Base, get_db
from app.core.session import sign_session
from app.models import (
    ApiKey,
    AuditEvent,
    CustomRole,
    User,
    UserMfa,
    UserSession,
    Workspace,
    WorkspaceMember,
)
from app.models.proof_graph import ArtifactIntegrityHash
from app.models.trust_promise import ContractDocument, TrustPromise

MODELS = (
    ArtifactIntegrityHash,
    ContractDocument,
    AuditEvent,
    UserMfa,
    UserSession,
    ApiKey,
    CustomRole,
    WorkspaceMember,
    User,
    Workspace,
)
KINDS = ("contract_document", "contract_documents")
NOT_FOUND = {"detail": "Referenced resource not found"}
CONTENT = "synthetic contract"
CONTENT_HASH = hashlib.sha256(CONTENT.encode()).hexdigest()


def snapshot(store, exclude=None):
    result = {}
    for model in store["models"]:
        query = select(model.__table__).order_by(model.id)
        if exclude and model in exclude:
            query = query.where(model.id.notin_(exclude[model]))
        rows = [list(row) for row in store["db"].execute(query)]
        encoded = json.dumps(rows, default=str).encode()
        result[model.__tablename__] = (len(rows), hashlib.sha256(encoded).hexdigest())
    return result


@pytest.fixture
def contract_store(request):
    backend = request.param
    if backend == "postgres":
        request.getfixturevalue("migrated_db")
        from app.core.database import SessionLocal

        db = SessionLocal()
        engine = db.get_bind()
        assert engine.dialect.name == "postgresql"
        models = (TrustPromise, *MODELS)
    else:
        assert backend == "sqlite"
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        models = MODELS
        Base.metadata.create_all(engine, tables=[model.__table__ for model in models])
        db = Session(engine)
    store = {"db": db, "engine": engine, "models": models}
    original = snapshot(store)
    owned = {model: set() for model in models}
    clients = []

    def add(model, **fields):
        row = model(**fields)
        db.add(row)
        db.flush()
        owned[model].add(row.id)
        return row

    def remember_flushed_rows(current, _context):
        # Capture exact IDs even if a regression writes into the wrong workspace
        # or an HTTP response fails after a flush. No broad tenant cleanup.
        for row in current.new:
            if type(row) in owned:
                owned[type(row)].add(row.id)

    try:
        suffix = secrets.token_hex(8)
        next_ws = int(db.scalar(select(func.max(Workspace.id))) or 0) + 1
        ws = [
            add(Workspace, id=next_ws + i, name="Contract", slug=f"contract-{suffix}-{i}").id
            for i in range(2)
        ]
        users = [
            add(User, email=f"contract-{suffix}-{i}@example.com", password_hash="unused").id
            for i in range(2)
        ]
        member = add(WorkspaceMember, workspace_id=ws[0], user_id=users[0], role="admin")
        add(WorkspaceMember, workspace_id=ws[1], user_id=users[1], role="admin")
        add(
            CustomRole,
            workspace_id=ws[0],
            name="session_only",
            can_admin=False,
            can_review=False,
            can_edit=False,
            can_export=False,
        )
        sid = secrets.token_hex(24)
        session = add(UserSession, user_id=users[0], session_id=sid)
        documents = {}
        for target in ("own", "archived_status", "foreign", "moved", "deleted"):
            row = add(
                ContractDocument,
                workspace_id=ws[1] if target == "foreign" else ws[0],
                title=f"Synthetic {target}",
                clauses_json='[{"text":"synthetic private clause"}]',
                status="archived" if target == "archived_status" else "ready",
                uploaded_by_user_id=users[0],
            )
            documents[target] = row.id
            if target == "moved":
                row.workspace_id = ws[1]
            elif target == "deleted":
                db.delete(row)
        documents["missing"] = 2147483647
        db.commit()
        app = FastAPI()
        for router in (contracts.router, promises.router, proof_graph.router):
            app.include_router(router, prefix="/api")

        def database():
            with Session(engine) as current:
                event.listen(current, "after_flush", remember_flushed_rows)
                yield current

        app.dependency_overrides[get_db] = database
        client, public = TestClient(app), TestClient(app)
        clients.extend([client, public])
        client.cookies.set(
            "tc_session",
            sign_session(
                users[0],
                f"contract-{suffix}-0@example.com",
                ws[0],
                "admin",
                session_id=sid,
                max_age_seconds=3600,
            ),
        )
        store.update(
            client=client,
            public=public,
            ws=ws,
            users=users,
            member=member,
            session=session,
            documents=documents,
            add=add,
        )
        yield store
    finally:
        for client in clients:
            client.close()
        db.rollback()
        try:
            for model in models:
                if owned[model]:
                    db.query(model).filter(model.id.in_(owned[model])).delete(
                        synchronize_session=False
                    )
            db.commit()
            assert snapshot(store) == original
        finally:
            db.close()
            if backend == "sqlite":
                engine.dispose()


SHARED_STORES = (
    pytest.param("sqlite", marks=pytest.mark.unit),
    pytest.param("postgres", marks=pytest.mark.integration),
)


def unchanged_request(store, method, path, status, *, body=None, anonymous=False):
    before = snapshot(store)
    writes = []

    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(store["engine"], "before_cursor_execute", observe)
    try:
        client = store["public"] if anonymous else store["client"]
        if anonymous:
            assert not client.cookies
        response = client.request(method, path, **({"json": body} if body is not None else {}))
    finally:
        event.remove(store["engine"], "before_cursor_execute", observe)
    assert response.status_code == status
    assert not writes, "Read/denial must not write SQL, even if later rolled back"
    assert snapshot(store) == before
    assert not store["db"].new and not store["db"].dirty and not store["db"].deleted
    if status == 404:
        assert response.json() == NOT_FOUND
    return response.json()


@pytest.mark.parametrize("contract_store", SHARED_STORES, indirect=True)
class TestContractAuthorization:
    @pytest.mark.parametrize("role", ["admin", "editor", "reviewer", "session_only"])
    def test_list_uses_current_workspace_and_preserves_status_visibility(
        self, contract_store, role
    ):
        s = contract_store
        s["member"].role = role  # Cookie remains admin; stored authority is current.
        s["db"].commit()
        body = unchanged_request(
            s,
            "GET",
            f'/api/contracts?workspace_id={s["ws"][1]}&document_id={s["documents"]["foreign"]}',
            200,
        )
        rows = {row["id"]: row for row in body["documents"]}
        assert set(rows) == {s["documents"]["own"], s["documents"]["archived_status"]}
        assert rows[s["documents"]["own"]]["clause_count"] == 1
        assert rows[s["documents"]["archived_status"]]["status"] == "archived"
        assert all(row["created_at"] for row in rows.values())

    def test_list_excludes_foreign_and_moved_rows_before_clause_decoding(self, contract_store):
        s = contract_store
        for target in ("foreign", "moved"):
            s["db"].get(ContractDocument, s["documents"][target]).clauses_json = "invalid JSON"
        s["db"].commit()
        body = unchanged_request(s, "GET", "/api/contracts", 200)
        assert {row["id"] for row in body["documents"]} == {
            s["documents"]["own"],
            s["documents"]["archived_status"],
        }

    @pytest.mark.parametrize("role", ["editor", "reviewer", "session_only"])
    def test_ingestion_requires_current_admin_permission(self, contract_store, role):
        s = contract_store
        s["member"].role = role
        s["db"].commit()
        unchanged_request(s, "POST", "/api/contracts/ingest", 403, body={"title": "Denied"})

    @pytest.mark.parametrize("target", ["foreign", "moved", "deleted", "missing"])
    def test_contract_backed_promise_requires_current_reference(self, contract_store, target):
        s = contract_store
        unchanged_request(
            s,
            "POST",
            "/api/promises",
            404,
            body={
                "promise_text": "Synthetic",
                "source_type": "contract_clause",
                "source_ref_id": s["documents"][target],
            },
        )

    @pytest.mark.parametrize("target", ["foreign", "moved", "deleted", "missing"])
    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("action", ["hash", "verify"])
    def test_contract_hash_aliases_require_current_reference(
        self, contract_store, target, kind, action
    ):
        s = contract_store
        unchanged_request(
            s,
            "POST",
            f"/api/proof-graph/artifacts/{action}",
            404,
            body={
                "artifact_kind": kind,
                "artifact_id": s["documents"][target],
                "content_text": CONTENT,
            },
        )

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("action", ["hash", "verify"])
    def test_owned_contract_hash_aliases_preserve_success(self, contract_store, kind, action):
        s = contract_store
        body = {
            "artifact_kind": kind,
            "artifact_id": s["documents"]["own"],
            "content_text": CONTENT,
        }
        if action == "verify":
            s["add"](
                ArtifactIntegrityHash,
                workspace_id=s["ws"][0],
                artifact_kind=kind,
                artifact_id=s["documents"]["own"],
                sha256_hex=CONTENT_HASH,
                recorded_by_user_id=s["users"][0],
            )
            s["db"].commit()
            result = unchanged_request(
                s, "POST", "/api/proof-graph/artifacts/verify", 200, body=body
            )
            assert result == {
                "ok": True,
                "recorded_sha256": CONTENT_HASH,
                "computed_sha256": CONTENT_HASH,
            }
        else:
            before = snapshot(s)
            response = s["client"].post("/api/proof-graph/artifacts/hash", json=body)
            assert response.status_code == 200
            result = response.json()
            row = s["db"].get(ArtifactIntegrityHash, result["id"])
            assert row.workspace_id == s["ws"][0] and row.recorded_by_user_id == s["users"][0]
            assert row.artifact_kind == kind and row.artifact_id == s["documents"]["own"]
            assert row.sha256_hex == result["sha256_hex"] == CONTENT_HASH
            assert snapshot(s, {ArtifactIntegrityHash: [row.id]}) == before

    @pytest.mark.parametrize("revocation", ["suspended", "membership_removed", "session_removed"])
    @pytest.mark.parametrize("action", ["list", "ingest"])
    def test_current_authority_loss_preserves_contract_rows(
        self, contract_store, revocation, action
    ):
        s = contract_store
        if revocation == "suspended":
            s["member"].suspended = True
        else:
            s["db"].delete(s["session"] if revocation == "session_removed" else s["member"])
        s["db"].commit()
        unchanged_request(
            s,
            "GET" if action == "list" else "POST",
            "/api/contracts" if action == "list" else "/api/contracts/ingest",
            401 if revocation == "session_removed" else 403,
            body=None if action == "list" else {"title": "Denied"},
        )

    @pytest.mark.parametrize("action", ["list", "ingest"])
    def test_contracts_are_not_anonymous_capabilities(self, contract_store, action):
        unchanged_request(
            contract_store,
            "GET" if action == "list" else "POST",
            "/api/contracts" if action == "list" else "/api/contracts/ingest",
            401,
            body=None if action == "list" else {"title": "Denied"},
            anonymous=True,
        )


@pytest.mark.integration
@pytest.mark.parametrize("contract_store", ["postgres"], indirect=True)
@pytest.mark.parametrize("variant", ["default", "three_clauses", "forged_scope"])
def test_postgres_ingestion_owns_document_and_all_generated_promises(contract_store, variant):
    s = contract_store
    body = {"title": "Synthetic MSA"}
    if variant == "three_clauses":
        body.update(
            body_text="90 day retention. Breach notification. AES encryption.",
            original_filename="synthetic-msa.txt",
        )
    elif variant == "forged_scope":
        body.update(
            workspace_id=s["ws"][1],
            uploaded_by_user_id=s["users"][1],
            document_id=s["documents"]["foreign"],
        )
    before = snapshot(s)
    response = s["client"].post("/api/contracts/ingest", json=body)
    assert response.status_code == 200
    result = response.json()
    doc = s["db"].get(ContractDocument, result["document_id"])
    assert doc.workspace_id == s["ws"][0] and doc.uploaded_by_user_id == s["users"][0]
    assert doc.title == body["title"] and doc.status == "ready"
    assert doc.original_filename == body.get("original_filename")
    clauses = json.loads(doc.clauses_json)
    assert clauses == result["clauses"]
    assert len(clauses) == (3 if variant == "three_clauses" else 1)
    ids = result["promise_ids"]
    assert len(ids) == len(set(ids)) == len(clauses)
    rows = s["db"].query(TrustPromise).filter(TrustPromise.contract_document_id == doc.id).all()
    assert {row.id for row in rows} == set(ids)
    assert {row.promise_text for row in rows} == {clause["text"] for clause in clauses}
    for row in rows:
        assert row.workspace_id == s["ws"][0] and row.owner_user_id == s["users"][0]
        assert row.source_type == "contract_clause" and row.source_ref_id == doc.id
        assert row.status == "active" and row.expires_at and row.review_at
    assert snapshot(s, {ContractDocument: [doc.id], TrustPromise: ids}) == before


@pytest.mark.integration
@pytest.mark.parametrize("contract_store", ["postgres"], indirect=True)
def test_postgres_owned_contract_reference_creates_owned_promise(contract_store):
    s = contract_store
    before = snapshot(s)
    response = s["client"].post(
        "/api/promises",
        json={
            "promise_text": "Synthetic commitment",
            "source_type": "contract_clause",
            "source_ref_id": s["documents"]["own"],
        },
    )
    assert response.status_code == 200
    row = s["db"].get(TrustPromise, response.json()["id"])
    assert row.workspace_id == s["ws"][0] and row.owner_user_id == s["users"][0]
    assert row.source_ref_id == s["documents"]["own"] and row.source_type == "contract_clause"
    assert row.promise_text == "Synthetic commitment" and row.status == "active"
    assert snapshot(s, {TrustPromise: [row.id]}) == before
