"""Configuration contract and production startup validation (TC-03-001).

Single source of truth for the environment variables the API, worker and migration
containers read: their type, whether production requires them, whether they are secret,
and the owner-account prerequisite behind them. ``validate_environment`` checks an
environment mapping against the contract; ``enforce_startup_contract`` is called by the API
lifespan, the worker and Alembic so production FAILS CLOSED before touching the database.

Error messages name the variable and the reason only. Values are NEVER included in messages,
logs or exceptions.

Run ``python -m app.core.config_contract markdown`` to print the documented variable table
(docs/release/config-contract.md is generated from it) or ``python -m app.core.config_contract
check`` to validate the current environment (exit 0 ok, 2 invalid).
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from typing import Iterable, Mapping
from urllib.parse import urlsplit

# Production detection and the SESSION_SECRET strength rule are master's (TC-07-001/001a): this module
# never decides "is this production?" or "is this signing key weak?" on its own.
from app.core.session import MIN_PRODUCTION_SECRET_LENGTH, is_production_env, is_weak_secret

ALLOWED_APP_ENVS = ("development", "test", "staging", "production")
MIN_PRODUCTION_PASSWORD_LENGTH = 16

# Publicly documented vendor/tutorial defaults and placeholder words. Compared case-insensitively.
# These are NOT secrets of this project; the scanner classifies them as review-only.
KNOWN_DEFAULT_CREDENTIALS = frozenset(
    {
        "postgres",
        "postgresql",
        "minioadmin",
        "minio",
        "minio123",
        "admin",
        "administrator",
        "root",
        "password",
        "passw0rd",
        "pass",
        "secret",
        "changeme",
        "change-me",
        "change_me",
        "changeit",
        "default",
        "example",
        "test",
        "testing",
        "dev",
        "development",
        "local",
        "demo",
        "qwerty",
        "letmein",
        "trustcopilot",
        "trust-copilot",
        "user",
        "guest",
        "123456",
        "12345678",
    }
)
# Whole values that are documentation placeholders rather than credentials (case-insensitive).
_EXACT_PLACEHOLDERS = frozenset(
    {
        "placeholder",
        "changeme",
        "change-me",
        "change_me",
        "changeit",
        "replaceme",
        "replace-me",
        "replace_me",
        "your-key-here",
        "your_key_here",
        "your-secret-here",
        "your_secret_here",
        "your-password-here",
        "your-api-key",
        "your-api-key-here",
        "todo",
        "tbd",
        "fixme",
        "dummy",
        "sample",
        "insecure",
        "none",
        "null",
    }
)
# Marker words. They only count as a whole token (split on [-_.:/ ]), and only when the value
# has too little other material to be a generated credential: a long random secret that happens
# to contain "todo" or "Sample" is accepted.
_PLACEHOLDER_MARKER_TOKENS = frozenset(
    {
        "placeholder",
        "changeme",
        "change",
        "changeit",
        "replace",
        "replaceme",
        "your",
        "example",
        "todo",
        "tbd",
        "fixme",
        "dummy",
        "sample",
        "insecure",
    }
)
_TOKEN_SPLIT = re.compile(r"[-_.:/ ]+")
_MIN_RANDOM_MATERIAL = 16

TRUTHY = ("1", "true", "yes", "on")


@dataclass(frozen=True)
class ConfigVar:
    name: str
    type: str
    production: str  # "required" | "forbidden" | "optional" | "conditional"
    secret: bool
    default: str  # description of the non-production default (never a credential value)
    description: str
    prerequisite: str = ""  # owner account / infrastructure prerequisite, if any


CONTRACT: tuple[ConfigVar, ...] = (
    ConfigVar(
        "APP_ENV",
        "enum(development|test|staging|production)",
        "required",
        False,
        "development",
        "Runtime mode. Only `production` enables the fail-closed checks below; unknown values are rejected.",
    ),
    ConfigVar(
        "SESSION_SECRET",
        "secret string (>=32 chars, >=8 distinct chars)",
        "required",
        True,
        "random per-process key (dev/test only)",
        "Signs `tc_session` cookies and OAuth state; derives MFA/Slack/credential-store keys. Placeholders rejected.",
    ),
    ConfigVar(
        "DATABASE_URL",
        "postgresql URL with user and password",
        "required",
        True,
        "local dev URL on localhost:5432 (dev only)",
        "Postgres DSN. Production: must be set explicitly; vendor-default/placeholder or short (<16) passwords rejected.",
        "Managed or self-hosted PostgreSQL 16 + pgvector",
    ),
    ConfigVar(
        "POSTGRES_USER",
        "string",
        "conditional",
        False,
        "compose dev default",
        "Postgres container superuser (compose). If visible to the app in production, must not be a vendor default.",
    ),
    ConfigVar(
        "POSTGRES_PASSWORD",
        "secret string (>=16 chars)",
        "conditional",
        True,
        "compose dev default",
        "Postgres container password (compose). If visible in production, defaults/placeholders/short values rejected.",
    ),
    ConfigVar(
        "S3_ENDPOINT",
        "URL",
        "required",
        False,
        "http://localhost:9000",
        "S3-compatible endpoint (MinIO in compose).",
        "Private S3-compatible bucket storage",
    ),
    ConfigVar(
        "S3_ACCESS_KEY",
        "secret string",
        "required",
        True,
        "none (required in every environment)",
        "Object storage access key. Production: vendor defaults/placeholders rejected.",
    ),
    ConfigVar(
        "S3_SECRET_KEY",
        "secret string (>=16 chars)",
        "required",
        True,
        "none (required in every environment)",
        "Object storage secret key. Production: vendor defaults/placeholders/short values rejected.",
    ),
    ConfigVar(
        "MINIO_ROOT_USER",
        "string",
        "conditional",
        False,
        "compose dev default",
        "MinIO root user (compose). If visible in production, vendor defaults rejected.",
    ),
    ConfigVar(
        "MINIO_ROOT_PASSWORD",
        "secret string (>=16 chars)",
        "conditional",
        True,
        "compose dev default",
        "MinIO root password (compose). If visible in production, defaults/placeholders/short values rejected.",
    ),
    ConfigVar(
        "S3_BUCKET_RAW", "string", "optional", False, "trustcopilot-raw", "Bucket for uploads."
    ),
    ConfigVar(
        "S3_BUCKET_EXPORTS",
        "string",
        "optional",
        False,
        "trustcopilot-exports",
        "Bucket for exports.",
    ),
    ConfigVar("S3_USE_SSL", "bool", "optional", False, "false", "Use TLS to the S3 endpoint."),
    ConfigVar(
        "APP_BASE_URL",
        "https URL",
        "required",
        False,
        "http://localhost:3000",
        "Public base URL; OAuth redirect URIs are built from it. Production: https, not localhost.",
        "DNS record + TLS (Caddy ACME) for the public hostname",
    ),
    ConfigVar(
        "FRONTEND_URL",
        "https URL",
        "required",
        False,
        "http://localhost:3000",
        "Frontend origin for CORS/CSRF. Production: https, not localhost.",
    ),
    ConfigVar(
        "TRUSTED_ORIGINS",
        "comma-separated origins",
        "optional",
        False,
        "FRONTEND_URL (+ localhost variants outside production)",
        "CORS/CSRF allow-list. Production: every entry must be an https origin.",
    ),
    ConfigVar(
        "CORS_ORIGINS",
        "comma-separated origins",
        "optional",
        False,
        "unset",
        "Legacy alias of TRUSTED_ORIGINS.",
    ),
    ConfigVar(
        "OPENAI_API_KEY",
        "secret string",
        "required",
        True,
        "unset (AI features return 503/empty)",
        "Model/embedding provider key. Production: required, placeholders rejected.",
        "OpenAI (or configured provider) account",
    ),
    ConfigVar(
        "EMAIL_DELIVERY_ENABLED",
        "bool",
        "conditional",
        False,
        "auto: enabled when SMTP_HOST is set",
        "Whether the deployment sends email (verification, invites, password resets, notifications). "
        "true/1/yes/on or false/0/no/off; unset = enabled iff SMTP_HOST is set. Production with email "
        "enabled requires SMTP_HOST and SMTP_FROM; production with email disabled suppresses all email "
        "(never printed to logs).",
        "SMTP relay account (only if email is enabled)",
    ),
    ConfigVar(
        "SMTP_HOST",
        "hostname",
        "conditional",
        False,
        "unset (dev: emails printed to stdout)",
        "Outbound mail relay. Production: required when email delivery is enabled (see EMAIL_DELIVERY_ENABLED).",
        "SMTP relay account (only if email is enabled)",
    ),
    ConfigVar("SMTP_PORT", "int", "optional", False, "587", "SMTP port."),
    ConfigVar("SMTP_USE_TLS", "bool", "optional", False, "true", "STARTTLS."),
    ConfigVar("SMTP_USER", "string", "optional", False, "unset", "SMTP username."),
    ConfigVar(
        "SMTP_PASSWORD",
        "secret string",
        "optional",
        True,
        "unset",
        "SMTP password; placeholders rejected in production.",
    ),
    ConfigVar(
        "SMTP_FROM",
        "email",
        "conditional",
        False,
        "unset",
        "From address. Production: required when email delivery is enabled.",
    ),
    ConfigVar(
        "REDIS_URL",
        "URL",
        "optional",
        True,
        "unset (in-memory rate limiting)",
        "Shared rate-limit store.",
    ),
    ConfigVar(
        "RATE_LIMIT_RPM_PER_IP",
        "int >= 0",
        "optional",
        False,
        "120",
        "Per-IP request limit (0 disables).",
    ),
    ConfigVar(
        "TRUSTED_PROXY_IPS",
        "comma-separated IPs",
        "optional",
        False,
        "unset",
        "Proxies allowed to set X-Forwarded-For.",
    ),
    ConfigVar("MAX_UPLOAD_BYTES", "int > 0", "optional", False, "52428800", "Upload size limit."),
    ConfigVar(
        "EXPORT_ANSWER_COL_OFFSET", "int", "optional", False, "1", "Export answer column offset."
    ),
    ConfigVar(
        "AUDIT_RETENTION_DAYS",
        "int >= 0",
        "optional",
        False,
        "90",
        "Audit purge horizon (0 disables).",
    ),
    ConfigVar(
        "LOG_LEVEL",
        "enum(DEBUG|INFO|WARNING|ERROR|CRITICAL)",
        "optional",
        False,
        "INFO",
        "Log level.",
    ),
    ConfigVar("OPENAI_TEMPERATURE", "float", "optional", False, "0.35", "Completion temperature."),
    ConfigVar(
        "MAPPING_RERANK_MIN_CONFIDENCE",
        "float",
        "optional",
        False,
        "0.82",
        "Mapping rerank threshold.",
    ),
    ConfigVar(
        "OIDC_DEFAULT_WORKSPACE_ID",
        "int or 'default'",
        "optional",
        False,
        "1",
        "JIT SSO workspace.",
    ),
    ConfigVar(
        "OAUTH_GOOGLE_CLIENT_ID",
        "string",
        "optional",
        False,
        "unset",
        "Google OAuth (pair with secret).",
    ),
    ConfigVar(
        "OAUTH_GOOGLE_CLIENT_SECRET",
        "secret string",
        "optional",
        True,
        "unset",
        "Google OAuth secret.",
    ),
    ConfigVar(
        "OAUTH_GITHUB_CLIENT_ID",
        "string",
        "optional",
        False,
        "unset",
        "GitHub OAuth (pair with secret).",
    ),
    ConfigVar(
        "OAUTH_GITHUB_CLIENT_SECRET",
        "secret string",
        "optional",
        True,
        "unset",
        "GitHub OAuth secret.",
    ),
    ConfigVar(
        "OAUTH_MICROSOFT_CLIENT_ID",
        "string",
        "optional",
        False,
        "unset",
        "Microsoft OAuth (pair with secret).",
    ),
    ConfigVar(
        "OAUTH_MICROSOFT_CLIENT_SECRET",
        "secret string",
        "optional",
        True,
        "unset",
        "Microsoft OAuth secret.",
    ),
    ConfigVar(
        "OIDC_ISSUER_URL",
        "https URL",
        "optional",
        False,
        "unset",
        "Enterprise OIDC issuer (with client id/secret).",
    ),
    ConfigVar("OIDC_CLIENT_ID", "string", "optional", False, "unset", "OIDC client id."),
    ConfigVar(
        "OIDC_CLIENT_SECRET", "secret string", "optional", True, "unset", "OIDC client secret."
    ),
    ConfigVar(
        "IDME_CLIENT_ID",
        "string",
        "optional",
        False,
        "unset",
        "ID.me client id (pair with secret).",
    ),
    ConfigVar(
        "IDME_CLIENT_SECRET", "secret string", "optional", True, "unset", "ID.me client secret."
    ),
    ConfigVar(
        "STRIPE_SECRET_KEY",
        "secret string",
        "optional",
        True,
        "unset",
        "Billing; production requires STRIPE_WEBHOOK_SECRET or STRIPE_WEBHOOK_SECRETS with it.",
    ),
    ConfigVar(
        "STRIPE_WEBHOOK_SECRET",
        "secret string",
        "optional",
        True,
        "unset",
        "Stripe webhook signing secret.",
    ),
    ConfigVar(
        "STRIPE_WEBHOOK_SECRETS",
        "comma-separated secret strings",
        "optional",
        True,
        "unset",
        "Additional Stripe webhook signing secrets (rotation); merged with STRIPE_WEBHOOK_SECRET.",
    ),
    ConfigVar("SENTRY_DSN", "URL", "optional", True, "unset", "Error tracking."),
    # Health probes (TC-03-003; see docs/release/tickets/TC-03-003.md).
    ConfigVar("PORT", "int", "optional", False, "8000", "API port the container probe targets."),
    ConfigVar(
        "TC_PROCESS_ROLE",
        "enum(api|worker)",
        "optional",
        False,
        "api",
        "Selects the container health probe (`python -m app.probe`): API /healthz or worker heartbeat.",
    ),
    ConfigVar(
        "READINESS_TIMEOUT_SEC",
        "float (>=0.1)",
        "optional",
        False,
        "3",
        "Per-check DB/S3 timeout for /readyz; 503 when exceeded.",
    ),
    ConfigVar(
        "WORKER_HEARTBEAT_INTERVAL_SEC",
        "int",
        "optional",
        False,
        "15",
        "How often the worker refreshes its heartbeat.",
    ),
    ConfigVar(
        "WORKER_HEARTBEAT_STALE_SEC",
        "int",
        "optional",
        False,
        "120",
        "Heartbeat age after which /workerz and the worker probe report unhealthy.",
    ),
    ConfigVar(
        "WORKER_JOB_MAX_RUNTIME_SEC",
        "int",
        "optional",
        False,
        "3600",
        "A single job running longer than this stops refreshing the heartbeat.",
    ),
    ConfigVar(
        "WORKER_LOOP_STALL_SEC",
        "int",
        "optional",
        False,
        "120",
        "Claim-loop stall after which the heartbeat stops being refreshed.",
    ),
    ConfigVar(
        "WORKER_HEARTBEAT_FILE",
        "path",
        "optional",
        False,
        "/tmp/trustcopilot-worker.heartbeat",
        "Heartbeat file read by the worker container probe.",
    ),
    ConfigVar(
        "RETRIEVAL_MAX_THREADS",
        "int",
        "optional",
        False,
        "8",
        "Max worker threads for batched retrieval (1-32); also capped by the DB pool size.",
    ),
    ConfigVar(
        "TRUST_COPILOT_IN_DOCKER",
        "bool",
        "optional",
        False,
        "auto (/.dockerenv)",
        "Keeps `postgres` hostname in DATABASE_URL.",
    ),
    ConfigVar(
        "COMPLETION_MODEL", "string", "optional", False, "gpt-4o-mini", "Answer-generation model."
    ),
    ConfigVar(
        "MAPPING_LLM_RERANK", "bool", "optional", False, "1", "LLM rerank for control mapping."
    ),
    ConfigVar(
        "MAPPING_LLM_RERANK_BULK", "bool", "optional", False, "0", "LLM rerank for bulk mapping."
    ),
    ConfigVar(
        "MAPPING_RERANK_MODEL", "string", "optional", False, "COMPLETION_MODEL", "Rerank model."
    ),
    ConfigVar(
        "MAPPING_MODE",
        "enum(llm_structured|heuristic)",
        "optional",
        False,
        "llm_structured",
        "Mapping pipeline.",
    ),
    ConfigVar(
        "MAPPING_CLASSIFICATION_MODEL",
        "string",
        "optional",
        False,
        "COMPLETION_MODEL",
        "Classification model.",
    ),
    ConfigVar(
        "MAPPING_CLASSIFICATION_PROMPT_VERSION",
        "string",
        "optional",
        False,
        "v1",
        "Classification prompt version.",
    ),
    ConfigVar("MAPPING_TIMING", "bool", "optional", False, "unset", "Mapping timing logs."),
    ConfigVar("CONTROL_CATALOG", "bool", "optional", False, "1", "Normalized control catalog."),
    ConfigVar(
        "USE_PGVECTOR_INDEX", "bool", "optional", False, "1", "pgvector index for semantic search."
    ),
    ConfigVar(
        "USE_ADAPTIVE_CONCURRENCY",
        "bool",
        "optional",
        False,
        "0",
        "Adaptive answer-generation concurrency.",
    ),
    ConfigVar("OIDC_SCOPE", "string", "optional", False, "openid profile email", "OIDC scopes."),
    ConfigVar(
        "IDME_REDIRECT_PATH",
        "path",
        "optional",
        False,
        "/api/auth/idme/callback",
        "ID.me callback path.",
    ),
    ConfigVar("STRIPE_PRICE_ID", "string", "optional", False, "unset", "Stripe monthly price."),
    ConfigVar(
        "STRIPE_ANNUAL_PRICE_ID", "string", "optional", False, "unset", "Stripe annual price."
    ),
    # Billing tuning (TC-24-001); validated by the billing provider preflight, not duplicated here.
    ConfigVar("STRIPE_MODE", "test|live", "optional", False, "implied by key", "Stripe mode."),
    ConfigVar("STRIPE_MONTHLY_PLAN", "string", "optional", False, "pro", "Monthly plan name."),
    ConfigVar("STRIPE_ANNUAL_PLAN", "string", "optional", False, "pro_annual", "Annual plan name."),
    ConfigVar(
        "STRIPE_PLAN_PRICE_IDS",
        "plan=price list",
        "optional",
        False,
        "derived from price ids",
        "Plan to Stripe price id map.",
    ),
    ConfigVar(
        "STRIPE_WEBHOOK_TOLERANCE_SECONDS",
        "integer >= 0",
        "optional",
        False,
        "300",
        "Webhook timestamp tolerance.",
    ),
    ConfigVar(
        "STRIPE_EVENT_RETENTION_SECONDS",
        "integer >= 0",
        "optional",
        False,
        "604800",
        "Processed webhook event retention.",
    ),
    # Message providers (TC-19-001); validated by message_providers.selection preflight.
    ConfigVar(
        "MESSAGE_PROVIDER_RUNTIME_MODE",
        "production|development",
        "optional",
        False,
        "follows APP_ENV",
        "Slack/Gmail provider runtime mode.",
    ),
    ConfigVar(
        "MESSAGE_PROVIDER_DEV_STUB",
        "boolean",
        "optional",
        False,
        "unset",
        "Development message-provider stub; production preflight refuses it.",
    ),
    ConfigVar(
        "SENTRY_ENVIRONMENT", "string", "optional", False, "APP_ENV", "Sentry environment tag."
    ),
    ConfigVar("SENTRY_RELEASE", "string", "optional", False, "unset", "Sentry release tag."),
    # Development / demo / test switches that production refuses outright.
    ConfigVar(
        "TRUST_COPILOT_DEV_RETURN_RESET_URL",
        "bool",
        "forbidden",
        False,
        "unset",
        "Dev only: returns reset links in API responses.",
    ),
    ConfigVar("TRUST_COPILOT_TESTING", "bool", "forbidden", False, "unset", "Test harness switch."),
    ConfigVar(
        "TRUST_COPILOT_E2E_RUNNER",
        "bool",
        "forbidden",
        False,
        "unset",
        "Full-stack E2E runner switch (changes .env precedence).",
    ),
    ConfigVar(
        "TRUST_COPILOT_DEBUG_NDJSON", "path", "forbidden", False, "unset", "Debug session log file."
    ),
    ConfigVar(
        "TC_ALLOW_PRODUCTION_SEED",
        "bool",
        "forbidden",
        False,
        "unset",
        "Removed override; demo/QA seeding is never allowed in production.",
    ),
    ConfigVar(
        "TC_SEED_DEMO_PASSWORD",
        "secret string",
        "forbidden",
        True,
        "generated",
        "Seed-account password (local/QA only).",
    ),
    ConfigVar(
        "TC_SEED_ADMIN_PASSWORD",
        "secret string",
        "forbidden",
        True,
        "generated",
        "Seed-account password (local/QA only).",
    ),
    ConfigVar(
        "TC_SEED_EDITOR_PASSWORD",
        "secret string",
        "forbidden",
        True,
        "generated",
        "Seed-account password (local/QA only).",
    ),
    ConfigVar(
        "TC_SEED_REVIEWER_PASSWORD",
        "secret string",
        "forbidden",
        True,
        "generated",
        "Seed-account password (local/QA only).",
    ),
    ConfigVar(
        "TC_SEED_SUSPENDED_PASSWORD",
        "secret string",
        "forbidden",
        True,
        "generated",
        "Seed-account password (local/QA only).",
    ),
    ConfigVar(
        "TC_SEED_RESET_PASSWORDS",
        "bool",
        "forbidden",
        False,
        "unset",
        "Resets seed-account passwords (local only).",
    ),
    ConfigVar(
        "TC_SESSION_SECRET",
        "secret string",
        "forbidden",
        True,
        "unset",
        "Live-API script helper (local stacks only).",
    ),
    ConfigVar(
        "NEXT_PUBLIC_DEMO_LOGIN_EMAIL",
        "email",
        "forbidden",
        False,
        "unset",
        "One-click demo login (build-time, local demo only).",
    ),
    ConfigVar(
        "NEXT_PUBLIC_DEMO_LOGIN_PASSWORD",
        "secret string",
        "forbidden",
        True,
        "unset",
        "One-click demo login (build-time, local demo only).",
    ),
)

CONTRACT_BY_NAME = {v.name: v for v in CONTRACT}
FORBIDDEN_IN_PRODUCTION = tuple(v.name for v in CONTRACT if v.production == "forbidden")
_OAUTH_PAIRS = (
    ("OAUTH_GOOGLE_CLIENT_ID", "OAUTH_GOOGLE_CLIENT_SECRET"),
    ("OAUTH_GITHUB_CLIENT_ID", "OAUTH_GITHUB_CLIENT_SECRET"),
    ("OAUTH_MICROSOFT_CLIENT_ID", "OAUTH_MICROSOFT_CLIENT_SECRET"),
    ("OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET"),
    ("IDME_CLIENT_ID", "IDME_CLIENT_SECRET"),
)
_INT_VARS = {
    "MAX_UPLOAD_BYTES": 1,
    "EXPORT_ANSWER_COL_OFFSET": None,
    "AUDIT_RETENTION_DAYS": 0,
    "RATE_LIMIT_RPM_PER_IP": 0,
    "SMTP_PORT": 1,
}
_FLOAT_VARS = ("OPENAI_TEMPERATURE", "MAPPING_RERANK_MIN_CONFIDENCE")
# Crash Settings() at import if malformed, so they are errors in every environment.
_ALWAYS_FATAL_TYPES = ("MAX_UPLOAD_BYTES", "EXPORT_ANSWER_COL_OFFSET", "OIDC_DEFAULT_WORKSPACE_ID")


@dataclass(frozen=True)
class Problem:
    name: str
    reason: str
    fatal: bool = True

    def __str__(self) -> str:  # never includes a value
        return f"{self.name}: {self.reason}"


class ConfigContractError(RuntimeError):
    def __init__(self, problems: Iterable[Problem], role: str = "api"):
        self.problems = [p for p in problems if p.fatal]
        lines = "\n".join(f"  - {p}" for p in self.problems)
        super().__init__(
            f"Refusing to start ({role}, APP_ENV=production): configuration contract violated "
            f"(values not shown; see docs/release/config-contract.md):\n{lines}"
        )


def _is_marker_token(token: str) -> bool:
    return (
        token in _PLACEHOLDER_MARKER_TOKENS
        or (len(token) >= 3 and set(token) == {"x"})
        or "<" in token
        or ">" in token
    )


def is_known_default_or_placeholder(value: str | None) -> bool:
    """True for unset values, shipped/vendor defaults and documentation placeholders.

    Matching is on the whole value (case-insensitive), never on substrings, so strong random
    secrets are not refused because they happen to contain a marker word. Marker words count
    only as whole tokens, and only when what remains is too short or too repetitive to be a
    generated credential.
    """
    if value is None:
        return True
    raw = value.strip()
    v = raw.lower()
    if not v:
        return True
    if v in KNOWN_DEFAULT_CREDENTIALS or v in _EXACT_PLACEHOLDERS:
        return True
    if v.startswith("<") and v.endswith(">"):  # e.g. <secret>, <your api key>
        return True
    if set(v) <= {"x", "*", "-", "_", "."}:  # e.g. xxxx, ****
        return True
    raw_tokens = [t for t in _TOKEN_SPLIT.split(raw) if t]
    if not any(_is_marker_token(t.lower()) for t in raw_tokens):
        return False
    # Remaining material: drop marker tokens and plain lower-case words ("key", "here", ...).
    rest = "".join(
        t
        for t in raw_tokens
        if not _is_marker_token(t.lower()) and not (t.isalpha() and t == t.lower())
    )
    return len(rest) < _MIN_RANDOM_MATERIAL or len(set(rest)) < 6


def _weak_password(
    value: str | None, min_length: int = MIN_PRODUCTION_PASSWORD_LENGTH
) -> str | None:
    """Return a reason string if ``value`` is not acceptable as a production credential."""
    if value is None or not value.strip():
        return "is unset or empty"
    if is_known_default_or_placeholder(value):
        return "is a known default or placeholder"
    if len(value.strip()) < min_length:
        return f"is shorter than {min_length} characters"
    if len(set(value)) < 6:
        return "has too little variety to be a generated credential"
    return None


def _check_url(name: str, raw: str | None, problems: list[Problem]) -> None:
    if not raw or not raw.strip():
        problems.append(Problem(name, "is required in production"))
        return
    try:
        parts = urlsplit(raw.strip())
    except ValueError:
        problems.append(Problem(name, "is not a valid URL"))
        return
    if parts.scheme != "https":
        problems.append(Problem(name, "must use https in production"))
    host = (parts.hostname or "").lower()
    if (
        not host
        or host in ("localhost", "127.0.0.1", "::1", "0.0.0.0")
        or host.endswith(".localhost")
    ):
        problems.append(Problem(name, "must be a public hostname in production (not localhost)"))


def _check_database_url(env: Mapping[str, str], problems: list[Problem]) -> None:
    raw = env.get("DATABASE_URL", "")
    if not raw or not raw.strip():
        problems.append(
            Problem(
                "DATABASE_URL", "must be set explicitly in production (the dev default is refused)"
            )
        )
        return
    try:
        parts = urlsplit(raw.strip())
        user, password, host = parts.username, parts.password, parts.hostname
    except ValueError:
        problems.append(Problem("DATABASE_URL", "is not a valid URL"))
        return
    if not parts.scheme.startswith("postgres"):
        problems.append(Problem("DATABASE_URL", "must be a postgresql:// URL"))
    if not host:
        problems.append(Problem("DATABASE_URL", "has no host"))
    if not user:
        problems.append(Problem("DATABASE_URL", "has no username"))
    reason = _weak_password(password)
    if reason:
        problems.append(Problem("DATABASE_URL", f"password {reason}"))
    elif user and password and password.strip().lower() == user.strip().lower():
        problems.append(Problem("DATABASE_URL", "password equals the username"))


def _parse_int(name: str, raw: str) -> bool:
    try:
        int(raw.strip())
        return True
    except ValueError:
        return False


_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")


def _parse_email_flag(raw: str | None) -> str:
    v = (raw or "").strip().lower()
    if not v:
        return "auto"
    if v in _TRUE:
        return "on"
    if v in _FALSE:
        return "off"
    return "invalid"


def email_delivery_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Single source of truth for whether this deployment sends email.

    EMAIL_DELIVERY_ENABLED=true/false wins; unset means "enabled iff SMTP_HOST is set" (the pre-existing
    behaviour of email_service.get_email_provider). An unparseable value counts as enabled (fail closed:
    production then requires SMTP), and is reported separately as a type problem.
    """
    env = os.environ if env is None else env
    flag = _parse_email_flag(env.get("EMAIL_DELIVERY_ENABLED"))
    if flag == "on" or flag == "invalid":
        return True
    if flag == "off":
        return False
    return bool((env.get("SMTP_HOST") or "").strip())


