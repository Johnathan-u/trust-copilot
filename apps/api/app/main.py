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

# Fail fast at startup (not per request) if the PDF backend (pypdf) is missing (TC-01-003a).
import app.services.pdf_text  # noqa: E402,F401

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.logging_config import configure_logging, request_id_ctx, workspace_id_ctx  # noqa: E402
from app.core.metrics import record_request as metrics_record_request  # noqa: E402
from app.core.rate_limit import get_client_ip, is_rate_limited, record_attempt  # noqa: E402
from app.api.routes import auth as auth_router  # noqa: E402
from app.api.routes import members as members_router  # noqa: E402
from app.api.routes import workspaces as workspaces_router  # noqa: E402
from app.core.csrf import is_csrf_safe  # noqa: E402
from app.api.routes import answers as answers_router  # noqa: E402
from app.api.routes import documents as documents_router  # noqa: E402
from app.api.routes import exports as exports_router  # noqa: E402
from app.api.routes import jobs as jobs_router  # noqa: E402
from app.api.routes import questionnaires as questionnaires_router  # noqa: E402
from app.api.routes import search as search_router  # noqa: E402
from app.api.routes import trust_articles as trust_articles_router  # noqa: E402
from app.api.routes import trust_requests as trust_requests_router  # noqa: E402
from app.api.routes import controls as controls_router  # noqa: E402
from app.api.routes import compliance_controls as compliance_controls_router  # noqa: E402
from app.api.routes import compliance_evidence as compliance_evidence_router  # noqa: E402
from app.api.routes import compliance_frameworks as compliance_frameworks_router  # noqa: E402
from app.api.routes import compliance_mappings as compliance_mappings_router  # noqa: E402
from app.api.routes import compliance_gaps as compliance_gaps_router  # noqa: E402
from app.api.routes import compliance_coverage as compliance_coverage_router  # noqa: E402
from app.api.routes import compliance_alerts as compliance_alerts_router  # noqa: E402
from app.api.routes import compliance_export as compliance_export_router  # noqa: E402
from app.api.routes import compliance_audit as compliance_audit_router  # noqa: E402
from app.api.routes import vendor_requests as vendor_requests_router  # noqa: E402
from app.api.routes import vendor_response as vendor_response_router  # noqa: E402
from app.api.routes import audit as audit_router  # noqa: E402
from app.api.routes import notifications as notifications_router  # noqa: E402
from app.api.routes import slack as slack_router  # noqa: E402
from app.api.routes import slack_ingest as slack_ingest_router  # noqa: E402
from app.api.routes import in_app_notifications as in_app_notifications_router  # noqa: E402
from app.api.routes import gmail as gmail_router  # noqa: E402
from app.api.routes import dashboard_cards as dashboard_cards_router  # noqa: E402
from app.api.routes import tags as tags_router  # noqa: E402
from app.api.routes import ai_mappings as ai_mappings_router  # noqa: E402
from app.api.routes import ai_insights as ai_insights_router  # noqa: E402
from app.api.routes import billing as billing_router  # noqa: E402
from app.api.routes import feature_flags as feature_flags_router  # noqa: E402
from app.api.routes import credits as credits_router  # noqa: E402
from app.api.routes import operator_queue as operator_queue_router  # noqa: E402
from app.api.routes import security_faq as security_faq_router  # noqa: E402
from app.api.routes import demo_proof as demo_proof_router  # noqa: E402
from app.api.routes import export_pack as export_pack_router  # noqa: E402
from app.api.routes import source_registry as source_registry_router  # noqa: E402
from app.api.routes import credentials as credentials_router  # noqa: E402
from app.api.routes import security_page as security_page_router  # noqa: E402
from app.api.routes import benchmarks as benchmarks_router  # noqa: E402
from app.api.routes import proof_widgets as proof_widgets_router  # noqa: E402
from app.api.routes import product_events as product_events_router  # noqa: E402
from app.api.routes import executive_dashboard as executive_dashboard_router  # noqa: E402
from app.api.routes import roi_calculator as roi_calculator_router  # noqa: E402
from app.api.routes import case_studies as case_studies_router  # noqa: E402
from app.api.routes import connector_health as connector_health_router  # noqa: E402
from app.api.routes import control_engine as control_engine_router  # noqa: E402
from app.api.routes import evidence_cards as evidence_cards_router  # noqa: E402
from app.api.routes import knowledge_packs as knowledge_packs_router  # noqa: E402
from app.api.routes import sla_tracking as sla_tracking_router  # noqa: E402
from app.api.routes import credit_prompts as credit_prompts_router  # noqa: E402
from app.api.routes import signal_mapping as signal_mapping_router  # noqa: E402
from app.api.routes import monitoring as monitoring_router  # noqa: E402
from app.api.routes import alert_management as alert_management_router  # noqa: E402
from app.api.routes import trust_center_publish as trust_center_publish_router  # noqa: E402
from app.api.routes import control_timeline as control_timeline_router  # noqa: E402
from app.api.routes import nda_access as nda_access_router  # noqa: E402
from app.api.routes import evidence_diff as evidence_diff_router  # noqa: E402
from app.api.routes import shareable_spaces as shareable_spaces_router  # noqa: E402
from app.api.routes import trust_center_analytics as trust_center_analytics_router  # noqa: E402
from app.api.routes import answer_tiers as answer_tiers_router  # noqa: E402
from app.api.routes import golden_answers as golden_answers_router  # noqa: E402
from app.api.routes import feedback_capture as feedback_capture_router  # noqa: E402
from app.api.routes import reuse_analytics as reuse_analytics_router  # noqa: E402
from app.api.routes import incident_pages as incident_pages_router  # noqa: E402
from app.api.routes import sli as sli_router  # noqa: E402
from app.api.routes import ingestion as ingestion_router  # noqa: E402
from app.api.routes import aws_connector as aws_connector_router  # noqa: E402
from app.api.routes import github_connector as github_connector_router  # noqa: E402
from app.api.routes import google_connector as google_connector_router  # noqa: E402
from app.api.routes import cloud_connectors as cloud_connectors_router  # noqa: E402
from app.api.routes import answer_approval as answer_approval_router  # noqa: E402
from app.api.routes import evidence_approval as evidence_approval_router  # noqa: E402
from app.api.routes import confidence_scoring as confidence_scoring_router  # noqa: E402
from app.api.routes import freshness_policies as freshness_policies_router  # noqa: E402
from app.api.routes import citation_composer as citation_composer_router  # noqa: E402
from app.api.routes import retention as retention_router  # noqa: E402
from app.api.routes import evidence_search as evidence_search_router  # noqa: E402
from app.api.routes import confidence_routing as confidence_routing_router  # noqa: E402
from app.api.routes import alerting_engine as alerting_engine_router  # noqa: E402
from app.api.routes import connector_wizard as connector_wizard_router  # noqa: E402
from app.api.routes import deals as deals_router  # noqa: E402
from app.api.routes import crm_connectors as crm_connectors_router  # noqa: E402
from app.api.routes import remediation as remediation_router  # noqa: E402
from app.api.routes import promises as promises_router  # noqa: E402
from app.api.routes import contracts as contracts_router  # noqa: E402
from app.api.routes import buyer_portal as buyer_portal_router  # noqa: E402
from app.api.routes import proof_graph as proof_graph_router  # noqa: E402
from app.api.routes import answer_outcomes as answer_outcomes_router  # noqa: E402
from app.services.storage import StorageClient  # noqa: E402


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
            raise RuntimeError("SESSION_SECRET must be at least 32 characters in production.")
    else:
        if not s.session_secret or s.session_secret == "change_me_dev_secret":
            import logging

            logging.getLogger("app.main").warning(
                "SESSION_SECRET is default or unset. Set SESSION_SECRET to a secure value for non-local use."
            )
    from app.services.message_providers.selection import assert_message_provider_preflight

    assert_message_provider_preflight()
    print(
        "OpenAI: configured"
        if s.openai_api_key
        else "OpenAI: not configured (Suggest Reply will return 503 or empty)",
        flush=True,
    )
    if s.oauth_google_client_id:
        google_redirect = f"{s.app_base_url.rstrip('/')}/api/auth/oauth/google/callback"
        print(
            f"Google OAuth: add this exact Authorized redirect URI in Google Cloud Console: {google_redirect}",
            flush=True,
        )
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


