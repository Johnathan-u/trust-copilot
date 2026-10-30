"""Current document provenance for retrieval; SQLite controls and real PostgreSQL.

No auth, provider, SQL or pgvector mocks. Only get_db is wired to the owned store.
"""

import hashlib
import json
import secrets
from contextlib import contextmanager
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.search import router
from app.core.config import get_settings
from app.core.database import Base, get_db
from app.core.session import sign_session
from app.models import (
    AIGovernanceSettings,
    ApiKey,
    AuditEvent,
    Chunk,
    CustomRole,
    Document,
    Framework,
    FrameworkControl,
    Question,
    Questionnaire,
    QuestionMappingPreference,
    Tag,
    User,
    UserMfa,
    UserSession,
    Workspace,
    WorkspaceControl,
    WorkspaceMember,
)
from app.services import retrieval

# All tables touched by the fixture, current auth, or empty mapping lookup, in
# FK-safe cleanup order. Hash all columns and count all rows, including outsiders.
MODELS = (
    Chunk,
    QuestionMappingPreference,
    Question,
    Questionnaire,
    Document,
    WorkspaceControl,
    FrameworkControl,
    Framework,
    Tag,
    AIGovernanceSettings,
    AuditEvent,
    UserMfa,
    UserSession,
    ApiKey,
    CustomRole,
    WorkspaceMember,
    User,
    Workspace,
)
BACKENDS = (
    pytest.param("sqlite", marks=pytest.mark.unit),
    pytest.param("postgres", marks=pytest.mark.integration),
)
QUERY = "provenance"


def embedding(first=1.0, second=0.0):
    return [first, second] + [0.0] * 1534


def snapshot(db):
    def serialize(value):
        if hasattr(value, "tolist"):
            return value.tolist()
        if hasattr(value, "isoformat"):
            return value.isoformat()
        raise TypeError(type(value).__name__)

    result = {}
    for model in MODELS:
        rows = [list(row) for row in db.execute(select(model.__table__).order_by(model.id))]
        encoded = json.dumps(rows, default=serialize, sort_keys=True).encode()
        result[model.__tablename__] = (len(rows), hashlib.sha256(encoded).hexdigest())
    return result


@contextmanager
def read_only(db):
    before = snapshot(db)
    yield
    assert not db.new and not db.dirty and not db.deleted
    assert snapshot(db) == before


@contextmanager
def stored_retrieval(request, backend):
    if backend == "postgres":
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
    before = snapshot(db)
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
        # The migrated fixture seeds explicit workspace ids; do not reset sequences.
        next_ws = int(db.scalar(select(func.max(Workspace.id))) or 0) + 1
        ws = [
            add(Workspace, id=next_ws + i, name="Retrieval", slug=f"retrieval-{suffix}-{i}")
            for i in range(2)
        ]
        user = add(User, email=f"retrieval-{suffix}@example.com", password_hash="unused")
        member = add(WorkspaceMember, workspace_id=ws[0].id, user_id=user.id, role="reviewer")
        sid = f"retrieval-{suffix}"
        session = add(UserSession, user_id=user.id, session_id=sid)
        docs = {}
        for name in ("own", "second", "spoof", "foreign", "archived", "moved", "deleted"):
            docs[name] = add(
                Document,
                workspace_id=ws[1].id if name == "foreign" else ws[0].id,
                storage_key=f"synthetic/{suffix}/{name}",
                filename=f"{name}.txt",
                deleted_at=datetime(2026, 1, 1) if name == "archived" else None,
            )
        chunks = {}
        # Ineligible candidates precede positives and have higher vector similarity.
        for name in (
            "foreign",
            "archived",
            "moved",
            "parentless",
            "other",
            "deleted",
            "own",
            "second",
            "spoof",
        ):
            parent = docs["foreign"] if name == "other" else docs.get(name)
            score = {"own": (0.8, 0.6), "second": (0.6, 0.8), "spoof": (0.0, 1.0)}.get(
                name, (1.0, 0.0)
            )
            chunks[name] = add(
                Chunk,
                workspace_id=ws[1].id if name == "other" else ws[0].id,
                document_id=parent.id if parent else None,
                text=f"{QUERY} training {name}",
                metadata_={"document_id": docs["foreign" if name == "spoof" else "own"].id},
                embedding=embedding(*score),
            )
        docs["moved"].workspace_id = ws[1].id
        deleted_chunk = chunks["deleted"].id
        db.delete(docs["deleted"])
        db.commit()
        assert db.scalar(select(Chunk.id).where(Chunk.id == deleted_chunk)) is None
        assert not get_settings().openai_api_key  # HTTP exercises real no-key embedding path.
        app = FastAPI()
        app.include_router(router, prefix="/api")

        def database():
            with Session(engine) as current:
                yield current

        app.dependency_overrides[get_db] = database
        client = TestClient(app)
        client.cookies.set(
            "tc_session",
            sign_session(
                user.id, user.email, ws[0].id, "reviewer", session_id=sid, max_age_seconds=3600
            ),
        )
        yield dict(
            db=db,
            svc=retrieval.RetrievalService(db),
            client=client,
            ws=[item.id for item in ws],
            docs=docs,
            chunks=chunks,
            member=member,
            session=session,
        )
    finally:
        if client:
            client.close()
        db.rollback()
        try:
            for model in MODELS:
                if owned[model]:
                    db.query(model).filter(model.id.in_(owned[model])).delete(
                        synchronize_session=False
                    )
            db.commit()
            assert snapshot(db) == before
        finally:
            db.close()
            if backend == "sqlite":
                engine.dispose()


