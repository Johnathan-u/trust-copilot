import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Env load order (must match database.py when DB is running): api/.env first (override), then repo .env.
# In Docker we skip so compose env (DATABASE_URL, S3_*, etc.) is used.
_api_root = Path(__file__).resolve().parent.parent
_repo_root = _api_root.parent.parent
_in_docker = Path("/.dockerenv").exists() or os.environ.get("TRUST_COPILOT_IN_DOCKER") == "1"
_in_test = os.environ.get("TRUST_COPILOT_TESTING") == "1"
# Full-stack E2E runner injects FRONTEND_URL / TRUSTED_ORIGINS; do not let api/.env override them.
_e2e_runner = os.environ.get("TRUST_COPILOT_E2E_RUNNER") == "1"
if not _in_docker and not _in_test:
    load_dotenv(_api_root / ".env", override=not _e2e_runner)
    load_dotenv(_repo_root / ".env", override=False)

# Bootstrap: ensure DB/config are initialized with current env before any route or config consumer runs.
import app.core.database  # noqa: E402

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging_config import configure_logging, request_id_ctx, workspace_id_ctx
from app.core.metrics import record_request as metrics_record_request
from app.core.rate_limit import get_client_ip, is_rate_limited, record_attempt
from app.api.routes import auth as auth_router
from app.api.routes import members as members_router
from app.api.routes import workspaces as workspaces_router
from app.core.csrf import is_csrf_safe
from app.api.routes import answers as answers_router
from app.api.routes import documents as documents_router
from app.api.routes import exports as exports_router
from app.api.routes import jobs as jobs_router
from app.api.routes import questionnaires as questionnaires_router
from app.api.routes import search as search_router
from app.api.routes import trust_articles as trust_articles_router
from app.api.routes import trust_requests as trust_requests_router
from app.api.routes import controls as controls_router
from app.api.routes import compliance_controls as compliance_controls_router
from app.api.routes import compliance_evidence as compliance_evidence_router
from app.api.routes import compliance_frameworks as compliance_frameworks_router
from app.api.routes import compliance_mappings as compliance_mappings_router
from app.api.routes import compliance_gaps as compliance_gaps_router
from app.api.routes import compliance_coverage as compliance_coverage_router
from app.api.routes import compliance_alerts as compliance_alerts_router
from app.api.routes import compliance_export as compliance_export_router
from app.api.routes import compliance_audit as compliance_audit_router
from app.api.routes import vendor_requests as vendor_requests_router
from app.api.routes import audit as audit_router
from app.api.routes import notifications as notifications_router
from app.api.routes import slack as slack_router
from app.api.routes import slack_ingest as slack_ingest_router
from app.api.routes import in_app_notifications as in_app_notifications_router
from app.api.routes import gmail as gmail_router
from app.api.routes import dashboard_cards as dashboard_cards_router
from app.api.routes import tags as tags_router
from app.api.routes import ai_mappings as ai_mappings_router
from app.api.routes import ai_insights as ai_insights_router
from app.services.storage import StorageClient


def _init_sentry() -> None:
    """Initialize Sentry when SENTRY_DSN is set. Scrubs cookies and Authorization from events."""
    s = get_settings()
    if not s.sentry_dsn:
        return
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration

    def before_send(event: dict, hint: dict) -> dict | None:
        # Do not send request cookies or Authorization header
        if "request" in event:
            event["request"].pop("cookies", None)
            headers = event["request"].get("headers") or {}
            if isinstance(headers, dict):
                headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}
            else:
                headers = [(k, v) for k, v in headers if k.lower() != "authorization"]
            event["request"]["headers"] = headers
        return event

    sentry_sdk.init(
        dsn=s.sentry_dsn,
        environment=s.sentry_environment,
        release=s.sentry_release,
        integrations=[FastApiIntegration()],
        traces_sample_rate=0.1,
        before_send=before_send,
    )


_init_sentry()


