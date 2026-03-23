"""Alembic environment."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load apps/api/.env so DATABASE_URL is set when running alembic from apps/api (skip in test mode)
if os.environ.get("TRUST_COPILOT_TESTING") != "1":
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import Base
from app.models import Answer, AuditEvent, Chunk, Document, EmailVerificationToken, ExportRecord, Job, PasswordResetToken, TrustArticle, TrustRequest, Workspace  # noqa: F401 - register models

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Use resolved URL (postgres Docker hostname -> localhost when API runs on host).
database_url = get_settings().database_url
config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