@pytest.fixture(params=BACKENDS)
def store(request):
    with stored_retrieval(request, request.param) as state:
        yield state


@pytest.fixture
def vector_store(request, monkeypatch):
    monkeypatch.setenv("USE_PGVECTOR_INDEX", "1")
    get_settings.cache_clear()
    assert get_settings().use_pgvector_index
    with stored_retrieval(request, "postgres") as state:
        yield state
    get_settings.cache_clear()


def run(state, method, scope=None, limit=20):
    svc, ws = state["svc"], state["ws"][0]
    if method.startswith("keyword"):
        query = "training" if method == "keyword_rare" else QUERY
        return svc._keyword_search(ws, query, limit, scope)
    if method in ("fallback", "vector"):
        fn = (
            svc._semantic_search_fallback if method == "fallback" else svc._semantic_search_pgvector
        )
        return fn(ws, embedding(), limit, 0.0, scope)
    if method in ("search", "vector_search"):
        return svc.search(
            ws,
            QUERY,
            limit=limit,
            query_embedding=embedding() if method == "vector_search" else None,
            document_ids=list(scope) if scope else None,
        )
    batches = svc.batch_search(
        ws,
        [(QUERY, embedding() if method == "vector_batch" else None), ("training", None)],
        limit=limit,
        document_ids=list(scope) if scope else None,
    )
    assert {row["id"] for row in batches[0]} == {row["id"] for row in batches[1]}
    return batches[0]


def ids(rows):
    return {row["id"] for row in rows}


def expected(state):
    return {state["chunks"][name].id for name in ("own", "second", "spoof")}


def scope_case(state, case):
    docs = state["docs"]
    if case == "own":
        return frozenset([docs["own"].id]), {state["chunks"]["own"].id}
    if case == "mixed":
        return frozenset(docs[name].id for name in ("own", "foreign", "archived", "moved")), {
            state["chunks"]["own"].id
        }
    return frozenset([docs["foreign"].id if case == "foreign" else 2147483647]), set()


@pytest.mark.parametrize("method", ["keyword", "keyword_rare", "fallback", "search", "batch"])
def test_all_paths_require_current_parent(store, method):
    with read_only(store["db"]):
        rows = run(store, method)
        assert ids(rows) == expected(store)
        assert all(set(row) == {"id", "text", "metadata", "score"} for row in rows)
        spoof = next(row for row in rows if row["id"] == store["chunks"]["spoof"].id)
        assert spoof["metadata"]["document_id"] == store["docs"]["foreign"].id
        # Existing metadata projection does not become the eligibility authority.


@pytest.mark.parametrize("method", ["keyword", "fallback", "search", "batch"])
@pytest.mark.parametrize("scope_name", ["own", "foreign", "mixed", "missing"])
def test_explicit_document_scope_cannot_grant_access(store, method, scope_name):
    scope, authorized = scope_case(store, scope_name)
    with read_only(store["db"]):
        assert ids(run(store, method, scope)) == authorized


