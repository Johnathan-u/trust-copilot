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

# Prevent database.py from loading .env which would override these test values
os.environ["TRUST_COPILOT_TESTING"] = "1"
_db_host = "postgres" if os.path.exists("/.dockerenv") else "localhost"
os.environ["DATABASE_URL"] = f"postgresql://postgres:postgres@{_db_host}:5432/trustcopilot_test"
os.environ["SESSION_SECRET"] = "test-secret"
os.environ["S3_ENDPOINT"] = f"http://{'minio' if os.path.exists('/.dockerenv') else 'localhost'}:9000"
os.environ["S3_ACCESS_KEY"] = "minio"
os.environ["S3_SECRET_KEY"] = "minio123"
os.environ["S3_BUCKET_RAW"] = "test-raw"
os.environ["S3_BUCKET_EXPORTS"] = "test-exports"
os.environ["TRUSTED_ORIGINS"] = "http://localhost,http://localhost:3000,http://127.0.0.1,http://127.0.0.1:3000"
os.environ["RATE_LIMIT_RPM_PER_IP"] = "0"
# Avoid real OpenAI calls from question_to_controls during most tests (enable in test_mapping_llm_rerank only).
os.environ["MAPPING_LLM_RERANK"] = "0"
# Load OPENAI_API_KEY from root .env if not already in environment
if not os.environ.get("OPENAI_API_KEY"):
    _root_env = Path(__file__).resolve().parents[3] / ".env"
    if _root_env.exists():
        for _line in _root_env.read_text().splitlines():
            if _line.startswith("OPENAI_API_KEY="):
                os.environ["OPENAI_API_KEY"] = _line.split("=", 1)[1].strip()
                break
# Clear cached settings so it picks up the env vars set above
try:
    from app.core.config import get_settings
    get_settings.cache_clear()
except Exception:
    pass

TEST_ORIGIN = "http://localhost"
TEST_HEADERS = {"Origin": TEST_ORIGIN, "Referer": f"{TEST_ORIGIN}/"}

_API_ROOT = Path(__file__).resolve().parent.parent


def pytest_configure(config):
    """Ensure test env vars survive any .env loading and settings caching that happens during collection."""
    os.environ["TRUST_COPILOT_TESTING"] = "1"
    os.environ["TRUSTED_ORIGINS"] = "http://localhost,http://localhost:3000,http://127.0.0.1,http://127.0.0.1:3000"
    os.environ["RATE_LIMIT_RPM_PER_IP"] = "0"
    os.environ["MAPPING_LLM_RERANK"] = "0"
    try:
        from app.core.config import get_settings
        get_settings.cache_clear()
    except Exception:
        pass


def _create_test_db_if_needed():
    """Create the trustcopilot_test database if it does not exist."""
    import sqlalchemy
    admin_url = os.environ["DATABASE_URL"].rsplit("/", 1)[0] + "/postgres"
    try:
        eng = sqlalchemy.create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with eng.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = 'trustcopilot_test'")
            ).scalar()
            if not exists:
                conn.execute(text("CREATE DATABASE trustcopilot_test"))
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
            mem = session.query(WorkspaceMember).filter(
                WorkspaceMember.user_id == user.id,
                WorkspaceMember.workspace_id == 1,
            ).first()
            if not mem:
                session.add(WorkspaceMember(workspace_id=1, user_id=user.id, role="editor"))
                session.commit()
            ws2 = session.query(Workspace).filter(Workspace.id == 2).first()
            if not ws2:
                session.add(Workspace(id=2, name="Other", slug="other"))
                session.commit()
            mem2 = session.query(WorkspaceMember).filter(
                WorkspaceMember.user_id == user.id,
                WorkspaceMember.workspace_id == 2,
            ).first()
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
            rev_mem = session.query(WorkspaceMember).filter(
                WorkspaceMember.user_id == reviewer.id,
                WorkspaceMember.workspace_id == 1,
            ).first()
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
            admin_mem = session.query(WorkspaceMember).filter(
                WorkspaceMember.user_id == admin_u.id,
                WorkspaceMember.workspace_id == 1,
            ).first()
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
            editor_mem = session.query(WorkspaceMember).filter(
                WorkspaceMember.user_id == editor_u.id,
                WorkspaceMember.workspace_id == 1,
            ).first()
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


@pytest.fixture
def client(_ensure_test_data) -> Generator[TestClient, None, None]:
    """FastAPI TestClient with CSRF-safe headers and test data ensured. Skips when Postgres unavailable."""
    if not _ensure_test_data:
        pytest.skip("Postgres not available (start Docker or set DATABASE_URL to trustcopilot_test)")
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
