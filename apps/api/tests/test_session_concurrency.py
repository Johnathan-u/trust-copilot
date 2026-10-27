"""TC-08-005: no SQLAlchemy Session is shared across worker threads.

AC1: each concurrent request/task has an isolated Session lifecycle and bounded pool usage.
AC2: concurrent two-tenant retrieval completes without transaction corruption or leaked objects.

Synthetic data only; no LLM / network calls (retrieval is DB-only, embeddings are hand-built).
Requires Postgres with pgvector (skips when unavailable).

Location note: the ticket proposes tests/release/test_session_concurrency.py; per Coordinator
ruling Q3 (TC-02-001 owns the release-test tree) this file lives in tests/ for now.
"""

from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

pytestmark = pytest.mark.integration

DIM = 1536
TERMS = ["encryption", "retention", "incident", "access", "backup", "logging"]


def _vec(hot: int) -> list[float]:
    v = [0.001] * DIM
    v[hot % DIM] = 1.0
    return v


@pytest.fixture(scope="module")
def pg_ready() -> bool:
    from tests.conftest import _ensure_db_schema

    if not _ensure_db_schema():
        pytest.skip("Postgres not available")
    return True


@pytest.fixture(scope="module")
def two_tenants(pg_ready) -> Iterator[dict]:
    """Two synthetic workspaces, each with one document and chunks sharing the same vocabulary."""
    from app.core.database import SessionLocal
    from app.models import Chunk, Document, Workspace

    tag = uuid.uuid4().hex[:8]
    db = SessionLocal()
    tenants: dict = {}
    try:
        # Seed rows in some migrations use explicit ids; make sure sequences are past them.
        for tbl in ("workspaces", "documents", "chunks"):
            db.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence('{tbl}', 'id'), "
                    f"GREATEST((SELECT COALESCE(MAX(id), 0) FROM {tbl}), 1))"
                )
            )
        for name in ("a", "b"):
            ws = Workspace(name=f"tc08005-{name}-{tag}", slug=f"tc08005-{name}-{tag}")
            db.add(ws)
            db.flush()
            doc = Document(
                workspace_id=ws.id,
                storage_key=f"synthetic/{tag}/{name}.txt",
                filename=f"{name}.txt",
            )
            db.add(doc)
            db.flush()
            ids = []
            for i, term in enumerate(TERMS):
                c = Chunk(
                    workspace_id=ws.id,
                    document_id=doc.id,
                    text=f"Synthetic tenant {name} policy about {term} controls number {i}.",
                    metadata_={"synthetic": True, "tenant": name},
                    embedding=_vec(
                        i
                    ),  # identical vectors across tenants -> isolation must come from filters
                )
                db.add(c)
                db.flush()
                ids.append(c.id)
            tenants[name] = {"ws": ws.id, "doc": doc.id, "chunks": set(ids)}
        db.commit()
        yield tenants
    finally:
        db.rollback()
        for t in tenants.values():
            db.execute(text("DELETE FROM chunks WHERE workspace_id = :w"), {"w": t["ws"]})
            db.execute(text("DELETE FROM documents WHERE workspace_id = :w"), {"w": t["ws"]})
            db.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": t["ws"]})
        db.commit()
        db.close()


def _queries(n: int = 12) -> list[tuple[str, list[float] | None]]:
    return [
        (f"What {TERMS[i % len(TERMS)]} controls exist?", _vec(i % len(TERMS))) for i in range(n)
    ]


class _SessionSpy:
    """Record which Session / thread executes each retrieval primitive."""

    def __init__(self, monkeypatch):
        from app.services.retrieval import RetrievalService

        self.calls: list[tuple[int, Session]] = []
        self._lock = threading.Lock()
        for name in ("_keyword_search", "_semantic_search"):
            orig = getattr(RetrievalService, name)

            def wrapper(svc, *a, __orig=orig, **kw):
                with self._lock:
                    self.calls.append((threading.get_ident(), svc._db))
                return __orig(svc, *a, **kw)

            monkeypatch.setattr(RetrievalService, name, wrapper)


