"""Application configuration from environment."""

import os
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit, urlparse


def _normalize_origin(origin: str | None) -> str | None:
    """Return a canonical origin (scheme + host + port, no path, lowercase) or None."""
    if not origin or not origin.strip():
        return None
    o = origin.strip().lower()
    if not o.startswith("http://") and not o.startswith("https://"):
        return None
    try:
        parsed = urlparse(o)
        if not parsed.scheme or not parsed.hostname:
            return None
        host = parsed.hostname.lower()
        # IPv6 must be bracketed in URL authority (urlparse.hostname is unbracketed)
        if ":" in host:
            host = f"[{host}]"
        port = parsed.port
        if port is None:
            return f"{parsed.scheme}://{host}"
        if (parsed.scheme == "https" and port == 443) or (parsed.scheme == "http" and port == 80):
            return f"{parsed.scheme}://{host}"
        return f"{parsed.scheme}://{host}:{port}"
    except Exception:
        return None


def _rewrite_postgres_docker_hostname_to_localhost(url: str, in_docker: bool) -> str:
    """Docker Compose uses hostname 'postgres'; on the host OS that name does not resolve.

    Rewrite to localhost when not running inside a container. Uses URL parsing so host
    matching is case-insensitive (e.g. @Postgres:5432) and works with +driver schemes.

    Note: urlsplit().hostname is lowercased, but netloc may still contain mixed-case host;
    we parse the host:port segment after the last '@' so replacement matches the real netloc.
    """
    if in_docker or not url or not url.strip():
        return url
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url
    if not parts.hostname or parts.hostname.lower() != "postgres":
        return url
    netloc = parts.netloc
    userinfo, _, hostport = netloc.rpartition("@")
    if not hostport:
        return url
    if ":" in hostport:
        host_only, port_str = hostport.rsplit(":", 1)
        if not port_str.isdigit():
            return url
        if host_only.lower() != "postgres":
            return url
        new_hostport = f"localhost:{port_str}"
    else:
        if hostport.lower() != "postgres":
            return url
        new_hostport = "localhost"
    new_netloc = f"{userinfo}@{new_hostport}" if userinfo else new_hostport
    return urlunsplit((parts.scheme, new_netloc, parts.path, parts.query, parts.fragment))


@lru_cache
def get_settings():
    """Load and cache settings from env."""
    return Settings()


