"""Test-suite isolation guards (TC-02-001).

Imported by ``tests/conftest.py`` *before* any application module so that importing or
collecting the suite can never reach production, a third-party provider, or use a
credential from a developer's ``.env``.

Three layers:

1. **Environment** - provider credentials (OpenAI, Stripe, OAuth/OIDC, SMTP, Sentry, AWS,
   Slack, Gmail, ID.me, Redis) are removed from ``os.environ`` unless provider tests are
   explicitly enabled with ``TC_ALLOW_PROVIDER_TESTS=1``. ``.env`` files are never read.
2. **Database target** - the test ``DATABASE_URL`` must point at a local/compose host and a
   database whose name ends in ``_test``; anything else aborts the run.
3. **Network egress guard** - ``socket.connect``/``connect_ex``/``getaddrinfo`` are wrapped so
   only loopback, Unix sockets and the configured local test services (Postgres, MinIO) are
   reachable. Every other attempt raises :class:`NetworkAccessBlocked` and is recorded; any
   attempt during collection fails the run.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import threading
from dataclasses import dataclass, field
from urllib.parse import urlparse

# Hosts the test suite may legitimately use: loopback plus docker-compose service names of
# the local test stack. Never add a real/remote host here.
LOCAL_SERVICE_HOSTS = frozenset({"localhost", "postgres", "minio", "testserver"})

# Env vars that carry credentials for real external providers. Removed unless
# TC_ALLOW_PROVIDER_TESTS=1 (and then only provider-marked tests should rely on them).
PROVIDER_SECRET_ENV_VARS = (
    "OPENAI_API_KEY",
    "OPENAI_ORG_ID",
    "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "OAUTH_GITHUB_CLIENT_SECRET",
    "OAUTH_GOOGLE_CLIENT_SECRET",
    "OAUTH_MICROSOFT_CLIENT_SECRET",
    "OIDC_CLIENT_SECRET",
    "OIDC_ISSUER_URL",
    "IDME_CLIENT_SECRET",
    "SMTP_HOST",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "SENTRY_DSN",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "SLACK_BOT_TOKEN",
    "SLACK_SIGNING_SECRET",
    "SLACK_CLIENT_SECRET",
    "GMAIL_CLIENT_SECRET",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "REDIS_URL",
)

PROVIDER_OPT_IN_ENV = "TC_ALLOW_PROVIDER_TESTS"
EXTRA_ALLOWED_HOSTS_ENV = "TC_TEST_ALLOWED_HOSTS"


def provider_tests_enabled() -> bool:
    return os.environ.get(PROVIDER_OPT_IN_ENV) == "1"


def scrub_provider_env(environ: dict | None = None) -> list[str]:
    """Remove provider credentials from the environment. Returns the names removed."""
    env = os.environ if environ is None else environ
    if environ is None and provider_tests_enabled():
        return []
    removed = [name for name in PROVIDER_SECRET_ENV_VARS if name in env]
    for name in removed:
        env.pop(name, None)
    return removed


class UnsafeTestTargetError(RuntimeError):
    """The configured test database/storage is not a local, test-only target."""


def _is_loopback_host(host: str) -> bool:
    host = (host or "").strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_local_test_host(host: str) -> bool:
    host = (host or "").strip("[]").lower()
    return _is_loopback_host(host) or host in LOCAL_SERVICE_HOSTS


def validate_test_database_url(url: str) -> str:
    """Return *url* if it targets a local ``*_test`` database, else raise UnsafeTestTargetError."""
    parsed = urlparse(url)
    if not parsed.scheme.startswith("postgresql"):
        raise UnsafeTestTargetError(
            f"test DATABASE_URL must be postgresql, got scheme {parsed.scheme!r}"
        )
    host = parsed.hostname or ""
    if not is_local_test_host(host):
        raise UnsafeTestTargetError(
            f"test DATABASE_URL host {host!r} is not local; tests only run against loopback or "
            f"compose hosts {sorted(LOCAL_SERVICE_HOSTS)}"
        )
    db_name = (parsed.path or "").lstrip("/")
    if not db_name.endswith("_test"):
        raise UnsafeTestTargetError(f"test database name {db_name!r} must end with '_test'")
    return url


def validate_test_s3_endpoint(url: str) -> str:
    host = urlparse(url).hostname or ""
    if not is_local_test_host(host):
        raise UnsafeTestTargetError(f"test S3_ENDPOINT host {host!r} is not local")
    return url


class NetworkAccessBlocked(ConnectionRefusedError):
    """Raised instead of opening a connection to a non-allowlisted host during tests."""


@dataclass
class _GuardState:
    allowed_hosts: set[str] = field(default_factory=set)
    allowed_ips: set[str] = field(default_factory=set)
    blocked: list[str] = field(default_factory=list)
    installed: bool = False
    phase: str = "import"
    lock: threading.Lock = field(default_factory=threading.Lock)


_STATE = _GuardState()
_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
_orig_getaddrinfo = socket.getaddrinfo


def _ip_allowed(ip: str) -> bool:
    ip = ip.split("%", 1)[0]
    try:
        if ipaddress.ip_address(ip).is_loopback:
            return True
    except ValueError:
        return False
    return ip in _STATE.allowed_ips


def _host_allowed(host) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    host = str(host).strip("[]").lower()
    if host in _STATE.allowed_hosts or _is_loopback_host(host):
        return True
    return _ip_allowed(host)


def _record(target: str) -> None:
    with _STATE.lock:
        _STATE.blocked.append(f"[{_STATE.phase}] {target}")


def _check_address(sock: socket.socket, address) -> None:
    family = getattr(sock, "family", None)
    if family not in (socket.AF_INET, socket.AF_INET6):
        return  # AF_UNIX etc. are local by definition
    host = address[0] if isinstance(address, tuple) and address else address
    if not _host_allowed(host):
        target = (
            f"{host}:{address[1]}" if isinstance(address, tuple) and len(address) > 1 else str(host)
        )
        _record(target)
        raise NetworkAccessBlocked(f"TC-02-001 network guard blocked connection to {target}")


def _guarded_connect(self, address):
    _check_address(self, address)
    return _orig_connect(self, address)


def _guarded_connect_ex(self, address):
    _check_address(self, address)
    return _orig_connect_ex(self, address)


def _guarded_getaddrinfo(host, *args, **kwargs):
    if not _host_allowed(host):
        _record(f"dns:{host}")
        raise NetworkAccessBlocked(f"TC-02-001 network guard blocked DNS lookup of {host}")
    return _orig_getaddrinfo(host, *args, **kwargs)


def install_network_guard(extra_hosts: list[str] | tuple[str, ...] = ()) -> None:
    """Patch socket so only loopback and the configured local test services are reachable."""
    hosts = {h.lower() for h in LOCAL_SERVICE_HOSTS}
    hosts.update(h.strip().lower() for h in extra_hosts if h and h.strip())
    hosts.update(
        h.strip().lower()
        for h in os.environ.get(EXTRA_ALLOWED_HOSTS_ENV, "").split(",")
        if h.strip()
    )
    # Every allowed host must itself be local; refuse to allowlist anything else.
    for h in list(hosts):
        if not is_local_test_host(h) and h not in _extra_local_hosts():
            raise UnsafeTestTargetError(
                f"refusing to allowlist non-local host {h!r} in the test network guard"
            )
    _STATE.allowed_hosts = hosts
    ips: set[str] = set()
    for h in hosts:
        try:
            ipaddress.ip_address(h)
            ips.add(h)
            continue
        except ValueError:
            pass
        if h in ("localhost", "testserver"):
            continue
        try:
            for info in _orig_getaddrinfo(h, None):
                ips.add(info[4][0].split("%", 1)[0])
        except OSError:
            pass  # not resolvable (e.g. compose name outside docker) - nothing to allow
    _STATE.allowed_ips = ips
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex
    socket.getaddrinfo = _guarded_getaddrinfo
    _STATE.installed = True


def _extra_local_hosts() -> set[str]:
    # TC_TEST_ALLOWED_HOSTS may only name additional compose-internal service hosts
    # (single-label names, no dots) - never a public DNS name or a routable IP.
    out = set()
    for h in os.environ.get(EXTRA_ALLOWED_HOSTS_ENV, "").split(","):
        h = h.strip().lower()
        if h and "." not in h and ":" not in h:
            out.add(h)
    return out


def uninstall_network_guard() -> None:
    socket.socket.connect = _orig_connect
    socket.socket.connect_ex = _orig_connect_ex
    socket.getaddrinfo = _orig_getaddrinfo
    _STATE.installed = False


def set_phase(phase: str) -> None:
    _STATE.phase = phase


def blocked_attempts() -> list[str]:
    with _STATE.lock:
        return list(_STATE.blocked)


def guard_installed() -> bool:
    return _STATE.installed