app = FastAPI(title="Trust Copilot API", lifespan=lifespan, redirect_slashes=False)


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
                wid = (
                    getattr(request.state, "workspace_id", None)
                    if hasattr(request, "state")
                    else None
                )
            except Exception:
                wid = None
            workspace_id_ctx.set(wid)
            logging.getLogger("app.request").info(
                "request",
                extra={
                    "route": path,
                    "method": method,
                    "status_code": status,
                    "latency_ms": latency_ms,
                },
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
                        origin,
                        referer,
                        s.trusted_origins,
                        request.scope.get("path"),
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
        if path in ("/healthz", "/readyz", "/workerz", "/metrics", "/api/billing/webhook"):
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
app.include_router(vendor_response_router.router, prefix="/api")
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
app.include_router(billing_router.router, prefix="/api")
app.include_router(feature_flags_router.router, prefix="/api")
app.include_router(credits_router.router, prefix="/api")
app.include_router(operator_queue_router.router, prefix="/api")
app.include_router(security_faq_router.router, prefix="/api")
app.include_router(demo_proof_router.router, prefix="/api")
app.include_router(export_pack_router.router, prefix="/api")
app.include_router(source_registry_router.router, prefix="/api")
app.include_router(credentials_router.router, prefix="/api")
app.include_router(security_page_router.router, prefix="/api")
app.include_router(benchmarks_router.router, prefix="/api")
app.include_router(proof_widgets_router.router, prefix="/api")
app.include_router(product_events_router.router, prefix="/api")
app.include_router(executive_dashboard_router.router, prefix="/api")
app.include_router(roi_calculator_router.router, prefix="/api")
app.include_router(case_studies_router.router, prefix="/api")
app.include_router(connector_health_router.router, prefix="/api")
app.include_router(control_engine_router.router, prefix="/api")
app.include_router(evidence_cards_router.router, prefix="/api")
app.include_router(knowledge_packs_router.router, prefix="/api")
app.include_router(sla_tracking_router.router, prefix="/api")
app.include_router(credit_prompts_router.router, prefix="/api")
app.include_router(signal_mapping_router.router, prefix="/api")
app.include_router(monitoring_router.router, prefix="/api")
app.include_router(alert_management_router.router, prefix="/api")
app.include_router(trust_center_publish_router.router, prefix="/api")
app.include_router(control_timeline_router.router, prefix="/api")
app.include_router(nda_access_router.router, prefix="/api")
app.include_router(evidence_diff_router.router, prefix="/api")
app.include_router(shareable_spaces_router.router, prefix="/api")
app.include_router(trust_center_analytics_router.router, prefix="/api")
app.include_router(answer_tiers_router.router, prefix="/api")
app.include_router(golden_answers_router.router, prefix="/api")
app.include_router(feedback_capture_router.router, prefix="/api")
app.include_router(reuse_analytics_router.router, prefix="/api")
app.include_router(incident_pages_router.router, prefix="/api")
app.include_router(sli_router.router, prefix="/api")
app.include_router(ingestion_router.router, prefix="/api")
app.include_router(aws_connector_router.router, prefix="/api")
app.include_router(github_connector_router.router, prefix="/api")
app.include_router(google_connector_router.router, prefix="/api")
app.include_router(cloud_connectors_router.router, prefix="/api")
app.include_router(answer_approval_router.router, prefix="/api")
app.include_router(evidence_approval_router.router, prefix="/api")
app.include_router(confidence_scoring_router.router, prefix="/api")
app.include_router(freshness_policies_router.router, prefix="/api")
app.include_router(citation_composer_router.router, prefix="/api")
app.include_router(retention_router.router, prefix="/api")
app.include_router(evidence_search_router.router, prefix="/api")
app.include_router(confidence_routing_router.router, prefix="/api")
app.include_router(alerting_engine_router.router, prefix="/api")
app.include_router(connector_wizard_router.router, prefix="/api")
app.include_router(deals_router.router, prefix="/api")
app.include_router(crm_connectors_router.router, prefix="/api")
app.include_router(remediation_router.router, prefix="/api")
app.include_router(promises_router.router, prefix="/api")
app.include_router(contracts_router.router, prefix="/api")
app.include_router(buyer_portal_router.router, prefix="/api")
app.include_router(buyer_portal_router.public_router, prefix="/public")
app.include_router(proof_graph_router.router, prefix="/api")
app.include_router(answer_outcomes_router.router, prefix="/api")


@app.get("/metrics")
def metrics():
    """Prometheus scrape endpoint. Request count, latency histogram, 5xx count."""
    from starlette.responses import Response
    from app.core.metrics import get_metrics_body, get_metrics_content_type

    return Response(content=get_metrics_body(), media_type=get_metrics_content_type())


@app.get("/healthz")
def healthz():
    """Liveness (TC-03-003): process is up and serving. Never touches DB/S3/worker, so dependency
    loss cannot make the orchestrator restart a healthy API process. Use /readyz for dependencies."""
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


# --- Readiness / worker health (TC-03-003) -------------------------------------------------
import concurrent.futures as _cf  # noqa: E402
import logging as _logging  # noqa: E402

_PROBE_POOL = _cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="readyz")


