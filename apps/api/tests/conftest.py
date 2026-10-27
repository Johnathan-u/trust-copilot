"""Pytest fixtures for Trust Copilot API tests. Enterprise test suite (auth, RBAC, API contracts)."""

import os
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

# --- TC-02-001: isolate the suite from live services and real credentials -------------------
# This block runs before any `app` import. It never reads a .env file.
from tests import _safety

os.environ["TRUST_COPILOT_TESTING"] = "1"
# Provider credentials (OpenAI, Stripe, OAuth, SMTP, Sentry, ...) are removed unless
# TC_ALLOW_PROVIDER_TESTS=1. Tests that need a real provider must be marked `provider`.
_safety.scrub_provider_env()
_in_docker_env = os.path.exists("/.dockerenv")
_db_host = "postgres" if _in_docker_env else "localhost"
# TC_TEST_DATABASE_URL lets a developer/CI point at a different *local* *_test* database
# (e.g. another port). It is validated: non-local hosts or non-`_test` names abort the run.
os.environ["DATABASE_URL"] = _safety.validate_test_database_url(
    os.environ.get("TC_TEST_DATABASE_URL")
    or f"postgresql://postgres:postgres@{_db_host}:5432/trustcopilot_test"
)
# TC-07-001: generated per test run; never a committed literal.
import secrets as _secrets  # noqa: E402

os.environ["SESSION_SECRET"] = _secrets.token_urlsafe(48)
os.environ["S3_ENDPOINT"] = _safety.validate_test_s3_endpoint(
    f"http://{'minio' if _in_docker_env else 'localhost'}:9000"
)
# Synthetic local-MinIO credentials (match docker-compose dev defaults; not a real secret).
os.environ["S3_ACCESS_KEY"] = "minio"
os.environ["S3_SECRET_KEY"] = "minio123"
os.environ["S3_BUCKET_RAW"] = "test-raw"
os.environ["S3_BUCKET_EXPORTS"] = "test-exports"
os.environ["TRUSTED_ORIGINS"] = (
    "http://localhost,http://localhost:3000,http://127.0.0.1,http://127.0.0.1:3000"
)
os.environ["RATE_LIMIT_RPM_PER_IP"] = "0"
# Avoid real OpenAI calls from question_to_controls during most tests (enable in test_mapping_llm_rerank only).
os.environ["MAPPING_LLM_RERANK"] = "0"
# Egress guard: only loopback + local test services (Postgres/MinIO) are reachable from Python sockets.
_safety.install_network_guard()
# Clear cached settings so it picks up the env vars set above
try:
    from app.core.config import get_settings

    get_settings.cache_clear()
except Exception:
    pass

TEST_ORIGIN = "http://localhost"
TEST_HEADERS = {"Origin": TEST_ORIGIN, "Referer": f"{TEST_ORIGIN}/"}

_API_ROOT = Path(__file__).resolve().parent.parent


# Module classification (TC-02-001). A test is `integration` if it uses a DB/app fixture or its
# module touches the database / ASGI app directly; otherwise `unit`. Explicit markers win.
_INTEGRATION_FIXTURES = frozenset({"client", "db_session", "test_workspace", "_ensure_test_data"})
_INTEGRATION_SOURCE_HINTS = (
    "SessionLocal",
    "TestClient",
    "create_engine",
    "from app.main import",
    "import app.main",
    "engine.connect",
    "get_db",
)
_CATEGORY_MARKERS = ("unit", "integration", "provider", "live_stack", "external_data")
_module_hint_cache: dict[str, bool] = {}


def _module_touches_db(path) -> bool:
    key = str(path)
    if key not in _module_hint_cache:
        try:
            src = Path(key).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            src = ""
        _module_hint_cache[key] = any(h in src for h in _INTEGRATION_SOURCE_HINTS)
    return _module_hint_cache[key]


def pytest_collectstart(collector):
    _safety.set_phase("collection")