def isolate_positive(state):
    # Exactly one eligible match: cap checks cannot rely on eligible SQL row order.
    for name in ("second", "spoof"):
        state["chunks"][name].text = "unmatched"
        state["chunks"][name].embedding = None
    state["db"].commit()


@pytest.mark.parametrize("method", ["keyword", "fallback"])
def test_parent_filter_precedes_candidate_limit(store, method, monkeypatch):
    isolate_positive(store)
    monkeypatch.setattr(retrieval, "FALLBACK_MAX_CHUNKS", 2)
    with read_only(store["db"]):
        assert ids(run(store, method, limit=1)) == {store["chunks"]["own"].id}


@pytest.mark.parametrize("method", ["keyword", "fallback", "search"])
@pytest.mark.parametrize("transition", ["archive", "move"])
def test_existing_parent_state_is_rechecked(store, method, transition):
    with read_only(store["db"]):
        assert ids(run(store, method)) == expected(store)
    doc = store["docs"]["own"]
    if transition == "archive":
        doc.deleted_at = datetime(2026, 2, 1)
    else:
        doc.workspace_id = store["ws"][1]
    store["db"].commit()
    with read_only(store["db"]):
        assert ids(run(store, method)) == expected(store) - {store["chunks"]["own"].id}


def test_http_uses_stored_session_and_current_membership(store):
    client, db = store["client"], store["db"]
    params = {"workspace_id": store["ws"][0], "q": QUERY, "limit": 50}
    for path in ("/api/search", "/api/search/"):
        with read_only(db):
            response = client.get(path, params=params, follow_redirects=False)
            assert response.status_code == 200, response.text
            assert ids(response.json()["results"]) == expected(store)
    with read_only(db):
        response = client.get("/api/search", params={**params, "workspace_id": store["ws"][1]})
        assert response.status_code == 403
        assert "results" not in response.json()
    store["member"].suspended = True
    db.commit()
    with read_only(db):
        assert client.get("/api/search", params=params).status_code == 403
    store["member"].suspended = False
    db.delete(store["session"])
    db.commit()
    with read_only(db):
        assert client.get("/api/search", params=params).status_code == 401


@pytest.mark.integration
def test_pgvector_current_parent_and_known_scores(vector_store):
    with read_only(vector_store["db"]):
        rows = run(vector_store, "vector")
        assert [row["id"] for row in rows] == [
            vector_store["chunks"][n].id for n in ("own", "second", "spoof")
        ]
        assert [row["score"] for row in rows] == pytest.approx([0.8, 0.6, 0.0], abs=1e-6)


@pytest.mark.integration
@pytest.mark.parametrize("scope_name", ["own", "foreign", "mixed", "missing"])
def test_pgvector_explicit_scope(vector_store, scope_name):
    scope, authorized = scope_case(vector_store, scope_name)
    with read_only(vector_store["db"]):
        assert ids(run(vector_store, "vector", scope)) == authorized


@pytest.mark.integration
def test_pgvector_filters_before_ranking_and_limit(vector_store):
    with read_only(vector_store["db"]):
        assert ids(run(vector_store, "vector", limit=1)) == {vector_store["chunks"]["own"].id}


@pytest.mark.integration
@pytest.mark.parametrize("transition", ["archive", "move"])
def test_pgvector_rechecks_parent(vector_store, transition):
    test_existing_parent_state_is_rechecked(vector_store, "vector", transition)


@pytest.mark.integration
@pytest.mark.parametrize("method", ["vector_search", "vector_batch"])
def test_pgvector_hybrid_and_batch(vector_store, method):
    with read_only(vector_store["db"]):
        assert ids(run(vector_store, method)) == expected(vector_store)


@pytest.mark.integration
def test_pgvector_preserves_minimum_score(vector_store):
    with read_only(vector_store["db"]):
        rows = vector_store["svc"]._semantic_search_pgvector(
            vector_store["ws"][0], embedding(), 20, 0.7, None
        )
        assert ids(rows) == {vector_store["chunks"]["own"].id}
