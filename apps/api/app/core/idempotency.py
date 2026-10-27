"""DB-backed idempotency for critical write endpoints. Shared across API replicas.

Flow: client sends Idempotency-Key header. First request claims the key (insert),
runs the handler, then stores the response. Duplicate requests see the key
already claimed and either get the cached response or 409 until the first completes.

An in-progress claim holds only a short lease. ``set`` extends that lease to the
full TTL when the response is stored. An expired row (crash, or TTL elapsed) can
be claimed again. ``cleanup_expired`` deletes rows past their lease or TTL.

Owner tokens (TC-10-003b): ``claim`` records a random ``owner_token`` on the row and
returns it. ``set``/``release`` called with ``owner=`` only touch the row while it still
carries that token, so a late finisher whose lease expired (and whose key was reclaimed
by a new request through the ON CONFLICT path) cannot free or overwrite the new owner's
claim. ``owner=None`` keeps the pre-TC-10-003b unconditional behavior for callers that
have not been migrated (``try_claim``-based routes).
"""

import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_DEFAULT_TTL_SEC = 86400  # 24 hours, applied when the response is stored
_IN_PROGRESS_LEASE_SEC = 60  # crash recovery: an unfinished claim expires quickly
_KEY_MAX_LEN = 256  # idempotency_keys.idempotency_key
# Client header, before workspace/route scoping. 1-255 of the safe token alphabet.
_CLIENT_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")
_CLIENT_KEY_MESSAGE = (
    "Idempotency-Key must be 1-255 characters and contain only "
    "letters, digits, and the characters . _ : -."
)


class IdempotencyKeyError(ValueError):
    """The client sent an Idempotency-Key that is empty, too long, or illegal."""


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


def new_owner_token() -> str:
    """Random, unguessable claim owner token (32 hex chars; column is 64)."""
    return secrets.token_hex(16)


def try_claim(db: Session, key: str, ttl_sec: int = _DEFAULT_TTL_SEC) -> bool:
    """Legacy boolean form of :func:`claim`: True if this caller now owns the key.

    The claim still records an owner token; callers that discard it must use ``owner=None``
    on ``set``/``release`` (unconditional, pre-TC-10-003b behavior). Prefer :func:`claim`.
    """
    return claim(db, key, ttl_sec) is not None


def claim(db: Session, key: str, ttl_sec: int = _DEFAULT_TTL_SEC) -> str | None:
    """Claim the key for this request. Returns this caller's owner token, or None if not claimed.

    A new row, and a row whose ``expires_at`` has passed, are claimed. The in-progress
    ``expires_at`` is a short lease (not ``ttl_sec``). ``set`` extends it to ``ttl_sec``
    when the response is stored. An unexpired row — in progress or already completed —
    is left untouched and this returns False.

    ``ttl_sec`` is accepted for callers that share the completion-TTL default; the
    in-progress lease does not use it.
    """
    del ttl_sec  # completion TTL is applied by set(), not by the in-progress lease
    if not _valid_key(key):
        return None
    k = key.strip()
    lease_expires = _now() + timedelta(seconds=_IN_PROGRESS_LEASE_SEC)
    owner = new_owner_token()
    try:
        # A reclaim of an expired row replaces owner_token, which is what fences the previous owner out.
        result = db.execute(
            text("""
                INSERT INTO idempotency_keys
                    (idempotency_key, status_code, response_body, expires_at, owner_token)
                VALUES (:k, 0, NULL, :expires_at, :owner)
                ON CONFLICT (idempotency_key) DO UPDATE
                SET status_code = 0,
                    response_body = NULL,
                    expires_at = EXCLUDED.expires_at,
                    owner_token = EXCLUDED.owner_token
                WHERE idempotency_keys.expires_at <= now()
                RETURNING id
            """),
            {"k": k, "expires_at": lease_expires, "owner": owner},
        )
        row = result.fetchone()
        db.commit()
        return owner if row is not None else None
    except Exception:
        logger.warning("idempotency try_claim failed", exc_info=True)
        db.rollback()
        return None


def _owner_clause(owner: str | None) -> str:
    """SQL fence for set/release: match the caller's token, or nothing extra for legacy callers."""
    return "" if owner is None else " AND owner_token = :owner"