def _run_dependency_check(fn, timeout: float) -> tuple[str, str | None]:
    """Run one dependency check with a hard deadline. Returns (state, redacted_error).

    The error string is only the exception class name: connection strings, hosts and credentials
    from driver messages are never returned to callers of an unauthenticated endpoint.
    """
    fut = _PROBE_POOL.submit(fn)
    try:
        fut.result(timeout=timeout)
        return "ok", None
    except _cf.TimeoutError:
        fut.cancel()
        return "timeout", f"timed out after {timeout:g}s"
    except Exception as e:  # noqa: BLE001
        return "unavailable", type(e).__name__


def _check_database() -> None:
    from sqlalchemy import text
    from app.core.database import engine

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def _check_storage() -> None:
    StorageClient().ping()


@app.get("/readyz")
def readyz():
    """Readiness: DB and S3 must be reachable within READINESS_TIMEOUT_SEC. 503 if not.

    Response (additive to the baseline contract): ``status`` ("ready" | "not ready"),
    ``checks`` {database, storage: "ok" | "unavailable" | "timeout"}, and on failure ``errors``
    (redacted, one per failing dependency).
    """
    from fastapi.responses import JSONResponse

    timeout = get_settings().readiness_timeout_sec
    checks: dict[str, str] = {}
    errors: list[str] = []
    for name, fn in (("database", _check_database), ("storage", _check_storage)):
        state, err = _run_dependency_check(fn, timeout)
        checks[name] = state
        if err:
            label = "s3" if name == "storage" else name
            errors.append(f"{label}: {state} ({err})")
    if errors:
        _logging.getLogger("trustcopilot.alert").warning("ALERT_NOT_READY %s", "; ".join(errors))
        return JSONResponse(
            status_code=503, content={"status": "not ready", "checks": checks, "errors": errors}
        )
    return {"status": "ready", "checks": checks}