def pytest_collection_modifyitems(config, items):
    """Auto-classify tests and gate opt-in categories with explicit skip reasons."""
    allow_provider = _safety.provider_tests_enabled()
    allow_live = os.environ.get("TC_LIVE_STACK_TESTS") == "1"
    for item in items:
        own = {m.name for m in item.iter_markers()}
        if not own.intersection(_CATEGORY_MARKERS):
            if _INTEGRATION_FIXTURES.intersection(
                getattr(item, "fixturenames", ())
            ) or _module_touches_db(item.fspath):
                item.add_marker(pytest.mark.integration)
            else:
                item.add_marker(pytest.mark.unit)
        if "provider" in own and not allow_provider:
            item.add_marker(
                pytest.mark.skip(
                    reason="provider: real third-party call; set TC_ALLOW_PROVIDER_TESTS=1"
                )
            )
        if "live_stack" in own and not allow_live:
            item.add_marker(
                pytest.mark.skip(
                    reason="live_stack: needs a running local stack; set TC_LIVE_STACK_TESTS=1"
                )
            )


def pytest_collection_finish(session):
    _safety.set_phase("run")
    during_collection = [
        b for b in _safety.blocked_attempts() if b.startswith(("[import]", "[collection]"))
    ]
    if during_collection:
        raise pytest.UsageError(
            "TC-02-001: network access attempted while importing/collecting tests: "
            + ", ".join(during_collection)
        )


def pytest_runtest_setup(item):
    _safety.set_phase(f"run {item.nodeid}")


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    attempts = _safety.blocked_attempts()
    if attempts:
        terminalreporter.write_sep("-", "TC-02-001 network guard: blocked egress attempts")
        for a in attempts:
            terminalreporter.write_line(a)


def pytest_configure(config):
    """Ensure test env vars survive any .env loading and settings caching that happens during collection."""
    os.environ["TRUST_COPILOT_TESTING"] = "1"
    _safety.scrub_provider_env()
    os.environ["TRUSTED_ORIGINS"] = (
        "http://localhost,http://localhost:3000,http://127.0.0.1,http://127.0.0.1:3000"
    )
    os.environ["RATE_LIMIT_RPM_PER_IP"] = "0"
    os.environ["MAPPING_LLM_RERANK"] = "0"
    try:
        from app.core.config import get_settings

        get_settings.cache_clear()
    except Exception:
        pass


def _create_test_db_if_needed():
    """Create the (validated, *_test) test database if it does not exist."""
    import sqlalchemy

    url = _safety.validate_test_database_url(os.environ["DATABASE_URL"])
    db_name = url.rsplit("/", 1)[1].split("?", 1)[0]
    admin_url = url.rsplit("/", 1)[0] + "/postgres"
    try:
        eng = sqlalchemy.create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with eng.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": db_name}
            ).scalar()
            if not exists:
                conn.execute(text('CREATE DATABASE "{}"'.format(db_name.replace('"', ""))))
        eng.dispose()
    except Exception:
        pass