class _PoolMeter:
    def __init__(self, engine):
        self.engine = engine
        self.out = 0
        self.peak = 0
        self._lock = threading.Lock()
        event.listen(engine, "checkout", self._co)
        event.listen(engine, "checkin", self._ci)

    def _co(self, *a):
        with self._lock:
            self.out += 1
            self.peak = max(self.peak, self.out)

    def _ci(self, *a):
        with self._lock:
            self.out -= 1

    def close(self):
        event.remove(self.engine, "checkout", self._co)
        event.remove(self.engine, "checkin", self._ci)


@pytest.fixture(params=["pgvector", "fallback"])
def search_mode(request, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("USE_PGVECTOR_INDEX", "1" if request.param == "pgvector" else "0")
    get_settings.cache_clear()
    yield request.param
    get_settings.cache_clear()


# ---------------------------------------------------------------- AC1: isolated lifecycle


def test_batch_search_never_uses_caller_session_off_thread(two_tenants, monkeypatch, search_mode):
    """Regression for the baseline bug: worker threads used the caller's Session."""
    from app.core.database import SessionLocal
    from app.services.retrieval import RetrievalService

    spy = _SessionSpy(monkeypatch)
    main = threading.get_ident()
    caller = SessionLocal()
    try:
        out = RetrievalService(caller).batch_search(two_tenants["a"]["ws"], _queries(12), limit=5)
        assert len(out) == 12 and all(out)
        worker_calls = [(t, s) for t, s in spy.calls if t != main]
        assert worker_calls, "expected parallel execution on a pooled engine"
        assert all(
            s is not caller for _, s in spy.calls
        ), "caller Session used inside worker thread"
        # each task session is used by exactly one thread, and is closed afterwards
        owners: dict[int, set[int]] = {}
        for t, s in spy.calls:
            owners.setdefault(id(s), set()).add(t)
        assert all(len(ts) == 1 for ts in owners.values())
        task_sessions = {id(s): s for _, s in spy.calls}.values()
        assert len(task_sessions) == 12  # one Session per task
        for s in task_sessions:
            assert not s.in_transaction() and len(s.identity_map) == 0
        assert len(caller.identity_map) == 0  # no ORM objects leaked into the caller
    finally:
        caller.close()


def test_pool_usage_bounded_and_returned(two_tenants, monkeypatch):
    from app.core.config import get_settings
    from app.core.database import SessionLocal, engine
    from app.services.retrieval import RetrievalService

    monkeypatch.setenv("RETRIEVAL_MAX_THREADS", "3")
    get_settings.cache_clear()
    baseline = engine.pool.checkedout()
    meter = _PoolMeter(engine)
    caller = SessionLocal()
    try:
        caller.execute(text("SELECT 1"))  # caller holds one connection, like a real request
        RetrievalService(caller).batch_search(two_tenants["a"]["ws"], _queries(16), limit=5)
        assert (
            meter.peak <= 1 + 3
        ), f"pool peak {meter.peak} exceeded caller + RETRIEVAL_MAX_THREADS"
        caller.close()
        assert engine.pool.checkedout() == baseline
    finally:
        meter.close()
        caller.close()
        get_settings.cache_clear()


def test_pool_thread_budget_respects_pool_capacity():
    from app.core.database import pool_thread_budget, supports_thread_isolation

    small = create_engine(os.environ["DATABASE_URL"], pool_size=2, max_overflow=1)
    try:
        assert supports_thread_isolation(small)
        assert pool_thread_budget(small, 8) == 2  # 2 + 1 - 1 reserved for caller
        assert pool_thread_budget(small, 1) == 1
    finally:
        small.dispose()
    sqlite = create_engine("sqlite://", poolclass=StaticPool)
    assert not supports_thread_isolation(sqlite)
    assert pool_thread_budget(sqlite, 8) == 1


def test_isolated_session_rejects_shared_connection(pg_ready):
    from app.core.database import engine, isolated_session, supports_thread_isolation

    with engine.connect() as conn:
        assert not supports_thread_isolation(conn)
        with pytest.raises(ValueError):
            with isolated_session(conn):
                pass


def test_connection_bound_session_runs_serially_on_caller_thread(two_tenants, monkeypatch):
    """A Session bound to a Connection (outer transaction) must not be fanned out to threads."""
    from app.core.database import engine
    from app.models import Chunk
    from app.services.retrieval import RetrievalService

    spy = _SessionSpy(monkeypatch)
    main = threading.get_ident()
    with engine.connect() as conn:
        trans = conn.begin()
        s = Session(bind=conn)
        try:
            ws = two_tenants["b"]["ws"]
            c = Chunk(
                workspace_id=ws,
                document_id=two_tenants["b"]["doc"],
                text="Uncommitted synthetic zebrafish note",
                embedding=_vec(99),
            )
            s.add(c)
            s.flush()
            out = RetrievalService(s).batch_search(
                ws, [("zebrafish note", None), ("encryption", _vec(0))], limit=5
            )
            assert c.id in {r["id"] for r in out[0]}  # sees caller's uncommitted state
            assert {t for t, _ in spy.calls} == {main}
            assert all(x is s for _, x in spy.calls)
        finally:
            s.close()
            trans.rollback()


def test_task_failure_releases_sessions_and_keeps_caller_usable(two_tenants, monkeypatch):
    from app.core.database import SessionLocal, engine
    from app.services.retrieval import RetrievalService

    orig = RetrievalService._keyword_search
    seen: list[Session] = []

    def flaky(svc, workspace_id, query, limit, scope):
        seen.append(svc._db)
        if "backup" in query:
            svc._db.execute(text("SELECT * FROM table_that_does_not_exist_tc08005"))
        return orig(svc, workspace_id, query, limit, scope)

    monkeypatch.setattr(RetrievalService, "_keyword_search", flaky)
    baseline = engine.pool.checkedout()
    caller = SessionLocal()
    try:
        with pytest.raises(Exception):
            RetrievalService(caller).batch_search(two_tenants["a"]["ws"], _queries(12), limit=5)
        # caller transaction is not poisoned by the failing task
        assert caller.execute(text("SELECT 1")).scalar() == 1
        assert all(s is not caller for s in seen)
        for s in seen:
            assert not s.in_transaction()
        caller.close()
        assert engine.pool.checkedout() == baseline
    finally:
        caller.close()


# ---------------------------------------------------------------- AC2: two-tenant concurrency


def test_concurrent_two_tenant_retrieval_isolated(two_tenants, search_mode):
    from app.core.database import SessionLocal, engine
    from app.services.retrieval import RetrievalService

    baseline = engine.pool.checkedout()
    errors: list[BaseException] = []
    leaks: list[str] = []
    rounds = 8
    barrier = threading.Barrier(4)

    def tenant_request(name: str) -> None:
        t = two_tenants[name]
        other = two_tenants["b" if name == "a" else "a"]
        try:
            barrier.wait(timeout=30)
            for r in range(rounds):
                db = SessionLocal()  # one Session per simulated request
                try:
                    doc_ids = [t["doc"]] if r % 2 else None
                    out = RetrievalService(db).batch_search(
                        t["ws"], _queries(10), limit=6, document_ids=doc_ids
                    )
                    assert len(out) == 10
                    for res in out:
                        assert res, f"tenant {name} got empty results"
                        for item in res:
                            if item["id"] not in t["chunks"] or item["id"] in other["chunks"]:
                                leaks.append(f"{name}:{item['id']}")
                            md = item.get("metadata") or {}
                            if md.get("document_id") != t["doc"] or md.get("tenant") != name:
                                leaks.append(f"{name}:md:{md}")
                    assert len(db.identity_map) == 0
                    assert db.execute(text("SELECT 1")).scalar() == 1
                finally:
                    db.close()
        except BaseException as e:  # noqa: BLE001 - surface to main thread
            errors.append(e)

    threads = [threading.Thread(target=tenant_request, args=(n,)) for n in ("a", "b", "a", "b")]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=120)
    assert not any(th.is_alive() for th in threads), "retrieval hung"
    assert not errors, errors
    assert not leaks, leaks[:10]
    assert engine.pool.checkedout() == baseline