def _verify_db_connectivity():
    """Fail fast at startup if DB is unreachable (industry best practice)."""
    import logging
    from sqlalchemy import text
    from app.core.database import engine
    log = logging.getLogger("app.main")
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        log.exception("Database connectivity check failed: %s", e)
        raise RuntimeError(
            "Database unreachable. Check DATABASE_URL and that Postgres is running (e.g. docker compose up -d postgres)."
        ) from e


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    print(f"FRONTEND_URL={s.frontend_url!r} trusted_origins={s.trusted_origins!r}", flush=True)
    _verify_db_connectivity()
    try:
        storage = StorageClient()
        storage.ensure_buckets()
    except Exception as e:
        import logging
        logging.getLogger("app.main").warning("S3/MinIO bucket init skipped or failed: %s", e)
    configure_logging(s.log_level, use_json=(s.app_env == "production"))
    if s.app_env == "production":
        if not s.session_secret or s.session_secret == "change_me_dev_secret":
            raise RuntimeError(
                "APP_ENV=production requires SESSION_SECRET to be set and not the default. "
                "Use a cryptographically secure value (min 32 chars)."
            )
        if len(s.session_secret) < 32:
            raise RuntimeError(
                "SESSION_SECRET must be at least 32 characters in production."
            )
    else:
        if not s.session_secret or s.session_secret == "change_me_dev_secret":
            import logging
            logging.getLogger("app.main").warning(
                "SESSION_SECRET is default or unset. Set SESSION_SECRET to a secure value for non-local use."
            )
    print("OpenAI: configured" if s.openai_api_key else "OpenAI: not configured (Suggest Reply will return 503 or empty)", flush=True)
    if s.oauth_google_client_id:
        google_redirect = f"{s.app_base_url.rstrip('/')}/api/auth/oauth/google/callback"
        print(f"Google OAuth: add this exact Authorized redirect URI in Google Cloud Console: {google_redirect}", flush=True)
    try:
        from app.core.database import SessionLocal
        from app.services.tag_service import ensure_system_tags
        _db = SessionLocal()
        try:
            ensure_system_tags(_db)
        finally:
            _db.close()
    except Exception:
        import logging
        logging.getLogger("app.main").debug("System tag seeding skipped", exc_info=True)
    yield


app = FastAPI(title="Trust Copilot API", lifespan=lifespan)


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Log each request as one JSON line: request_id, workspace_id (if set), route, status, latency_ms."""

    async def dispatch(self, request: Request, call_next):
        import logging
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        token = request_id_ctx.set(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status = getattr(response, "status_code", 500)
            path = request.scope.get("path") or ""
            method = request.scope.get("method") or ""
            elapsed = time.perf_counter() - start
            latency_ms = round(elapsed * 1000)
            try:
                wid = getattr(request.state, "workspace_id", None) if hasattr(request, "state") else None
            except Exception:
                wid = None
            workspace_id_ctx.set(wid)
            logging.getLogger("app.request").info(
                "request",
                extra={"route": path, "method": method, "status_code": status, "latency_ms": latency_ms},
            )
            metrics_record_request(method, path, status, elapsed)
            return response
        except Exception:
            path = request.scope.get("path") or ""
            method = request.scope.get("method") or ""
            elapsed = time.perf_counter() - start
            metrics_record_request(method, path, 500, elapsed)
            raise
        finally:
            request_id_ctx.reset(token)


class CSRFMiddleware(BaseHTTPMiddleware):
    """SEC-201: Reject state-changing requests with session cookie if Origin/Referer not allowed."""

    async def dispatch(self, request: Request, call_next):
        if os.environ.get("TRUST_COPILOT_TESTING") == "1":
            return await call_next(request)
        if request.method.upper() in ("POST", "PUT", "PATCH", "DELETE"):
            has_cookie = "tc_session" in (request.cookies or {})
            if has_cookie:
                s = get_settings()
                origin = request.headers.get("origin")
                referer = request.headers.get("referer")
                host = request.url.hostname if request.url else None
                xfh = request.headers.get("x-forwarded-host")
                xfp = request.headers.get("x-forwarded-proto")
                if not is_csrf_safe(
                    request.method,
                    origin,
                    referer,
                    has_session_cookie=True,
                    allowed_origins=s.trusted_origins,
                    request_host=host,
                    x_forwarded_host=xfh,
                    x_forwarded_proto=xfp,
                ):
                    import logging
                    logging.getLogger("app.main").warning(
                        "CSRF reject: Origin=%r Referer=%r trusted_origins=%r path=%s",
                        origin, referer, s.trusted_origins, request.scope.get("path"),
                    )
                    from starlette.responses import JSONResponse
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Invalid or missing Origin/Referer"},
                    )
        return await call_next(request)


class GlobalRateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP rate limit for API requests. Skips /healthz and /readyz. Disabled when RATE_LIMIT_RPM_PER_IP=0."""

    async def dispatch(self, request: Request, call_next):
        path = (request.scope.get("path") or "").strip()
        if path in ("/healthz", "/readyz", "/workerz", "/metrics"):
            return await call_next(request)
        s = get_settings()
        if s.rate_limit_rpm_per_ip <= 0:
            return await call_next(request)
        ip = get_client_ip(request)
        key = f"api_ip:{ip}"
        if is_rate_limited(key, max_attempts=s.rate_limit_rpm_per_ip, window_sec=60.0):
            from starlette.responses import JSONResponse
            return JSONResponse(status_code=429, content={"detail": "Too many requests"})
        record_attempt(key, max_attempts=s.rate_limit_rpm_per_ip, window_sec=60.0)
        return await call_next(request)