def _run_alembic_upgrade():
    """Run alembic upgrade head against the test database."""
    env = {
        **os.environ,
        "DATABASE_URL": os.environ["DATABASE_URL"],
        "TRUST_COPILOT_TESTING": "1",
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(_API_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade head failed (do not stamp on error):\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def _verify_registry_schema(engine) -> bool:
    """Return True if documents, trust_requests, questionnaires have display_id."""
    required = [
        ("documents", "display_id"),
        ("trust_requests", "display_id"),
        ("questionnaires", "display_id"),
    ]
    with engine.connect() as conn:
        for table, col in required:
            r = conn.execute(
                text(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = :t AND column_name = :c
                    """
                ),
                {"t": table, "c": col},
            )
            if not r.scalar():
                return False
    return True


def _force_migrations_resync():
    """Fix schema drift: stamp 037 (if columns missing, downgrade would fail) then upgrade head."""
    env = {
        **os.environ,
        "DATABASE_URL": os.environ["DATABASE_URL"],
        "TRUST_COPILOT_TESTING": "1",
    }
    for cmd, args in [("stamp", ["037"]), ("upgrade", ["head"])]:
        r = subprocess.run(
            [sys.executable, "-m", "alembic", cmd, *args],
            cwd=str(_API_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r.returncode != 0:
            raise RuntimeError(
                f"alembic {cmd} {' '.join(args)} failed:\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
            )


_db_ready = None


def _ensure_db_schema():
    """Create test DB and run migrations (once per process)."""
    global _db_ready
    if _db_ready is not None:
        return _db_ready
    try:
        # Clear any cached settings so they pick up test env vars
        from app.core.config import get_settings

        get_settings.cache_clear()

        _create_test_db_if_needed()
        _run_alembic_upgrade()

        # Verify registry columns exist; if not, schema drift from stamp-on-error.
        import sqlalchemy

        engine = sqlalchemy.create_engine(os.environ["DATABASE_URL"])
        if not _verify_registry_schema(engine):
            engine.dispose()
            _force_migrations_resync()
            engine = sqlalchemy.create_engine(os.environ["DATABASE_URL"])
            if not _verify_registry_schema(engine):
                engine.dispose()
                raise RuntimeError(
                    "Registry schema verification failed after migration resync. "
                    "Expected display_id on documents, trust_requests, questionnaires. "
                    "Run: DATABASE_URL=.../trustcopilot_test alembic downgrade 037 && alembic upgrade head"
                )
        engine.dispose()
        _db_ready = True
    except Exception as exc:
        print(f"WARNING: test DB setup failed: {exc}", file=sys.stderr)
        _db_ready = False
    return _db_ready


@pytest.fixture(autouse=True)
def _mock_storage():
    """Mock MinIO bucket creation so tests run without MinIO."""
    with patch("app.services.storage.StorageClient.ensure_buckets"):
        yield


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    """Reset in-memory rate limit counters and settings cache between tests."""
    from app.core import rate_limit as _rl
    from app.core.config import get_settings

    _rl._store.clear()
    _rl._backend = None
    get_settings.cache_clear()
    yield
    _rl._store.clear()


@pytest.fixture(scope="session")
def _ensure_test_data():
    """Ensure DB schema is current and workspace 1 + demo user exist."""
    if not _ensure_db_schema():
        return False
    try:
        from app.core.database import SessionLocal
        from app.core.password import hash_password
        from app.models import User, Workspace, WorkspaceMember

        session = SessionLocal()
        try:
            ws = session.query(Workspace).filter(Workspace.id == 1).first()
            if not ws:
                session.add(Workspace(id=1, name="Default", slug="default"))
                session.commit()
            user = session.query(User).filter(User.email == "demo@trust.local").first()
            if not user:
                user = User(
                    email="demo@trust.local",
                    password_hash=hash_password("j"),
                    display_name="Demo User",
                )
                session.add(user)
                session.commit()
                session.refresh(user)
            mem = (
                session.query(WorkspaceMember)
                .filter(
                    WorkspaceMember.user_id == user.id,
                    WorkspaceMember.workspace_id == 1,
                )
                .first()
            )
            if not mem:
                session.add(WorkspaceMember(workspace_id=1, user_id=user.id, role="editor"))
                session.commit()
            ws2 = session.query(Workspace).filter(Workspace.id == 2).first()
            if not ws2:
                session.add(Workspace(id=2, name="Other", slug="other"))
                session.commit()
            mem2 = (
                session.query(WorkspaceMember)
                .filter(
                    WorkspaceMember.user_id == user.id,
                    WorkspaceMember.workspace_id == 2,
                )
                .first()
            )
            if not mem2:
                session.add(WorkspaceMember(workspace_id=2, user_id=user.id, role="editor"))
                session.commit()
            ws3 = session.query(Workspace).filter(Workspace.id == 3).first()
            if not ws3:
                session.add(Workspace(id=3, name="NoAccess", slug="noaccess"))
                session.commit()
            # Reviewer user (can review but cannot edit)
            reviewer = session.query(User).filter(User.email == "reviewer@trust.local").first()
            if not reviewer:
                reviewer = User(
                    email="reviewer@trust.local",
                    password_hash=hash_password("r"),
                    display_name="Reviewer User",
                )
                session.add(reviewer)
                session.commit()
                session.refresh(reviewer)
            rev_mem = (
                session.query(WorkspaceMember)
                .filter(
                    WorkspaceMember.user_id == reviewer.id,
                    WorkspaceMember.workspace_id == 1,
                )
                .first()
            )
            if not rev_mem:
                session.add(WorkspaceMember(workspace_id=1, user_id=reviewer.id, role="reviewer"))
                session.commit()
            # Admin user (full permissions)
            admin_u = session.query(User).filter(User.email == "admin@trust.local").first()
            if not admin_u:
                admin_u = User(
                    email="admin@trust.local",
                    password_hash=hash_password("a"),
                    display_name="Admin User",
                )
                session.add(admin_u)
                session.commit()
                session.refresh(admin_u)
            admin_mem = (
                session.query(WorkspaceMember)
                .filter(
                    WorkspaceMember.user_id == admin_u.id,
                    WorkspaceMember.workspace_id == 1,
                )
                .first()
            )
            if not admin_mem:
                session.add(WorkspaceMember(workspace_id=1, user_id=admin_u.id, role="admin"))
                session.commit()
            elif admin_mem.role != "admin":
                admin_mem.role = "admin"
                session.commit()
            # Editor user (can edit, cannot admin, cannot manage tags)
            editor_u = session.query(User).filter(User.email == "editor@trust.local").first()
            if not editor_u:
                editor_u = User(
                    email="editor@trust.local",
                    password_hash=hash_password("e"),
                    display_name="Editor User",
                )
                session.add(editor_u)
                session.commit()
                session.refresh(editor_u)
            editor_mem = (
                session.query(WorkspaceMember)
                .filter(
                    WorkspaceMember.user_id == editor_u.id,
                    WorkspaceMember.workspace_id == 1,
                )
                .first()
            )
            if not editor_mem:
                session.add(WorkspaceMember(workspace_id=1, user_id=editor_u.id, role="editor"))
                session.commit()
            elif editor_mem.role != "editor":
                editor_mem.role = "editor"
                session.commit()
            return True
        finally:
            session.close()
    except Exception:
        return False


def _db_required() -> bool:
    """CI sets TC_REQUIRE_DB=1: an unavailable or incompatible test DB is then a hard failure,
    never a silent skip (e.g. SQLAlchemy 2.1 + psycopg2-only install made every DB test skip)."""
    return os.environ.get("TC_REQUIRE_DB") == "1"


_DB_UNAVAILABLE_MSG = (
    "Postgres test database unavailable or incompatible (see 'WARNING: test DB setup failed' "
    "above; start the local test Postgres or set TC_TEST_DATABASE_URL to a local *_test database)"
)


def pytest_sessionstart(session):
    """Fail the whole run up front when the DB is required but unusable."""
    if _db_required() and not _ensure_db_schema():
        pytest.exit(f"TC_REQUIRE_DB=1: {_DB_UNAVAILABLE_MSG}", returncode=3)


@pytest.fixture
def client(_ensure_test_data) -> Generator[TestClient, None, None]:
    """FastAPI TestClient with CSRF-safe headers and test data ensured.

    Skips when Postgres is unavailable, unless TC_REQUIRE_DB=1 (CI), where it fails loudly.
    """
    if not _ensure_test_data:
        if _db_required():
            pytest.fail(f"TC_REQUIRE_DB=1: {_DB_UNAVAILABLE_MSG}")
        pytest.skip(_DB_UNAVAILABLE_MSG)
    from app.main import app

    yield TestClient(app, base_url=TEST_ORIGIN, headers=TEST_HEADERS)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Database session for direct DB access in tests."""
    _ensure_db_schema()
    from app.core.database import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def test_workspace(db_session: Session) -> dict:
    """Test workspace (id=1) from seed. Must exist after migrations."""
    from app.models import Workspace

    ws = db_session.query(Workspace).filter(Workspace.id == 1).first()
    if ws:
        return {"id": ws.id, "name": ws.name, "slug": ws.slug}
    return {"id": 1, "name": "Default", "slug": "default"}


SYNTHETIC_OPENAI_KEY = "sk-test-synthetic-offline-key"


@pytest.fixture
def synthetic_openai_key(monkeypatch):
    """Set a fake OpenAI key for code paths that only check the key is configured.

    The OpenAI client must still be mocked by the test; any real call is blocked by the
    TC-02-001 network guard. Never use a real key here.
    """
    from app.core.config import get_settings

    monkeypatch.setenv("OPENAI_API_KEY", SYNTHETIC_OPENAI_KEY)
    get_settings.cache_clear()
    yield SYNTHETIC_OPENAI_KEY
    get_settings.cache_clear()