class Settings:
    """Application settings."""

    def __init__(self):
        raw = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/trustcopilot")
        # When API runs on host, "postgres" hostname (Docker) doesn't resolve; use localhost.
        # When API runs inside Docker, keep "postgres" so it resolves to the postgres container.
        in_docker = os.path.exists("/.dockerenv") or os.environ.get("TRUST_COPILOT_IN_DOCKER") == "1"
        self.database_url: str = _rewrite_postgres_docker_hostname_to_localhost(raw, in_docker)
        self.session_secret: str = os.getenv("SESSION_SECRET", "change_me_dev_secret")
        self.app_base_url: str = os.getenv("APP_BASE_URL", "http://localhost:3000")
        self.frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:3000")

        self.s3_endpoint: str = os.getenv("S3_ENDPOINT", "http://localhost:9000")
        self.s3_access_key: str = os.getenv("S3_ACCESS_KEY", "minio")
        self.s3_secret_key: str = os.getenv("S3_SECRET_KEY", "minio123")
        self.s3_bucket_raw: str = os.getenv("S3_BUCKET_RAW", "trustcopilot-raw")
        self.s3_bucket_exports: str = os.getenv("S3_BUCKET_EXPORTS", "trustcopilot-exports")
        self.s3_use_ssl: bool = os.getenv("S3_USE_SSL", "false").lower() == "true"

        self.openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
        # Completion model and tone controls for answer generation
        self.completion_model: str = os.getenv("COMPLETION_MODEL", "gpt-4o-mini")
        try:
            self.openai_temperature: float = float(os.getenv("OPENAI_TEMPERATURE", "0.35"))
        except ValueError:
            self.openai_temperature = 0.35
        self.export_answer_col_offset: int = int(os.getenv("EXPORT_ANSWER_COL_OFFSET", "1"))
        self.max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))

        # Post-heuristic LLM re-rank for question_to_controls (optional; falls back on failure)
        _mllm = os.getenv("MAPPING_LLM_RERANK", "1").lower()
        self.mapping_llm_rerank_enabled: bool = _mllm not in ("0", "false", "no")
        self.mapping_rerank_model: str = os.getenv("MAPPING_RERANK_MODEL") or self.completion_model
        try:
            self.mapping_rerank_min_confidence: float = float(os.getenv("MAPPING_RERANK_MIN_CONFIDENCE", "0.82"))
        except ValueError:
            self.mapping_rerank_min_confidence = 0.82
        # When true, bulk POST /generate-mappings runs LLM rerank (slow). Default false: heuristic only for bulk.
        _mbulk = os.getenv("MAPPING_LLM_RERANK_BULK", "0").lower()
        self.mapping_llm_rerank_bulk: bool = _mbulk in ("1", "true", "yes")

        # Normalized control catalog (JSON sidecar) for mapping retrieval + LLM rerank
        _ccat = os.getenv("CONTROL_CATALOG", "1").lower()
        self.control_catalog_enabled: bool = _ccat not in ("0", "false", "no")

        # Structured LLM classification per question during generate-mappings (enterprise pipeline).
        # MAPPING_MODE: 'llm_structured' (default prod — LLM every question), 'heuristic' (legacy).
        _mmode = os.getenv("MAPPING_MODE", "llm_structured").lower()
        self.mapping_mode: str = _mmode if _mmode in ("llm_structured", "heuristic") else "llm_structured"
        self.mapping_classification_model: str = os.getenv("MAPPING_CLASSIFICATION_MODEL") or self.completion_model
        self.mapping_classification_prompt_version: str = os.getenv("MAPPING_CLASSIFICATION_PROMPT_VERSION", "v1")

        # OAuth (ENT-201) - optional; leave unset to hide OAuth buttons
        self.oauth_google_client_id: str | None = os.getenv("OAUTH_GOOGLE_CLIENT_ID")
        self.oauth_google_client_secret: str | None = os.getenv("OAUTH_GOOGLE_CLIENT_SECRET")
        self.oauth_github_client_id: str | None = os.getenv("OAUTH_GITHUB_CLIENT_ID")
        self.oauth_github_client_secret: str | None = os.getenv("OAUTH_GITHUB_CLIENT_SECRET")
        self.oauth_microsoft_client_id: str | None = os.getenv("OAUTH_MICROSOFT_CLIENT_ID")
        self.oauth_microsoft_client_secret: str | None = os.getenv("OAUTH_MICROSOFT_CLIENT_SECRET")

        # Auth0 / Enterprise OIDC SSO (ENT-203) - optional
        self.oidc_issuer_url: str | None = os.getenv("OIDC_ISSUER_URL")
        self.oidc_client_id: str | None = os.getenv("OIDC_CLIENT_ID")
        self.oidc_client_secret: str | None = os.getenv("OIDC_CLIENT_SECRET")
        self.oidc_scope: str = os.getenv("OIDC_SCOPE", "openid profile email")
        # Workspace for JIT SSO users when no claim mapping (default workspace id)
        _oidc_ws = os.getenv("OIDC_DEFAULT_WORKSPACE_ID", "1").strip().lower()
        self.oidc_default_workspace_id: int = 1 if _oidc_ws in ("", "default") else int(_oidc_ws)

        # id.me (ENT-205, ENT-206) - optional; sandbox first
        self.idme_client_id: str | None = os.getenv("IDME_CLIENT_ID")
        self.idme_client_secret: str | None = os.getenv("IDME_CLIENT_SECRET")
        self.idme_redirect_path: str = os.getenv("IDME_REDIRECT_PATH", "/api/auth/idme/callback")

        # Use pgvector index for semantic search when True (requires migration 024)
        self.use_pgvector_index: bool = os.getenv("USE_PGVECTOR_INDEX", "1").lower() in ("1", "true", "yes")

        # Phase 4: adaptive concurrency for answer generation (wave-based, 2-6 workers). Default off for stability.
        self.use_adaptive_concurrency: bool = os.getenv("USE_ADAPTIVE_CONCURRENCY", "0").lower() in ("1", "true", "yes")

        # Redis for rate limiting in production (optional; uses in-memory when unset)
        self.redis_url: str | None = os.getenv("REDIS_URL")

        # Global API rate limit: requests per minute per IP (0 = disabled)
        _rpm = os.getenv("RATE_LIMIT_RPM_PER_IP", "120").strip()
        self.rate_limit_rpm_per_ip: int = max(0, int(_rpm)) if _rpm.isdigit() else 120

        self.app_env: str = os.getenv("APP_ENV", "development").lower()
        # Audit retention: delete events older than this many days (0 = disable purge)
        _audit_days = os.getenv("AUDIT_RETENTION_DAYS", "90").strip()
        self.audit_retention_days: int = max(0, int(_audit_days)) if _audit_days.isdigit() else 90

        # Log level for app (e.g. INFO, DEBUG); structured JSON to stdout when APP_ENV=production
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"

        # Stripe billing (Phase 2)
        self.stripe_secret_key: str | None = os.getenv("STRIPE_SECRET_KEY", "").strip() or None
        self.stripe_webhook_secret: str | None = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip() or None
        self.stripe_price_id: str | None = os.getenv("STRIPE_PRICE_ID", "").strip() or None
        self.stripe_annual_price_id: str | None = os.getenv("STRIPE_ANNUAL_PRICE_ID", "").strip() or None
        # Sentry: set SENTRY_DSN to enable error tracking (optional)
        self.sentry_dsn: str | None = os.getenv("SENTRY_DSN", "").strip() or None
        self.sentry_environment: str = os.getenv("SENTRY_ENVIRONMENT", "").strip() or self.app_env
        self.sentry_release: str | None = os.getenv("SENTRY_RELEASE", "").strip() or None

        # Trusted frontend origins: used for CORS and CSRF (SEC-201). Single source of truth.
        # TRUSTED_ORIGINS = comma-separated list (e.g. "https://app.example.com,https://admin.example.com").
        # If unset, CORS_ORIGINS is used for backward compatibility.
        # If both unset: development = [FRONTEND_URL] + common localhost variants; production = [FRONTEND_URL] only.
        _trusted_raw = os.getenv("TRUSTED_ORIGINS", "").strip()
        if _trusted_raw:
            _origins = [o.strip() for o in _trusted_raw.split(",") if o.strip()]
            _normalized = [_normalize_origin(o) for o in _origins if _normalize_origin(o)]
            self.trusted_origins: list[str] = list(dict.fromkeys(_normalized))
            # Non-production: also allow common local origins so TRUSTED_ORIGINS from a
            # prod template does not break cookie auth + CSRF on localhost.
            if self.app_env != "production":
                _dev_defaults = [
                    "https://localhost",
                    "https://localhost:3000",
                    "https://127.0.0.1",
                    "https://127.0.0.1:3000",
                    "http://localhost",
                    "http://localhost:3000",
                    "http://127.0.0.1",
                    "http://127.0.0.1:3000",
                    "http://[::1]",
                    "http://[::1]:3000",
                ]
                self.trusted_origins = list(dict.fromkeys(self.trusted_origins + _dev_defaults))
        else:
            _cors_legacy = os.getenv("CORS_ORIGINS", "").strip()
            if _cors_legacy:
                _origins = [o.strip() for o in _cors_legacy.split(",") if o.strip()]
                _normalized = [_normalize_origin(o) for o in _origins if _normalize_origin(o)]
                self.trusted_origins = list(dict.fromkeys(_normalized))
                if self.app_env != "production":
                    _dev_defaults = [
                        "https://localhost",
                        "https://localhost:3000",
                        "https://127.0.0.1",
                        "https://127.0.0.1:3000",
                        "http://localhost",
                        "http://localhost:3000",
                        "http://127.0.0.1",
                        "http://127.0.0.1:3000",
                        "http://[::1]",
                        "http://[::1]:3000",
                    ]
                    self.trusted_origins = list(dict.fromkeys(self.trusted_origins + _dev_defaults))
            else:
                _frontend = _normalize_origin(self.frontend_url)
                _base = [_frontend] if _frontend else []
                if self.app_env == "production":
                    self.trusted_origins = _base if _base else []
                else:
                    _dev_defaults = [
                        "https://localhost",
                        "https://localhost:3000",
                        "https://127.0.0.1",
                        "https://127.0.0.1:3000",
                        "http://localhost",
                        "http://localhost:3000",
                        "http://127.0.0.1",
                        "http://127.0.0.1:3000",
                        "http://[::1]",
                        "http://[::1]:3000",
                    ]
                    self.trusted_origins = list(dict.fromkeys(_base + _dev_defaults))

        # CORS uses the same list as CSRF (kept for backward compatibility of the attribute name).
        self.cors_origins: list[str] = self.trusted_origins
