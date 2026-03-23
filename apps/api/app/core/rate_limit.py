"""AUTH-210: Login abuse controls. In-memory (default) or Redis rate limiting."""

import logging
import os
import time
from collections import defaultdict
from threading import Lock

_rl_logger = logging.getLogger(__name__)

# Default: 10 attempts per 60 seconds per key (IP or email)
DEFAULT_MAX_ATTEMPTS = 10
DEFAULT_WINDOW_SECONDS = 60

# In-memory store for when Redis is not configured
_store: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))
_lock = Lock()


def _now() -> float:
    return time.monotonic()


class _InMemoryBackend:
    """In-memory rate limit backend (per-process)."""

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


class _RedisBackend:
    """Redis-backed rate limit. Uses INCR + EXPIRE for sliding window."""

    def __init__(self, redis_url: str):
        import redis
        self._client = redis.from_url(redis_url, decode_responses=True)

    def check(self, key: str, max_attempts: int, window_sec: float) -> bool:
        try:
            rkey = f"rate:{key}"
            count = self._client.get(rkey)
            if count is None:
                return False
            return int(count) >= max_attempts
        except Exception:
            return False  # Fail open on Redis errors

    def record(self, key: str, max_attempts: int, window_sec: float) -> None:
        try:
            rkey = f"rate:{key}"
            pipe = self._client.pipeline()
            pipe.incr(rkey)
            pipe.expire(rkey, int(window_sec) + 1)
            pipe.execute()
        except Exception:
            pass  # Fail open


def _get_backend():
    redis_url = (os.getenv("REDIS_URL") or "").strip()
    app_env = os.getenv("APP_ENV", "development").lower()
    if redis_url:
        try:
            backend = _RedisBackend(redis_url.strip())
            _rl_logger.info("Rate-limit backend: Redis (%s)", redis_url.split("@")[-1] if "@" in redis_url else redis_url)
            return backend
        except ImportError:
            _rl_logger.warning("REDIS_URL is set but redis package is not installed; falling back to in-memory rate limiting")
    if app_env == "production":
        _rl_logger.warning(
            "Rate limiting is using in-memory backend in production. "
            "This is per-process only and will not protect against distributed attacks. "
            "Set REDIS_URL for production-grade rate limiting."
        )
    else:
        _rl_logger.info("Rate-limit backend: in-memory (dev/test)")
    return _InMemoryBackend()


_backend = None


def _backend_instance():
    global _backend
    if _backend is None:
        _backend = _get_backend()
    return _backend


def is_rate_limited(
    key: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    window_sec: float = DEFAULT_WINDOW_SECONDS,
) -> bool:
    """Return True if the key is over the limit. Does not increment."""
    return _backend_instance().check(key, max_attempts, window_sec)


def record_attempt(
    key: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    window_sec: float = DEFAULT_WINDOW_SECONDS,
) -> None:
    """Record one attempt for the key (e.g. after a login try or API request)."""
    _backend_instance().record(key, max_attempts, window_sec)


def get_client_ip(request) -> str:
    """Get client IP from request.

    Only trusts X-Forwarded-For when TRUSTED_PROXY_IPS is configured (comma-separated)
    and request.client.host is one of those proxies. Otherwise uses the direct
    connection IP, which prevents X-Forwarded-For spoofing from untrusted clients.
    """
    direct_ip = "unknown"
    if getattr(request, "client", None) and request.client:
        direct_ip = request.client.host or "unknown"

    trusted_raw = os.getenv("TRUSTED_PROXY_IPS", "").strip()
    if trusted_raw:
        trusted_set = {ip.strip() for ip in trusted_raw.split(",") if ip.strip()}
        if direct_ip in trusted_set:
            forwarded = getattr(request, "headers", None) and request.headers.get("x-forwarded-for")
            if forwarded:
                return forwarded.split(",")[0].strip()

    return direct_ip