def set(
    db: Session,
    key: str,
    status_code: int,
    response_body: dict,
    ttl_sec: int = _DEFAULT_TTL_SEC,
    *,
    owner: str | None = None,
) -> bool:
    """Store the response and extend the short in-progress lease to the full TTL.

    TC-10-003a: 5xx responses are never cached. A server error is not a final answer for the request, so
    the in-progress claim is released instead and the client's retry with the same key runs again.

    TC-10-003b: with ``owner`` (the token returned by :func:`claim`), the row is only updated while it still
    carries that token. A stale owner (lease expired, key reclaimed by another request) is a no-op.
    Returns True if a row was written.
    """
    if not _valid_key(key):
        return False
    if status_code >= 500:
        logger.info("idempotency: not caching %s response; releasing claim", status_code)
        release(db, key, owner=owner)
        return False
    k = key.strip()
    expires = _now() + timedelta(seconds=ttl_sec)
    body_str = json.dumps(response_body)
    params = {"k": k, "sc": status_code, "body": body_str, "expires_at": expires}
    if owner is not None:
        params["owner"] = owner
    try:
        result = db.execute(
            text(
                """
                UPDATE idempotency_keys
                SET status_code = :sc, response_body = :body, expires_at = :expires_at
                WHERE idempotency_key = :k"""
                + _owner_clause(owner)
            ),
            params,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    written = bool(result.rowcount)
    if not written and owner is not None:
        logger.warning("idempotency set skipped: claim is no longer owned by this request")
    return written


def scoped_key(
    workspace_id: int, route: str, resource_id: int | str, client_key: str | None
) -> str:
    """Scope a client Idempotency-Key to workspace + route + resource (TC-10-003).

    Keys are stored in one global table; without scoping, the same client key used in two workspaces or on two
    routes would replay the other request's response.

    Returns "" when the header is absent (``client_key is None``): idempotency is optional.
    Raises IdempotencyKeyError when the header is present but empty, longer than 255 characters,
    outside ``[A-Za-z0-9._:-]``, or too long to store once scoped (column limit 256).
    """
    if client_key is None:
        return ""
    if not _CLIENT_KEY_RE.fullmatch(client_key):
        raise IdempotencyKeyError(_CLIENT_KEY_MESSAGE)
    scoped = f"ws:{int(workspace_id)}:{route}:{resource_id}:{client_key}"
    if len(scoped) > _KEY_MAX_LEN:
        raise IdempotencyKeyError(
            "Idempotency-Key is too long to store for this route "
            f"(stored key limit is {_KEY_MAX_LEN} characters)."
        )
    return scoped


def cleanup_expired(db: Session) -> int:
    """Delete idempotency rows whose lease or TTL has passed. Returns how many were removed.

    Called from the worker's hourly maintenance loop (alongside quota usage cleanup).
    """
    try:
        result = db.execute(
            text("DELETE FROM idempotency_keys WHERE expires_at <= :now"),
            {"now": _now()},
        )
        db.commit()
        return int(result.rowcount or 0)
    except Exception:
        logger.warning("idempotency cleanup_expired failed", exc_info=True)
        db.rollback()
        raise


def release(db: Session, key: str, *, owner: str | None = None) -> bool:
    """Drop an in-progress claim (no stored response) so the client can retry, e.g. after a 429 (TC-10-003).

    TC-10-003b: with ``owner``, only this caller's own claim is dropped; a stale owner's release after a
    reclaim is a no-op. Returns True if a row was deleted.
    """
    if not _valid_key(key):
        return False
    params = {"k": key.strip()}
    if owner is not None:
        params["owner"] = owner
    try:
        result = db.execute(
            text(
                "DELETE FROM idempotency_keys WHERE idempotency_key = :k AND response_body IS NULL"
                + _owner_clause(owner)
            ),
            params,
        )
        db.commit()
    except Exception:
        db.rollback()
        return False
    deleted = bool(result.rowcount)
    if not deleted and owner is not None:
        logger.info("idempotency release skipped: claim is no longer owned by this request")
    return deleted
