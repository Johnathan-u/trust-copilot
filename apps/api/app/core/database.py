"""Database session and engine."""

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv


def utc_now():
    """Return current UTC time (timezone-aware). Use for model defaults instead of datetime.utcnow."""
    return datetime.now(timezone.utc)


# Env load order must match main.py so auth/config see the same env when DB is running.
# When running in Docker, do not load .env so compose env (DATABASE_URL, S3_*) is kept.
# When on host: load apps/api/.env first (override), then repo .env (fill only unset).
_api_root = Path(__file__).resolve().parent.parent
_repo_root = _api_root.parent.parent
_in_docker = Path("/.dockerenv").exists() or os.environ.get("TRUST_COPILOT_IN_DOCKER") == "1"
_in_test = os.environ.get("TRUST_COPILOT_TESTING") == "1"
if not _in_docker and not _in_test:
    load_dotenv(_api_root / ".env", override=True)
    load_dotenv(_repo_root / ".env")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.engine import Connection, Engine  # noqa: E402
from sqlalchemy.orm import Session, declarative_base, sessionmaker  # noqa: E402
from sqlalchemy.pool import NullPool, QueuePool  # noqa: E402

from app.core.config import get_settings  # noqa: E402

settings = get_settings()
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency for FastAPI to get a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def warn_if_database_time_zone_is_not_utc(bind=None) -> None:
    """Log when the session TimeZone is not UTC. Do not refuse to start.

    ``jobs.updated_at`` and ``jobs.started_at`` are timestamps without a time zone. The
    NULL-lease grace compares them to ``now()``, which is only UTC when the session TimeZone is UTC.
    """
    import logging

    from sqlalchemy import text

    target = engine if bind is None else bind
    try:
        with target.connect() as conn:
            zone = conn.execute(text("SHOW TimeZone")).scalar()
    except Exception:
        logging.getLogger(__name__).warning("could not read database TimeZone", exc_info=True)
        return
    if str(zone) not in {"UTC", "Etc/UTC"}:
        logging.getLogger(__name__).warning(
            "database session TimeZone is %s; NULL-lease grace compares timestamps to now() and assumes UTC",
            zone,
        )


# --- TC-08-005: per-thread / per-task Session isolation helpers -------------------------------
# A SQLAlchemy Session (and the DBAPI connection it holds) is NOT thread-safe. Code that fans work
# out to threads must give each task its own short-lived Session on its own pooled connection,
# never reuse the caller's Session or the caller's Connection.


def supports_thread_isolation(bind) -> bool:
    """True when ``bind`` can safely hand a *separate* connection to each thread.

    Only an Engine backed by a real connection pool (QueuePool) or NullPool qualifies. A Session
    bound to a Connection (e.g. a test running inside an outer transaction) or an Engine using a
    single shared connection (StaticPool / SingletonThreadPool, typical for SQLite) does not:
    callers must then run the work serially on the calling thread.
    """
    if isinstance(bind, Connection) or not isinstance(bind, Engine):
        return False
    return isinstance(bind.pool, (QueuePool, NullPool))


def pool_thread_budget(bind, requested: int) -> int:
    """Bound ``requested`` worker threads so fan-out cannot exhaust the engine's pool.

    One connection is reserved for the calling thread (which normally already holds one).
    Returns 1 (serial) when the bind cannot be isolated per thread.
    """
    requested = max(1, int(requested))
    if not supports_thread_isolation(bind):
        return 1
    pool = bind.pool
    if isinstance(pool, QueuePool):
        size = pool.size()
        overflow = getattr(pool, "_max_overflow", 0)
        if overflow is None or overflow < 0:
            return requested  # unbounded overflow configured explicitly
        return max(1, min(requested, size + overflow - 1))
    return requested


_slot_lock = threading.Lock()
_task_slots: dict[tuple[int, str], threading.BoundedSemaphore] = {}


def task_slots(bind, name: str, size: int) -> threading.BoundedSemaphore:
    """Process-wide semaphore bounding concurrent task connections for ``name`` on ``bind``.

    Per-call thread caps alone do not bound the pool when several requests fan out at once;
    acquiring one of these slots around ``isolated_session`` caps total task connections per
    engine at ``size`` (fixed on first use for a given engine/name).
    """
    key = (id(bind), name)
    with _slot_lock:
        sem = _task_slots.get(key)
        if sem is None:
            sem = threading.BoundedSemaphore(max(1, int(size)))
            _task_slots[key] = sem
        return sem


@contextmanager
def isolated_session(bind) -> Iterator[Session]:
    """Yield a brand-new Session on its own pooled connection; always closed on exit.

    Use inside a worker thread/task. The Session is never shared with the caller, so the
    caller's transaction state cannot be corrupted and ORM instances never cross threads.
    Raises ValueError if ``bind`` cannot provide an independent connection (see
    ``supports_thread_isolation``).
    """
    if not supports_thread_isolation(bind):
        raise ValueError("isolated_session requires a pooled Engine bind, not a shared Connection")
    session = Session(bind=bind, autoflush=False, expire_on_commit=True)
    try:
        yield session
    finally:
        session.close()