app.add_middleware(StructuredLoggingMiddleware)
app.add_middleware(GlobalRateLimitMiddleware)
app.add_middleware(CSRFMiddleware)
_s = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_s.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router, prefix="/api")
app.include_router(members_router.router, prefix="/api")
app.include_router(workspaces_router.router, prefix="/api")
app.include_router(answers_router.router, prefix="/api")
app.include_router(exports_router.router, prefix="/api")
app.include_router(jobs_router.router, prefix="/api")
app.include_router(trust_articles_router.router, prefix="/api")
app.include_router(trust_requests_router.router, prefix="/api")
app.include_router(controls_router.router, prefix="/api")
app.include_router(compliance_controls_router.router, prefix="/api")
app.include_router(compliance_evidence_router.router, prefix="/api")
app.include_router(compliance_frameworks_router.router, prefix="/api")
app.include_router(compliance_mappings_router.router, prefix="/api")
app.include_router(compliance_gaps_router.router, prefix="/api")
app.include_router(compliance_coverage_router.router, prefix="/api")
app.include_router(compliance_alerts_router.router, prefix="/api")
app.include_router(compliance_export_router.router, prefix="/api")
app.include_router(compliance_audit_router.router, prefix="/api")
app.include_router(vendor_requests_router.router, prefix="/api")
app.include_router(documents_router.router, prefix="/api")
app.include_router(questionnaires_router.router, prefix="/api")
app.include_router(search_router.router, prefix="/api")
app.include_router(audit_router.router, prefix="/api")
app.include_router(notifications_router.router, prefix="/api")
app.include_router(slack_router.router, prefix="/api")
app.include_router(slack_ingest_router.router, prefix="/api")
app.include_router(in_app_notifications_router.router, prefix="/api")
app.include_router(gmail_router.router, prefix="/api")
app.include_router(dashboard_cards_router.router, prefix="/api")
app.include_router(tags_router.router, prefix="/api")
app.include_router(ai_mappings_router.router, prefix="/api")
app.include_router(ai_mappings_router.gov_router, prefix="/api")
app.include_router(ai_insights_router.router, prefix="/api")


@app.get("/metrics")
def metrics():
    """Prometheus scrape endpoint. Request count, latency histogram, 5xx count."""
    from starlette.responses import Response
    from app.core.metrics import get_metrics_body, get_metrics_content_type
    return Response(content=get_metrics_body(), media_type=get_metrics_content_type())


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/db-test")
def db_test():
    """Debug: verify DB connection. Only available in dev/test environments."""
    from fastapi.responses import JSONResponse
    from app.core.config import get_settings
    if get_settings().app_env == "production":
        return JSONResponse({"detail": "Not available"}, status_code=404)
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError
    from app.core.database import engine
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except OperationalError:
        return JSONResponse({"status": "error", "db": "connection failed"}, status_code=503)


@app.get("/readyz")
def readyz():
    """Readiness: DB and S3 must be reachable. Returns 503 if unhealthy."""
    from fastapi.responses import JSONResponse
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    errors = []
    try:
        from app.core.database import engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as e:
        errors.append(f"database: {e}")
    except Exception as e:
        errors.append(f"database: {e}")

    try:
        StorageClient().ping()
    except Exception as e:
        errors.append(f"s3: {e}")

    if errors:
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "errors": errors},
        )
    return {"status": "ready"}


@app.get("/workerz")
def workerz():
    """Worker and queue visibility: worker alive (heartbeat within 2 min) and queue depth. Returns 503 if worker not seen."""
    from datetime import datetime, timedelta, timezone
    from fastapi.responses import JSONResponse
    from sqlalchemy import text
    from app.core.database import engine

    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT last_seen_utc FROM worker_heartbeat WHERE id = 1")).fetchone()
            queued = conn.execute(text("SELECT COUNT(*) FROM jobs WHERE status = 'queued'")).scalar() or 0
            running = conn.execute(text("SELECT COUNT(*) FROM jobs WHERE status = 'running'")).scalar() or 0
        last_seen = row[0] if row else None
        now_utc = datetime.now(timezone.utc)
        if last_seen is not None and hasattr(last_seen, "replace"):
            last_seen_utc = last_seen.replace(tzinfo=timezone.utc) if last_seen.tzinfo is None else last_seen
        else:
            last_seen_utc = last_seen
        threshold_sec = 120
        worker_alive = (
            last_seen_utc is not None
            and (now_utc - last_seen_utc).total_seconds() < threshold_sec
        )
        body = {"worker_alive": worker_alive, "queued": queued, "running": running}
        if not worker_alive:
            import logging
            logging.getLogger("trustcopilot.alert").warning(
                "ALERT_WORKER_DOWN queued=%s running=%s", queued, running
            )
            return JSONResponse(status_code=503, content=body)
        return body
    except Exception as e:
        import logging
        logging.getLogger("trustcopilot.alert").warning(
            "ALERT_WORKER_DOWN error=%s", str(e)[:200]
        )
        return JSONResponse(status_code=503, content={"worker_alive": False, "queued": None, "running": None, "error": str(e)})
