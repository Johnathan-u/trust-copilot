"""AUTH-210 / TC-04-007b: shared login abuse controls.

Redis is used when ``REDIS_URL`` is set. Otherwise counters live in the
``rate_limit_buckets`` table, one fixed window per key, shared across processes.
The in-memory class is not selected.
"""

import hashlib
import logging
import math
import os
import time
from collections import defaultdict
from threading import Lock

_rl_logger = logging.getLogger(__name__)

# Default: 10 attempts per 60 seconds per key (IP or email)
DEFAULT_MAX_ATTEMPTS = 10
DEFAULT_WINDOW_SECONDS = 60

# The in-memory class below still reads this dict. Tests call ``_store.clear()`` to
# drop it and, when the database backend is installed, the shared rows as well.
class _SharedStore(defaultdict):
    def clear(self) -> None:
        super().clear()
        if _database_selected or isinstance(_backend, _DatabaseBackend):
            _DatabaseBackend().clear_shared()


_store: dict[str, tuple[int, float]] = _SharedStore(lambda: (0, 0.0))
_lock = Lock()
# Set once the database backend is selected, so a later ``_store.clear()`` still
# deletes shared rows if the installed backend object was replaced.
_database_selected = False


def _now() -> float:
    return time.monotonic()


class _InMemoryBackend:
    """Fixed-window counter kept in this process. ``_get_backend`` does not return it."""

    def check(self, key: str, max_attempts: int, window_sec: float) -> bool:
        with _lock:
            count, start = _store[key]
            now = _now()
            if now - start >= window_sec:
                return False
            return count >= max_attempts

    def record(self, key: str, max_attempts: int, window_sec: float) -> None:
        with _lock:
            count, start = _store[key]
            now = _now()
            if now - start >= window_sec:
                _store[key] = (1, now)
            else:
                _store[key] = (count + 1, start)

    def retry_after(self, key: str, window_sec: float) -> float:
        with _lock:
            if key not in _store:
                return 0.0
            _count, start = _store[key]
            return max(0.0, start + window_sec - _now())


class RateLimitBackendError(Exception):
    """The rate-limit store did not answer. Raised only when the caller fails closed."""


class _RedisBackend:
    """Redis-backed rate limit. Uses INCR + EXPIRE for sliding window.

    Store errors propagate. Callers fail open unless they pass ``fail_closed``.
    """

    def __init__(self, redis_url: str):
        import redis

        self._client = redis.from_url(redis_url, decode_responses=True)

    def check(self, key: str, max_attempts: int, window_sec: float) -> bool:
        rkey = f"rate:{key}"
        count = self._client.get(rkey)
        if count is None:
            return False
        return int(count) >= max_attempts

    def record(self, key: str, max_attempts: int, window_sec: float) -> None:
        rkey = f"rate:{key}"
        pipe = self._client.pipeline()
        pipe.incr(rkey)
        pipe.expire(rkey, int(window_sec) + 1)
        pipe.execute()

    def retry_after(self, key: str, window_sec: float) -> float:
        ttl = self._client.ttl(f"rate:{key}")
        return float(ttl) if ttl and ttl > 0 else float(window_sec)


_BUCKET_KEY_MAX = 512


def _bucket_key(key: str) -> str:
    """Store the limiter key as-is, or a digest when it would not fit the column."""
    raw = str(key)
    if len(raw) <= _BUCKET_KEY_MAX:
        return raw
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