def validate_environment(env: Mapping[str, str] | None = None) -> list[Problem]:
    """Return contract problems for ``env`` (defaults to os.environ). Never includes values.

    Production is decided by app.core.session.is_production_env (whitespace/case-insensitive):
    for the running process (``env`` None) that is the same check the startup secret gate uses.
    """
    production = is_production_env(env)
    env = os.environ if env is None else env
    problems: list[Problem] = []
    app_env = (env.get("APP_ENV") or "development").strip().lower()

    if app_env not in ALLOWED_APP_ENVS:
        problems.append(Problem("APP_ENV", f"must be one of {', '.join(ALLOWED_APP_ENVS)}"))

    # Types (fatal where Settings() would crash; otherwise fatal only in production).
    for name, minimum in _INT_VARS.items():
        raw = env.get(name)
        if raw is None or raw.strip() == "":
            continue
        if not _parse_int(name, raw):
            problems.append(
                Problem(name, "must be an integer", fatal=production or name in _ALWAYS_FATAL_TYPES)
            )
        elif minimum is not None and int(raw.strip()) < minimum:
            problems.append(Problem(name, f"must be >= {minimum}", fatal=production))
    raw_ws = env.get("OIDC_DEFAULT_WORKSPACE_ID")
    if (
        raw_ws
        and raw_ws.strip().lower() not in ("", "default")
        and not _parse_int("OIDC_DEFAULT_WORKSPACE_ID", raw_ws)
    ):
        problems.append(Problem("OIDC_DEFAULT_WORKSPACE_ID", "must be an integer or 'default'"))
    for name in _FLOAT_VARS:
        raw = env.get(name)
        if raw and raw.strip():
            try:
                float(raw)
            except ValueError:
                problems.append(Problem(name, "must be a number", fatal=production))
    if _parse_email_flag(env.get("EMAIL_DELIVERY_ENABLED")) == "invalid":
        problems.append(
            Problem(
                "EMAIL_DELIVERY_ENABLED",
                "must be true/false (1/0, yes/no, on/off) or unset",
                fatal=production,
            )
        )
    lvl = env.get("LOG_LEVEL")
    if (
        lvl
        and lvl.strip()
        and lvl.strip().upper() not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
    ):
        problems.append(
            Problem(
                "LOG_LEVEL", "must be DEBUG, INFO, WARNING, ERROR or CRITICAL", fatal=production
            )
        )

    if not production:
        return problems

    # --- Production: signing, storage and database credentials (fail closed) ---
    if is_weak_secret(env.get("SESSION_SECRET")):
        problems.append(
            Problem(
                "SESSION_SECRET",
                f"must be a random value of at least {MIN_PRODUCTION_SECRET_LENGTH} "
                "characters (unset, short or placeholder values are refused)",
            )
        )
    _check_database_url(env, problems)

    access = env.get("S3_ACCESS_KEY")
    if not access or not access.strip():
        problems.append(Problem("S3_ACCESS_KEY", "is required in production"))
    elif is_known_default_or_placeholder(access):
        problems.append(Problem("S3_ACCESS_KEY", "is a known default or placeholder"))
    reason = _weak_password(env.get("S3_SECRET_KEY"))
    if reason:
        problems.append(Problem("S3_SECRET_KEY", reason))
    endpoint = env.get("S3_ENDPOINT")
    if not endpoint or not endpoint.strip():
        problems.append(Problem("S3_ENDPOINT", "is required in production"))

    # Container credentials, checked whenever they are visible to this process (compose env_file).
    for name in ("POSTGRES_PASSWORD", "MINIO_ROOT_PASSWORD"):
        if name in env:
            reason = _weak_password(env.get(name))
            if reason:
                problems.append(Problem(name, reason))
    for name in ("POSTGRES_USER", "MINIO_ROOT_USER"):
        if (
            name in env
            and name == "MINIO_ROOT_USER"
            and is_known_default_or_placeholder(env.get(name))
        ):
            problems.append(Problem(name, "is a known default or placeholder"))
        elif name in env and not (env.get(name) or "").strip():
            problems.append(Problem(name, "is empty"))

    # --- Public URLs ---
    _check_url("APP_BASE_URL", env.get("APP_BASE_URL"), problems)
    _check_url("FRONTEND_URL", env.get("FRONTEND_URL"), problems)
    for list_name in ("TRUSTED_ORIGINS", "CORS_ORIGINS"):
        raw = env.get(list_name, "")
        for origin in [o.strip() for o in raw.split(",") if o.strip()]:
            if not origin.lower().startswith("https://"):
                problems.append(Problem(list_name, "every origin must use https in production"))
                break

    # --- Owner-account prerequisites ---
    api_key = env.get("OPENAI_API_KEY")
    if not api_key or not api_key.strip():
        problems.append(
            Problem("OPENAI_API_KEY", "is required in production (model provider account)")
        )
    elif is_known_default_or_placeholder(api_key):
        problems.append(Problem("OPENAI_API_KEY", "is a placeholder"))
    if email_delivery_enabled(env):
        if not (env.get("SMTP_HOST") or "").strip():
            problems.append(
                Problem("SMTP_HOST", "is required in production when email delivery is enabled")
            )
        if not (env.get("SMTP_FROM") or "").strip():
            problems.append(
                Problem("SMTP_FROM", "is required in production when email delivery is enabled")
            )
    if (env.get("SMTP_PASSWORD") or "").strip() and is_known_default_or_placeholder(
        env.get("SMTP_PASSWORD")
    ):
        problems.append(Problem("SMTP_PASSWORD", "is a known default or placeholder"))
    for cid, csec in _OAUTH_PAIRS:
        has_id, has_sec = bool((env.get(cid) or "").strip()), bool((env.get(csec) or "").strip())
        if has_id != has_sec:
            problems.append(
                Problem(
                    cid if not has_id else csec,
                    f"must be set together with {csec if has_id else cid}",
                )
            )
        elif has_sec and is_known_default_or_placeholder(env.get(csec)):
            problems.append(Problem(csec, "is a placeholder"))
    if (env.get("OIDC_CLIENT_ID") or "").strip() and not (env.get("OIDC_ISSUER_URL") or "").strip():
        problems.append(Problem("OIDC_ISSUER_URL", "is required when OIDC_CLIENT_ID is set"))
    for name in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_WEBHOOK_SECRETS"):
        raw = env.get(name) or ""
        items = (
            [i.strip() for i in raw.split(",")]
            if name == "STRIPE_WEBHOOK_SECRETS"
            else [raw.strip()]
        )
        if raw.strip() and any(not i or is_known_default_or_placeholder(i) for i in items):
            problems.append(Problem(name, "is a known default or placeholder"))
    if (env.get("STRIPE_SECRET_KEY") or "").strip() and not any(
        (env.get(n) or "").strip() for n in ("STRIPE_WEBHOOK_SECRET", "STRIPE_WEBHOOK_SECRETS")
    ):
        problems.append(
            Problem(
                "STRIPE_WEBHOOK_SECRET",
                "is required (or STRIPE_WEBHOOK_SECRETS) when STRIPE_SECRET_KEY is set",
            )
        )

    # --- Dev / demo / test switches and demo seeding ---
    for name in FORBIDDEN_IN_PRODUCTION:
        raw = env.get(name)
        if (
            raw is not None
            and raw.strip()
            and raw.strip().lower() not in ("0", "false", "no", "off")
        ):
            problems.append(Problem(name, "is not allowed in production (dev/demo/test only)"))

    return problems


