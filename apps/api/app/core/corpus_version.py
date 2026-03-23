"""Per-workspace corpus version for retrieval cache invalidation."""

import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def get_corpus_version(db: Session, workspace_id: int) -> str:
    """Return current version token for workspace. Creates row with default if missing."""
    row = db.execute(
        text("SELECT version_token FROM workspace_corpus_versions WHERE workspace_id = :ws"),
        {"ws": workspace_id},
    ).fetchone()
    if row:
        return row[0]
    # Insert default so we have a version
    token = _new_token()
    db.execute(
        text("INSERT INTO workspace_corpus_versions (workspace_id, version_token, updated_at) VALUES (:ws, :tok, :now) ON CONFLICT (workspace_id) DO NOTHING"),
        {"ws": workspace_id, "tok": token, "now": datetime.now(timezone.utc)},
    )
    db.commit()
    row = db.execute(text("SELECT version_token FROM workspace_corpus_versions WHERE workspace_id = :ws"), {"ws": workspace_id}).fetchone()
    return row[0] if row else token


def bump_corpus_version(db: Session, workspace_id: int) -> str:
    """Set new version token for workspace (call after document index or delete). Returns new token."""
    token = _new_token()
    db.execute(
        text("""
            INSERT INTO workspace_corpus_versions (workspace_id, version_token, updated_at)
            VALUES (:ws, :tok, :now)
            ON CONFLICT (workspace_id) DO UPDATE SET version_token = :tok, updated_at = :now
        """),
        {"ws": workspace_id, "tok": token, "now": datetime.now(timezone.utc)},
    )
    db.commit()
    logger.info("corpus_version bumped workspace_id=%s token=%s", workspace_id, token[:8])
    return token


def _new_token() -> str:
    """Generate a new version token."""
    return hashlib.sha256(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:24]