def _worker_stale_after_sec() -> int:
    from app.worker_health import heartbeat_stale_sec

    return heartbeat_stale_sec()


@app.get("/workerz")
def workerz():
    """Worker and queue visibility. ``worker_alive`` is true when the worker heartbeat is newer than
    WORKER_HEARTBEAT_STALE_SEC (default 120s). The worker refreshes it from a background thread,
    including while a long job runs. 503 when stale/missing, or ``status: "unknown"`` when the
    heartbeat store itself is unreachable (a dependency problem, not proof the worker died).
    """
    from datetime import datetime, timezone
    from fastapi.responses import JSONResponse
    from sqlalchemy import text
    from app.core.database import engine

    threshold_sec = _worker_stale_after_sec()
    alert = _logging.getLogger("trustcopilot.alert")
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT last_seen_utc FROM worker_heartbeat WHERE id = 1")
            ).fetchone()
            queued = (
                conn.execute(text("SELECT COUNT(*) FROM jobs WHERE status = 'queued'")).scalar()
                or 0
            )
            running = (
                conn.execute(text("SELECT COUNT(*) FROM jobs WHERE status = 'running'")).scalar()
                or 0
            )
        last_seen = row[0] if row else None
        now_utc = datetime.now(timezone.utc)
        if last_seen is not None and hasattr(last_seen, "replace"):
            last_seen_utc = (
                last_seen.replace(tzinfo=timezone.utc) if last_seen.tzinfo is None else last_seen
            )
        else:
            last_seen_utc = None
        age = (now_utc - last_seen_utc).total_seconds() if last_seen_utc is not None else None
        worker_alive = age is not None and age < threshold_sec
        body = {
            "worker_alive": worker_alive,
            "status": "ok" if worker_alive else "stale",
            "queued": queued,
            "running": running,
            "last_seen_age_sec": round(age, 1) if age is not None else None,
            "stale_after_sec": threshold_sec,
        }
        if not worker_alive:
            alert.warning(
                "ALERT_WORKER_DOWN queued=%s running=%s age=%s",
                queued,
                running,
                body["last_seen_age_sec"],
            )
            return JSONResponse(status_code=503, content=body)
        return body
    except Exception as e:  # noqa: BLE001
        alert.warning("ALERT_WORKER_DOWN status=unknown error=%s", type(e).__name__)
        return JSONResponse(
            status_code=503,
            content={
                "worker_alive": False,
                "status": "unknown",
                "queued": None,
                "running": None,
                "last_seen_age_sec": None,
                "stale_after_sec": threshold_sec,
                "error": f"heartbeat store unavailable ({type(e).__name__})",
            },
        )
