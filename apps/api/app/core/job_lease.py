"""Per-job leases (TC-10-001).

A running job is owned by one worker, named by an unguessable ``lease_owner`` token (the same
construction as ``idempotency.new_owner_token``). The lease is valid until ``lease_expires_at``.
Renewal is an ``UPDATE ... WHERE lease_owner = :owner AND lease_expires_at > :now RETURNING``,
so a stale owner cannot extend it. A commit fence takes the same row ``FOR UPDATE`` and refuses
the commit when that token no longer holds a live lease.

Lease instants use the database clock (``now()``), not the worker process clock.
Abandoned jobs (``running`` and ``lease_expires_at <= now()``) are locked with
``FOR UPDATE SKIP LOCKED``. The token swap and the retry classification commit together.
A NULL expiry is not abandoned: rows written before this lease existed stay untouched.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
from collections.abc import Callable
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

    Clamped to [1, 1200]. A missed beat must still leave a full interval, so the heartbeat is
    kept at most half the lease (``heartbeat * 2 <= lease``). A larger value is replaced with
    ``lease // 2``.
    """
    global _clamp_logged
    lease = lease_seconds()
    raw = _env_int(
        "JOB_LEASE_HEARTBEAT_SECONDS",
        DEFAULT_HEARTBEAT_SECONDS,
        MIN_HEARTBEAT_SECONDS,
        MAX_HEARTBEAT_SECONDS,
    )
    if raw * 2 <= lease:
        return raw
    clamped = max(1, lease // 2)
    if not _clamp_logged:
        _clamp_logged = True
        logger.warning(
            "JOB_LEASE_HEARTBEAT_SECONDS must be at most half JOB_LEASE_SECONDS; using %s",
            clamped,
        )
    return clamped


def renew_lease(
    job_id: int,
    owner: str,
    *,
    extend_seconds: int,
    session: Session | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> bool:
    """Extend the lease. True only when ``owner`` still holds a running, unexpired lease.

    Expiry is the database clock: ``lease_expires_at > now()``, and the new expiry is
    ``now()`` plus ``extend_seconds``. A Python clock is not consulted.
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
                SET lease_expires_at = now() + make_interval(secs => :seconds)
                WHERE id = :id
                  AND lease_owner = :owner
                  AND status = 'running'
                  AND lease_expires_at > now()
                RETURNING id
                """
            ),
            {"id": job_id, "owner": owner, "seconds": float(extend_seconds)},
        ).fetchone()
        session.commit()
        return row is not None
    except Exception:
        session.rollback()
        raise
    finally:
        if close:
            session.close()


def owns_lease(session_factory: Callable[[], Session], job_id: int, owner: str) -> bool:
    """True when the committed row is still running under ``owner`` and ``lease_expires_at > now()``."""
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
                  AND lease_expires_at > now()
                """
            ),
            {"id": job_id, "owner": owner},
        ).fetchone()
        return row is not None
    finally:
        session.close()


def lock_expired_lease(session: Session) -> tuple[int, str | None] | None:
    """Lock one running job whose lease is already past ``now()``.

    ``FOR UPDATE SKIP LOCKED`` so a second recoverer takes a different row, or none.
    Does not commit: the caller swaps the token and classifies the failure in this transaction.
    A NULL ``lease_expires_at`` is not expired.
    """
    row = session.execute(
        text(
            """
            SELECT id, lease_owner
            FROM jobs
            WHERE status = 'running'
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at <= now()
            ORDER BY lease_expires_at, id
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        )
    ).fetchone()
    if row is None:
        return None
    previous = row[1] if isinstance(row[1], str) else None
    return int(row[0]), previous


def claim_lease_expiry(session: Session, job_id: int, owner: str, seconds: int) -> None:
    """Set the lease expiry from the database clock. Does not commit."""
    session.execute(
        text(
            """
            UPDATE jobs
            SET lease_owner = :owner,
                lease_expires_at = now() + make_interval(secs => :seconds)
            WHERE id = :id
            """
        ),
        {"id": job_id, "owner": owner, "seconds": float(seconds)},
    )


def lease_is_held(session: Session, job_id: int, owner: str, *, lock: bool) -> bool:
    """True when this owner still has a running lease with ``lease_expires_at > now()``."""
    suffix = " FOR UPDATE" if lock else ""
    with session.no_autoflush:
        row = session.execute(
            text(
                f"""
                SELECT 1
                FROM jobs
                WHERE id = :id
                  AND lease_owner = :owner
                  AND status = 'running'
                  AND lease_expires_at > now()
                {suffix}
                """
            ),
            {"id": job_id, "owner": owner},
        ).fetchone()
    return row is not None


def confirm_lease_for_commit(session: Session, job_id: int, owner: str) -> None:
    """Lock the job row and raise LeaseLost unless ``owner`` still holds a live lease.

    The comparison is ``lease_expires_at > now()`` in the database. Call this before writing
    the completion, then commit in the same transaction.
    """
    if not lease_is_held(session, job_id, owner, lock=True):
        session.rollback()
        raise LeaseLost(job_id)


def install_commit_fence(session: Session, job_id: int, owner: str) -> None:
    """Refuse ``session.commit`` unless this owner still holds a live lease.

    The check is ``lease_expires_at > now()`` under ``FOR UPDATE``, with autoflush off, so a
    pending completion is not written before the lease is confirmed. The row lock is held until
    the commit. After the job is no longer running for this owner, later commits in the same
    session (notifications) are allowed.
    """
    if getattr(session, "_lease_fence_original", None) is not None:
        return
    original = session.commit
    session._lease_fence_open = True  # type: ignore[attr-defined]

    def fenced_commit():
        if not getattr(session, "_lease_fence_open", True):
            return original()
        if not lease_is_held(session, job_id, owner, lock=True):
            session.rollback()
            raise LeaseLost(job_id)
        result = original()
        if not lease_is_held(session, job_id, owner, lock=False):
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
