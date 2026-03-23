"""Prometheus metrics: request count, latency, error count; pipeline jobs, index, retrieval, answer gen. Exposed at GET /metrics."""

from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

# Skip these paths in metrics (health, readiness, worker check, metrics itself)
SKIP_PATHS = frozenset({"/healthz", "/readyz", "/workerz", "/metrics", "/db-test"})

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path_template", "status_class"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "Request latency in seconds",
    ["method", "path_template"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
ERROR_COUNT = Counter(
    "http_errors_total",
    "Total 5xx responses",
    ["method", "path_template"],
)

# Pipeline: jobs
JOB_STARTED_TOTAL = Counter("pipeline_job_started_total", "Jobs started", ["kind"])
JOB_COMPLETED_TOTAL = Counter("pipeline_job_completed_total", "Jobs completed", ["kind", "status"])  # status: completed, failed
INDEX_DOCUMENT_TOTAL = Counter("pipeline_index_document_total", "Documents indexed", ["status"])  # status: success, failure
INDEX_DURATION_SECONDS = Histogram("pipeline_index_duration_seconds", "Indexing duration", buckets=(0.5, 1, 2, 5, 10, 30, 60))
RETRIEVAL_DURATION_SECONDS = Histogram("pipeline_retrieval_duration_seconds", "Retrieval duration", buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2))
ANSWER_GEN_DURATION_SECONDS = Histogram("pipeline_answer_gen_duration_seconds", "Answer generation duration", buckets=(1, 2, 5, 10, 20, 40, 60))
OPENAI_EMBEDDING_FAILURES_TOTAL = Counter("pipeline_openai_embedding_failures_total", "OpenAI embedding call failures")
OPENAI_COMPLETION_FAILURES_TOTAL = Counter("pipeline_openai_completion_failures_total", "OpenAI completion call failures")
INSUFFICIENT_EVIDENCE_TOTAL = Counter("pipeline_insufficient_evidence_total", "Batches with no evidence (skipped LLM)")
BATCH_FALLBACK_TOTAL = Counter("pipeline_batch_fallback_total", "Answer batch fallback to per-question", ["reason"])

# Phase 4: adaptive concurrency
ADAPTIVE_CONCURRENCY_CURRENT = Gauge("pipeline_adaptive_concurrency_current", "Current adaptive concurrency (max_workers) for answer gen")
ADAPTIVE_RATE_LIMITED_BATCHES_TOTAL = Counter("pipeline_adaptive_rate_limited_batches_total", "Batches that triggered rate-limit (429) step-down")
ADAPTIVE_TIMEOUT_STEPDOWN_TOTAL = Counter("pipeline_adaptive_timeout_stepdown_total", "Batches that triggered timeout step-down")

# Compliance foundation (Phase 1)
compliance_control_created_total = Counter("compliance_control_created_total", "Workspace controls created")
compliance_control_status_changed_total = Counter("compliance_control_status_changed_total", "Workspace control status changes")
compliance_evidence_linked_total = Counter("compliance_evidence_linked_total", "Evidence linked to controls")
COMPLIANCE_CONTROLS_TOTAL = Gauge("compliance_controls_total", "Total workspace controls")
COMPLIANCE_CONTROLS_WITH_EVIDENCE_TOTAL = Gauge("compliance_controls_with_evidence_total", "Workspace controls with at least one evidence link")
COMPLIANCE_EVIDENCE_ITEMS_TOTAL = Gauge("compliance_evidence_items_total", "Total evidence items")


def _path_template(path: str) -> str:
    """Reduce path to a template (e.g. /api/workspaces/123 -> /api/workspaces/{id})."""
    if not path or not path.startswith("/"):
        return path or "/"
    parts = path.strip("/").split("/")
    if len(parts) >= 4 and parts[0] == "api":
        # /api/<resource>/<id>/... -> /api/<resource>/{id}
        return "/" + "/".join(parts[:2] + ["{id}"] + parts[3:])
    if len(parts) >= 3 and parts[0] == "api":
        return "/" + "/".join(parts[:2] + ["{id}"])
    return path


def record_request(method: str, path: str, status_code: int, duration_sec: float) -> None:
    if path in SKIP_PATHS:
        return
    template = _path_template(path)
    status_class = f"{status_code // 100}xx"
    REQUEST_COUNT.labels(method=method, path_template=template, status_class=status_class).inc()
    REQUEST_LATENCY.labels(method=method, path_template=template).observe(duration_sec)
    if status_code >= 500:
        ERROR_COUNT.labels(method=method, path_template=template).inc()


def get_metrics_content_type() -> str:
    return CONTENT_TYPE_LATEST


def update_compliance_gauges(db_session) -> None:
    """Set compliance gauges from DB. Call with a SQLAlchemy session (e.g. at /metrics scrape)."""
    try:
        from app.models import WorkspaceControl, ControlEvidenceLink, EvidenceItem
        from sqlalchemy import func
        total = db_session.query(WorkspaceControl).count()
        COMPLIANCE_CONTROLS_TOTAL.set(total)
        with_evidence = (
            db_session.query(ControlEvidenceLink.control_id)
            .distinct()
            .count()
        )
        COMPLIANCE_CONTROLS_WITH_EVIDENCE_TOTAL.set(with_evidence)
        COMPLIANCE_EVIDENCE_ITEMS_TOTAL.set(db_session.query(EvidenceItem).count())
    except Exception:
        pass


def get_metrics_body() -> bytes:
    try:
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            update_compliance_gauges(db)
        finally:
            db.close()
    except Exception:
        pass
    return generate_latest()