class _DatabaseBackend:
    """Fixed window in ``rate_limit_buckets``. Each call commits on its own connection.

    A request that later rolls back still keeps the attempt. Two processes increment
    the same row; the window start stays until ``window_sec`` has passed.
    """

    def _connect(self):
        from app.core.database import engine

        return engine.begin()

    def _age_and_count(self, key: str) -> tuple[int, float] | None:
        from sqlalchemy import text

        with self._connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT attempt_count,
                           EXTRACT(EPOCH FROM (clock_timestamp() - window_started)) AS age
                    FROM rate_limit_buckets
                    WHERE bucket_key = :key
                    """
                ),
                {"key": _bucket_key(key)},
            ).fetchone()
        if row is None:
            return None
        return int(row[0]), float(row[1])

    def check(self, key: str, max_attempts: int, window_sec: float) -> bool:
        found = self._age_and_count(key)
        if found is None:
            return False
        count, age = found
        if age >= window_sec:
            return False
        return count >= max_attempts

    def record(self, key: str, max_attempts: int, window_sec: float) -> None:
        from sqlalchemy import text

        stored = _bucket_key(key)
        with self._connect() as conn:
            now = conn.execute(text("SELECT clock_timestamp()")).scalar()
            conn.execute(
                text(
                    """
                    INSERT INTO rate_limit_buckets (bucket_key, attempt_count, window_started)
                    VALUES (:key, 1, :now)
                    ON CONFLICT (bucket_key) DO UPDATE SET
                      attempt_count = CASE
                        WHEN EXTRACT(EPOCH FROM (:now - rate_limit_buckets.window_started))
                             >= :window
                        THEN 1
                        ELSE rate_limit_buckets.attempt_count + 1
                      END,
                      window_started = CASE
                        WHEN EXTRACT(EPOCH FROM (:now - rate_limit_buckets.window_started))
                             >= :window
                        THEN :now
                        ELSE rate_limit_buckets.window_started
                      END
                    """
                ),
                {"key": stored, "now": now, "window": float(window_sec)},
            )

    def retry_after(self, key: str, window_sec: float) -> float:
        found = self._age_and_count(key)
        if found is None:
            return 0.0
        _count, age = found
        if age >= window_sec:
            return 0.0
        return max(0.0, float(window_sec) - age)

    def clear_shared(self) -> None:
        """Drop every bucket. Test resets call this. A missing table is not an error."""
        from sqlalchemy import text
        from sqlalchemy.exc import ProgrammingError

        try:
            with self._connect() as conn:
                conn.execute(text("DELETE FROM rate_limit_buckets"))
        except ProgrammingError:
            _rl_logger.warning("rate_limit_buckets is missing; counters were not reset")


def _get_backend():
    global _database_selected
    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if redis_url:
        try:
            backend = _RedisBackend(redis_url.strip())
            _rl_logger.info(
                "Rate-limit backend: Redis (%s)",
                redis_url.split("@")[-1] if "@" in redis_url else redis_url,
            )
            return backend
        except ImportError:
            _rl_logger.warning(
                "REDIS_URL is set but redis package is not installed; "
                "using the database rate-limit store"
            )
    from app.core.session import is_production_env  # local: session imports nothing from here

    _database_selected = True
    if is_production_env():
        _rl_logger.info("Rate-limit backend: database (shared across processes in production)")
    else:
        _rl_logger.info("Rate-limit backend: database (shared across processes)")
    return _DatabaseBackend()


_backend = None


def _backend_instance():
    global _backend
    if _backend is None:
        _backend = _get_backend()
    return _backend


def _warn_store_unavailable(*, refused: bool) -> None:
    """Log a store outage without the exception text, which can contain a connection target."""
    if refused:
        _rl_logger.warning("Rate-limit store unavailable; refusing the request")
    else:
        _rl_logger.warning("Rate-limit store unavailable; allowing the request")


def is_rate_limited(
    key: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    window_sec: float = DEFAULT_WINDOW_SECONDS,
    *,
    fail_closed: bool = False,
) -> bool:
    """Return True if the key is over the limit. Does not increment.

    Store errors fail open (return False) unless ``fail_closed`` is set, in which case
    ``RateLimitBackendError`` is raised. Other routes keep the fail-open default.
    """
    try:
        return _backend_instance().check(key, max_attempts, window_sec)
    except Exception:
        _warn_store_unavailable(refused=fail_closed)
        if fail_closed:
            raise RateLimitBackendError()
        return False


def record_attempt(
    key: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    window_sec: float = DEFAULT_WINDOW_SECONDS,
) -> None:
    """Record one attempt for the key (e.g. after a login try or API request).

    A store error is ignored so a completed action is not turned into a failure.
    """
    try:
        _backend_instance().record(key, max_attempts, window_sec)
    except Exception:
        _warn_store_unavailable(refused=False)


def retry_after_seconds(key: str, window_sec: float) -> int:
    """Whole seconds until the key's current window resets (for a Retry-After header, >= 1)."""
    try:
        remaining = _backend_instance().retry_after(key, window_sec)
    except Exception:
        remaining = window_sec
    return max(1, math.ceil(remaining))


def get_client_ip(request) -> str:
    """Get client IP from request.

    Only trusts X-Forwarded-For when TRUSTED_PROXY_IPS is configured (comma-separated
    IPs or CIDRs) and request.client.host is one of those proxies. Otherwise uses
    the direct connection IP, which prevents X-Forwarded-For spoofing from untrusted
    clients. Unset trusts nothing.
    """
    direct_ip = "unknown"
    if getattr(request, "client", None) and request.client:
        direct_ip = request.client.host or "unknown"

    # Same peer rule as CSRF (TC-07-004): exact IPs and CIDRs, default trust nothing.
    trusted_raw = os.getenv("TRUSTED_PROXY_IPS", "").strip()
    from app.core.csrf import peer_is_trusted_proxy

    if peer_is_trusted_proxy(direct_ip, trusted_raw):
        forwarded = getattr(request, "headers", None) and request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()

    return direct_ip
