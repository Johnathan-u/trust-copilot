"""DB-backed idempotency for critical write endpoints. Shared across API replicas.

Flow: client sends Idempotency-Key header. First request claims the key (insert),
runs the handler, then stores the response. Duplicate requests see the key
already claimed and either get the cached response or 409 until the first completes.
"""

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

_DEFAULT_TTL_SEC = 86400  # 24 hours
_KEY_MAX_LEN = 256


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _valid_key(key: str) -> bool:
    return bool(key and len(key.strip()) <= _KEY_MAX_LEN)


def get(db: Session, key: str) -> tuple[int, dict] | None:
    """Return (status_code, response_body) if key exists, not expired, and response stored. Else None.
    Returns None when the row exists but response_body is null (request in progress).
    """
    if not _valid_key(key):
        return None
    k = key.strip()
    row = db.execute(
        text("""
            SELECT status_code, response_body
            FROM idempotency_keys
            WHERE idempotency_key = :k AND expires_at > :now
        """),
        {"k": k, "now": _now()},
    ).fetchone()
    if not row or row[1] is None:
        return None
    try:
        body = json.loads(row[1]) if isinstance(row[1], str) else row[1]
    except (TypeError, ValueError):
        return None
    return (int(row[0]), body)


def try_claim(db: Session, key: str, ttl_sec: int = _DEFAULT_TTL_SEC) -> bool:
    """Try to claim the idempotency key. Returns True if we inserted (caller must run handler and call set).
    Returns False if key already exists (another request is handling or already completed)."""
    if not _valid_key(key):
        return False
    k = key.strip()
    expires = _now() + timedelta(seconds=ttl_sec)
    try:
        result = db.execute(
            text("""
                INSERT INTO idempotency_keys (idempotency_key, status_code, response_body, expires_at)
                VALUES (:k, 0, NULL, :expires_at)
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING id
            """),
            {"k": k, "expires_at": expires},
        )
        row = result.fetchone()
        db.commit()
        return row is not None
    except Exception:
        db.rollback()
        return False


def set(
    db: Session, key: str, status_code: int, response_body: dict, ttl_sec: int = _DEFAULT_TTL_SEC
) -> None:
    """Store response for key. Call after successful handler execution. Updates existing row (from try_claim)."""
    if not _valid_key(key):
        return
    k = key.strip()
    expires = _now() + timedelta(seconds=ttl_sec)
    body_str = json.dumps(response_body)
    try:
        db.execute(
            text("""
                UPDATE idempotency_keys
                SET status_code = :sc, response_body = :body, expires_at = :expires_at
                WHERE idempotency_key = :k
            """),
            {"k": k, "sc": status_code, "body": body_str, "expires_at": expires},
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def scoped_key(workspace_id: int, route: str, resource_id: int | str, client_key: str) -> str:
    """Scope a client Idempotency-Key to workspace + route + resource (TC-10-003).

    Keys are stored in one global table; without scoping, the same client key used in two workspaces or on two
    routes would replay the other request's response. Returns "" for an empty/oversized client key.
    """
    k = (client_key or "").strip()
    if not k:
        return ""
    scoped = f"ws:{int(workspace_id)}:{route}:{resource_id}:{k}"
    return scoped if _valid_key(scoped) else ""


def release(db: Session, key: str) -> None:
    """Drop an in-progress claim (no stored response) so the client can retry, e.g. after a 429 (TC-10-003)."""
    if not _valid_key(key):
        return
    try:
        db.execute(
            text(
                "DELETE FROM idempotency_keys WHERE idempotency_key = :k AND response_body IS NULL"
            ),
            {"k": key.strip()},
        )
        db.commit()
    except Exception:
        db.rollback()
