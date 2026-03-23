"""Database session and engine."""

import os
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

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import get_settings

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