def enforce_startup_contract(
    role: str = "api", env: Mapping[str, str] | None = None
) -> list[Problem]:
    """Validate the environment at process start.

    Production: raise ConfigContractError on any fatal problem (fail closed).
    Non-production: raise only for problems that would crash anyway; return the rest as warnings.
    """
    production = is_production_env(env)
    problems = validate_environment(env)
    fatal = [p for p in problems if p.fatal]
    if fatal and (
        production or any(p.name in _ALWAYS_FATAL_TYPES or p.name == "APP_ENV" for p in fatal)
    ):
        raise ConfigContractError(fatal, role)
    return problems


def refuse_demo_seed_in_production(env: Mapping[str, str] | None = None) -> None:
    """Demo/QA/E2E seeding is never allowed with APP_ENV=production (no override)."""
    if is_production_env(env):
        raise SystemExit(
            "Refusing to seed demo/QA/E2E data with APP_ENV=production. "
            "Production accounts are created through the invitation/owner bootstrap flow, never by seed scripts."
        )


def contract_markdown() -> str:
    rows = [
        "| Variable | Type | Production | Secret | Non-production default | Description | Owner prerequisite |",
        "|---|---|---|---|---|---|---|",
    ]
    for v in CONTRACT:
        rows.append(
            f"| `{v.name}` | {v.type} | {v.production} | {'yes' if v.secret else 'no'} | {v.default} | "
            f"{v.description} | {v.prerequisite} |"
        )
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    cmd = args[0] if args else "check"
    if cmd == "markdown":
        sys.stdout.write(contract_markdown())
        return 0
    if cmd == "check":
        role = args[1] if len(args) > 1 else "entrypoint"
        try:
            problems = enforce_startup_contract(role)
        except ConfigContractError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        for p in problems:
            print(f"config warning: {p}", file=sys.stderr)
        print(
            f"config contract: ok ({role}, APP_ENV={(os.environ.get('APP_ENV') or 'development').lower()})"
        )
        return 0
    print("usage: python -m app.core.config_contract [check [role] | markdown]", file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
