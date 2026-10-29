"""Per-job leases (TC-10-001).

A running job is owned by one worker, named by an unguessable ``lease_owner`` token (the same
construction as ``idempotency.new_owner_token``). The lease is valid until ``lease_expires_at``.
Renewal is an ``UPDATE ... WHERE lease_owner = :owner AND lease_expires_at > :now RETURNING``,
so a stale owner cannot extend it. A commit fence takes the same row ``FOR UPDATE`` and refuses
the commit when that token no longer holds a live lease.

Abandoned jobs (``running`` and ``lease_expires_at`` in the past) are selected with
``FOR UPDATE SKIP LOCKED`` and handed back to the existing retry classifier. A NULL expiry is
not abandoned: rows written before this lease existed stay untouched.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DEFAULT_LEASE_SECONDS = 60
DEFAULT_HEARTBEAT_SECONDS = 15
MIN_LEASE_SECONDS = 10
MAX_LEASE_SECONDS = 3600
MIN_HEARTBEAT_SECONDS = 1
MAX_HEARTBEAT_SECONDS = 1200

# Shown on the job and in the audit trail. Not an upstream body.
LEASE_EXPIRED_MESSAGE = "Worker lease expired before the job finished; the attempt was abandoned"

_clamp_logged = False


class LeaseLost(Exception):
    """This worker no longer holds a valid lease, so it must not commit the job result."""

    def __init__(self, job_id: int) -> None:
        self.job_id = job_id
        super().__init__(f"job {job_id} lease is no longer held by this worker")


def new_lease_owner_token() -> str:
    """Random owner token (32 hex chars). Same construction as idempotency.new_owner_token."""
    return secrets.token_hex(16)


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        val = default
    else:
        try:
            val = int(raw)
        except ValueError:
            val = default
    return min(max(val, lo), hi)


def lease_seconds() -> int:
    """Lease lifetime in seconds. Clamped to [10, 3600]. Default 60."""
    return _env_int(
        "JOB_LEASE_SECONDS", DEFAULT_LEASE_SECONDS, MIN_LEASE_SECONDS, MAX_LEASE_SECONDS
    )


def lease_heartbeat_seconds() -> int:
    """How often the owner renews the lease.

    Clamped to [1, 1200] and forced below the lease. A heartbeat that is not shorter than the
    lease cannot land a renewal before expiry, so it is replaced with about one third of the lease.
    """
    global _clamp_logged
    lease = lease_seconds()
    raw = _env_int(
        "JOB_LEASE_HEARTBEAT_SECONDS",
        DEFAULT_HEARTBEAT_SECONDS,
        MIN_HEARTBEAT_SECONDS,
        MAX_HEARTBEAT_SECONDS,
    )
    if raw < lease:
        return raw
    clamped = max(MIN_HEARTBEAT_SECONDS, (lease - 1) // 3)
    if clamped >= lease:
        clamped = max(1, lease - 1)
    if not _clamp_logged:
        _clamp_logged = True
        logger.warning(
            "JOB_LEASE_HEARTBEAT_SECONDS must be lower than JOB_LEASE_SECONDS; using %s",
            clamped,
        )
    return clamped


def _naive(value: datetime | None) -> datetime | None:
    """Compare timestamps as naive UTC. Aware values are converted; other types are not a lease."""
    if value is None or not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        from datetime import timezone

        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def renew_lease(
    job_id: int,
    owner: str,
    *,
    now: datetime,
    extend_seconds: int,
    session: Session | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> bool:
    """Extend the lease. True only when ``owner`` still holds a running, unexpired lease.

    ``UPDATE ... WHERE lease_owner = :owner AND lease_expires_at > :now RETURNING id``.
    """
    close = session is None
    if session is None:
        if session_factory is None:
            raise RuntimeError("renew_lease needs a session or a session_factory")
        session = session_factory()
    try:
        row = session.execute(
            text(
                """
                UPDATE jobs
                SET lease_expires_at = :expires
                WHERE id = :id
                  AND lease_owner = :owner
                  AND status = 'running'
                  AND lease_expires_at > :now
                RETURNING id
                """
            ),
            {
                "id": job_id,
                "owner": owner,
                "now": now,
                "expires": now + timedelta(seconds=extend_seconds),
            },
        ).fetchone()
        session.commit()
        return row is not None
    except Exception:
        session.rollback()
        raise
    finally:
        if close:
            session.close()


def owns_lease(
    session_factory: Callable[[], Session], job_id: int, owner: str, now: datetime
) -> bool:
    """True when the committed row is still running under ``owner`` and the lease has not expired."""
    session = session_factory()
    try:
        row = session.execute(
            text(
                """
                SELECT 1
                FROM jobs
                WHERE id = :id
                  AND lease_owner = :owner
                  AND status = 'running'
                  AND lease_expires_at > :now
                """
            ),
            {"id": job_id, "owner": owner, "now": now},
        ).fetchone()
        return row is not None
    finally:
        session.close()


def steal_expired_leases(
    session: Session,
    *,
    now: datetime,
    owner: str,
    hold_until: datetime,
    limit: int = 20,
) -> list[tuple[int, str | None]]:
    """Lock expired running leases and retoken them. Returns ``(job_id, previous_owner)``.

    ``SELECT ... FOR UPDATE SKIP LOCKED`` so two recoverers cannot take the same row.
    A NULL ``lease_expires_at`` is not expired. Commits the steal. Returns [] when the
    session cannot execute SQL (a test double).
    """
    fetched = session.execute(
        text(
            """
            SELECT id, lease_owner
            FROM jobs
            WHERE status = 'running'
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at <= :now
            ORDER BY lease_expires_at, id
            FOR UPDATE SKIP LOCKED
            LIMIT :limit
            """
        ),
        {"now": now, "limit": limit},
    ).fetchall()
    if not isinstance(fetched, list):
        return []
    if not fetched:
        session.rollback()
        return []
    for row in fetched:
        session.execute(
            text(
                """
                UPDATE jobs
                SET lease_owner = :owner, lease_expires_at = :hold
                WHERE id = :id
                """
            ),
            {"owner": owner, "hold": hold_until, "id": row[0]},
        )
    session.commit()
    return [(int(row[0]), row[1]) for row in fetched]


def _row_owned(row, owner: str, now: datetime) -> bool:
    if row is None:
        return False
    lease_owner = row[0]
    status = row[1]
    expires = _naive(row[2])
    moment = _naive(now)
    return (
        lease_owner == owner
        and status == "running"
        and expires is not None
        and moment is not None
        and expires > moment
    )


def confirm_lease_for_commit(session: Session, job_id: int, owner: str, now: datetime) -> None:
    """Lock the job row and raise LeaseLost unless ``owner`` still holds a live lease.

    Call this before writing the completion, then commit in the same transaction.
    The row lock stops a recoverer until that commit. ``no_autoflush`` keeps a pending
    status change off the row until the check has passed.
    """
    with session.no_autoflush:
        row = session.execute(
            text(
                """
                SELECT lease_owner, status, lease_expires_at
                FROM jobs
                WHERE id = :id
                FOR UPDATE
                """
            ),
            {"id": job_id},
        ).fetchone()
    if not _row_owned(row, owner, now):
        session.rollback()
        raise LeaseLost(job_id)


def install_commit_fence(
    session: Session,
    job_id: int,
    owner: str,
    clock: Callable[[], datetime],
) -> None:
    """Refuse ``session.commit`` unless this owner still holds a live lease.

    The check is ``SELECT ... FOR UPDATE`` with autoflush off, so a pending completion is not
    written before the lease is confirmed. The row lock is held until the commit, which stops a
    recoverer from stealing the lease in that window. After the job is no longer running for this
    owner, later commits in the same session (notifications) are allowed.
    """
    if getattr(session, "_lease_fence_original", None) is not None:
        return
    original = session.commit
    session._lease_fence_open = True  # type: ignore[attr-defined]

    def fenced_commit():
        if not getattr(session, "_lease_fence_open", True):
            return original()
        with session.no_autoflush:
            row = session.execute(
                text(
                    """
                    SELECT lease_owner, status, lease_expires_at
                    FROM jobs
                    WHERE id = :id
                    FOR UPDATE
                    """
                ),
                {"id": job_id},
            ).fetchone()
        if not _row_owned(row, owner, clock()):
            session.rollback()
            raise LeaseLost(job_id)
        result = original()
        with session.no_autoflush:
            still = session.execute(
                text(
                    """
                    SELECT 1 FROM jobs
                    WHERE id = :id AND status = 'running' AND lease_owner = :owner
                    """
                ),
                {"id": job_id, "owner": owner},
            ).fetchone()
        if still is None:
            session._lease_fence_open = False  # type: ignore[attr-defined]
        return result

    session.commit = fenced_commit  # type: ignore[method-assign]
    session._lease_fence_original = original  # type: ignore[attr-defined]


def uninstall_commit_fence(session: Session) -> None:
    original = getattr(session, "_lease_fence_original", None)
    if original is None:
        return
    session.commit = original  # type: ignore[method-assign]
    session._lease_fence_original = None  # type: ignore[attr-defined]
    session._lease_fence_open = False  # type: ignore[attr-defined]


class JobLeaseHeartbeat:
    """Renew one job's lease until stopped or the renewal matches no row.

    ``sleep`` is injectable. Production waits on the stop event instead of ``time.sleep``,
    so ``stop`` interrupts the interval. Tests pass a ``sleep`` that does not block.
    """

    def __init__(
        self,
        renew: Callable[[], bool],
        *,
        interval_sec: float,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._renew = renew
        self.interval_sec = interval_sec
        self._sleep = sleep
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.beats = 0
        self.lost = False

    def beat_once(self) -> bool:
        """Renew once. A database error is logged and does not count as a lost lease."""
        if self.lost:
            return False
        try:
            ok = bool(self._renew())
        except Exception:
            logger.warning("job lease heartbeat failed", exc_info=True)
            return True
        if ok:
            self.beats += 1
            return True
        self.lost = True
        self._stop.set()
        return False

    def run_until_stopped(self) -> None:
        while not self._stop.is_set():
            if not self.beat_once():
                return
            if self._sleep is None:
                self._stop.wait(self.interval_sec)
            else:
                self._sleep(self.interval_sec)

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self.run_until_stopped, name="job-lease-heartbeat", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
