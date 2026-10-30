"""Worker claim loop (JOB-02) — multi-threaded with adaptive scaling."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Same env semantics as main.py/database.py: in Docker do not load .env so compose env is used.
# Under tests (TRUST_COPILOT_TESTING=1) never load .env either, so importing the worker cannot
# replace the test DATABASE_URL or inject real provider credentials (TC-02-001).
_in_docker = Path("/.dockerenv").exists() or os.environ.get("TRUST_COPILOT_IN_DOCKER") == "1"
_in_test = os.environ.get("TRUST_COPILOT_TESTING") == "1"
if not _in_docker and not _in_test:
    _api_root = Path(__file__).resolve().parent.parent
    _repo_root = _api_root.parent.parent
    load_dotenv(_api_root / ".env", override=True)
    load_dotenv(_repo_root / ".env")

import io  # noqa: E402, F401
import json  # noqa: E402
import logging  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from collections.abc import Callable  # noqa: E402
from concurrent.futures import ThreadPoolExecutor, as_completed  # noqa: E402, F401
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import and_, create_engine, func, or_, text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.pipeline_logging import log_job_failure, log_job_start, log_job_success  # noqa: E402
from app.core.metrics import JOB_COMPLETED_TOTAL, JOB_STARTED_TOTAL  # noqa: E402
from app.models import Document, Job, JobStatus, Question, Questionnaire  # noqa: E402
from app.core.audit import persist_audit  # noqa: E402
from app.core.job_errors import (  # noqa: E402
    AUTH_FAILED,
    LEASE_EXPIRED,
    MAX_ATTEMPTS_CEILING,
    RetryableJobError,
    TerminalJobError,
    backoff_delay,
    classify,
    effective_max_attempts,
    is_fatal_code,
    is_retryable_code,
    retry_after_seconds,
    retry_base_seconds,
    retry_max_seconds,
    safe_error_message,
)
from app.core.job_lease import (  # noqa: E402
    LEASE_EXPIRED_MESSAGE,
    JobLeaseHeartbeat,
    LeaseLost,
    claim_lease_expiry,
    confirm_lease_for_commit,
    install_commit_fence,
    lease_heartbeat_seconds,
    lease_seconds,
    lock_expired_lease,
    lock_null_lease_past_grace,
    new_lease_owner_token,
    null_lease_grace_seconds,
    owns_lease,
    renew_lease,
    uninstall_commit_fence,
)
from app.services.file_service import FileService  # noqa: E402
from app.services.storage import StorageClient  # noqa: E402
from app.services.docx_questionnaire_parser import parse_docx_questionnaire  # noqa: E402
from app.services.pdf_questionnaire_parser import parse_pdf_questionnaire  # noqa: E402  (hard-imports pypdf: fails at worker startup if missing)
from app.services.pdf_text import PdfTextError  # noqa: E402
from app.services.xlsx_questionnaire_parser import parse_xlsx_questionnaire  # noqa: E402
from app.services.compliance_webhook_delivery import process_compliance_webhook_outbox  # noqa: E402
from app.services.in_app_notification_service import notify_admins, notify_workspace  # noqa: E402
from app.services.automation_service import maybe_auto_generate, evaluate_generation_result  # noqa: E402
from app.services.compliance_event_service import evaluate_and_fire_compliance_events  # noqa: E402
from app.services.job_effects import (  # noqa: E402
    EnqueueConflictError,
    JobEffects,
    mark_unsettled_uncertain,
    reconcile_previous_attempts,
)
from app.worker_health import HeartbeatState, HeartbeatThread  # noqa: E402

settings = get_settings()
COMPLIANCE_WEBHOOK_INTERVAL_SEC = 30
USAGE_CLEANUP_INTERVAL_SEC = 3600
last_compliance_webhook_run = 0.0
last_usage_cleanup_run = 0.0
last_dedupe_prune_run = 0.0
_last_claimed_workspace_id: int | None = None
engine = create_engine(settings.database_url, pool_size=12, max_overflow=8)
SessionFactory = sessionmaker(bind=engine)

WORKER_MIN_THREADS = 3
WORKER_MAX_THREADS = 10
WORKER_INITIAL_THREADS = 6

# TC-03-003: heartbeat is refreshed by a background thread so long-running healthy jobs keep it fresh.
HEARTBEAT_STATE = HeartbeatState()
_HEARTBEAT_SQL = text(
    "INSERT INTO worker_heartbeat (id, last_seen_utc) VALUES (1, (NOW() AT TIME ZONE 'UTC')) "
    "ON CONFLICT (id) DO UPDATE SET last_seen_utc = EXCLUDED.last_seen_utc"
)


def write_db_heartbeat() -> None:
    """Refresh the shared heartbeat row read by /workerz (own short-lived session)."""
    session = SessionFactory()
    try:
        session.execute(_HEARTBEAT_SQL)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


_active_threads = WORKER_INITIAL_THREADS
_threads_lock = threading.Lock()
_consecutive_idle = 0
_consecutive_busy = 0


def _adapt_thread_count(had_work: bool) -> int:
    """Adapt worker thread pool size based on queue pressure."""
    global _active_threads, _consecutive_idle, _consecutive_busy
    with _threads_lock:
        if had_work:
            _consecutive_idle = 0
            _consecutive_busy += 1
            if _consecutive_busy >= 3 and _active_threads < WORKER_MAX_THREADS:
                _active_threads += 1
                _consecutive_busy = 0
                logging.getLogger(__name__).info(
                    "worker: scaling up to %d threads", _active_threads
                )
        else:
            _consecutive_busy = 0
            _consecutive_idle += 1
            if _consecutive_idle >= 5 and _active_threads > WORKER_MIN_THREADS:
                _active_threads -= 1
                _consecutive_idle = 0
                logging.getLogger(__name__).info(
                    "worker: scaling down to %d threads", _active_threads
                )
        return _active_threads


_clock: Callable[[], datetime] | None = None


def set_clock(clock: Callable[[], datetime] | None) -> None:
    """Test hook. Naive UTC clock for claim, lease, backoff and recovery. None is wall time."""
    global _clock
    _clock = clock


def _utcnow_naive() -> datetime:
    """Naive UTC, matching the naive ``DateTime`` job columns."""
    if _clock is not None:
        current = _clock()
        if current.tzinfo is not None:
            current = current.astimezone(timezone.utc).replace(tzinfo=None)
        return current
    return datetime.now(timezone.utc).replace(tzinfo=None)


def claimable_filter(now: datetime | None = None):
    """Queued, attempts left under the capped budget, and any scheduled retry backoff has elapsed.

    The budget is ``effective_max_attempts`` (NULL defaults to 3, then clamped to
    ``[1, MAX_ATTEMPTS_CEILING]``), not the raw ``jobs.max_attempts`` column.
    """
    now = now or _utcnow_naive()
    capped_attempts = func.least(
        func.greatest(func.coalesce(Job.max_attempts, 3), 1),
        MAX_ATTEMPTS_CEILING,
    )
    return and_(
        Job.status == JobStatus.QUEUED.value,
        Job.attempt < capped_attempts,
        or_(Job.next_attempt_at.is_(None), Job.next_attempt_at <= now),
    )


def claim_job(session) -> Job | None:
    """Claim next queued job with round-robin fair scheduling across workspaces.

    TC-10-002: a retry scheduled by ``_handle_job_failure`` is not claimable before ``next_attempt_at``.
    """
    global _last_claimed_workspace_id

    base = session.query(Job).filter(claimable_filter())
    if _last_claimed_workspace_id is not None:
        job = (
            base.filter(Job.workspace_id != _last_claimed_workspace_id)
            .order_by(Job.created_at)
            .with_for_update(skip_locked=True)
            .first()
        )
        if not job:
            job = base.order_by(Job.created_at).with_for_update(skip_locked=True).first()
    else:
        job = base.order_by(Job.created_at).with_for_update(skip_locked=True).first()
    if not job:
        return None
    _last_claimed_workspace_id = job.workspace_id
    job.status = JobStatus.RUNNING.value
    job.attempt += 1
    job.started_at = datetime.now(timezone.utc)
    job.next_attempt_at = (
        None  # the scheduled retry is now running (error/error_code keep the last failure)
    )
    # TC-10-001: one owner token per claim. The row lock above is what makes the claim exclusive;
    # the token is what later heartbeats and commits check. Expiry is the database clock.
    owner = new_lease_owner_token()
    job.lease_owner = owner
    session.flush()
    claim_lease_expiry(session, job.id, owner, lease_seconds())
    session.commit()
    session.refresh(job)
    # TC-10-003: provider calls of earlier attempts that never settled may have been charged.
    try:
        reconcile_previous_attempts(session, job)
    except Exception:
        session.rollback()
        logging.getLogger(__name__).warning(
            "reconcile_previous_attempts failed job_id=%s", job.id, exc_info=True
        )
    return job


def _set_outcome(job: Job, outcome: str, **extra) -> None:
    """Record a no-op outcome (already applied / superseded) in the job result (TC-10-003)."""
    job.result = json.dumps({"outcome": outcome, **extra})


def _record_auto_generate_enqueue_conflict(job: Job) -> None:
    """Note a lost auto-generate enqueue on the parse job. The session was just rolled back.

    The parse outcome already stored on ``job.result`` is kept. ``auto_generate`` is how the
    conflict is recorded on that outcome. No generate row is written here.
    """
    logging.getLogger(__name__).warning(
        "auto-generate enqueue conflict job_id=%s workspace_id=%s; "
        "parse completion kept, no generate job committed",
        job.id,
        job.workspace_id,
    )
    try:
        data = json.loads(job.result) if job.result else {}
    except (TypeError, ValueError):
        data = {"previous_result": job.result}
    if not isinstance(data, dict):
        data = {"previous_result": data}
    data["auto_generate"] = "enqueue_conflict"
    job.result = json.dumps(data)


def _job_outcome(job: Job) -> str | None:
    try:
        # getattr: a job without a result attribute (e.g. TC-03-003's heartbeat probe double) has no outcome;
        # an AttributeError here would turn a completed job into a failure.
        data = json.loads(getattr(job, "result", None) or "{}")
    except (TypeError, ValueError):
        return None
    return data.get("outcome") if isinstance(data, dict) else None


EFFECT_QUESTIONS = "questions"
EFFECT_CHUNKS = "chunks"
EFFECT_EXPORT = "export_record"


def run_parse_questionnaire(job: Job, session, payload: dict) -> None:
    """Parse questionnaire XLSX or DOCX and save questions (QNR-13, QNR-07/08/09)."""
    qnr_id = payload.get("questionnaire_id")
    storage_key = payload.get("storage_key")
    if not qnr_id or not storage_key:
        raise ValueError("Missing questionnaire_id or storage_key")
    qnr = session.query(Questionnaire).filter(Questionnaire.id == qnr_id).first()
    if not qnr:
        raise ValueError(f"Questionnaire {qnr_id} not found")
    if qnr.workspace_id != job.workspace_id:
        raise ValueError(
            f"Questionnaire {qnr_id} workspace mismatch: {qnr.workspace_id} != {job.workspace_id}"
        )
    effects = JobEffects(session, job)
    if effects.is_applied(EFFECT_QUESTIONS):
        # A previous attempt committed the questions; only the (cached, idempotent) classification may remain.
        _set_outcome(job, "already_applied", effect=EFFECT_QUESTIONS)
        _auto_classify_questionnaire(session, qnr_id, job.workspace_id)
        return
    stale = _parse_stale_reason(qnr, storage_key)
    if stale:
        _set_outcome(job, "superseded", reason=stale)
        return
    ext = Path(qnr.filename or storage_key or "").suffix.lower()
    if ext not in (".xlsx", ".xls", ".docx", ".doc", ".pdf"):
        ext = ".xlsx"
    storage = StorageClient()
    file_svc = FileService(storage)
    content = file_svc.download_raw(storage_key)
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        f.write(content)
        path = f.name
    try:
        if ext in (".docx", ".doc"):
            questions = parse_docx_questionnaire(path)
        elif ext == ".pdf":
            questions = parse_pdf_questionnaire(path)
        else:
            questions = parse_xlsx_questionnaire(path)
        # Serialize concurrent parses of the same questionnaire and re-check under the lock.
        # populate_existing: FOR UPDATE alone returns the identity-map row, which can
        # still show the pre-lock storage key / deleted_at and miss a concurrent parse.
        qnr = (
            session.query(Questionnaire)
            .filter(Questionnaire.id == qnr_id)
            .populate_existing()
            .with_for_update()
            .first()
        )
        stale = _parse_stale_reason(qnr, storage_key) if qnr else "questionnaire_missing"
        if stale:
            session.rollback()
            _set_outcome(job, "superseded", reason=stale)
            return
        existing = session.query(Question).filter(Question.questionnaire_id == qnr_id).count()
        if existing:
            # Questions already exist (another job, or pre-ledger code): never duplicate them and never
            # delete them (answers / approvals hang off them). Reconcile instead.
            if qnr.status != "parsed":
                qnr.status = "parsed"
            effects.mark_applied(
                EFFECT_QUESTIONS, {"reconciled": "existing_questions", "count": existing}
            )
            _set_outcome(job, "reconciled", effect=EFFECT_QUESTIONS, count=existing)
            session.commit()
            _auto_classify_questionnaire(session, qnr_id, job.workspace_id)
            return
        for q in questions:
            session.add(
                Question(
                    questionnaire_id=qnr_id,
                    text=q["text"],
                    section=q.get("section"),
                    answer_type=q.get("answer_type"),
                    source_location=q.get("source_location"),
                    confidence=q.get("confidence"),
                )
            )
        qnr.status = "parsed"
        qnr.parse_metadata = json.dumps({"count": len(questions), "questions": questions[:50]})
        effects.mark_applied(EFFECT_QUESTIONS, {"count": len(questions)})
        session.commit()

        _auto_classify_questionnaire(session, qnr_id, job.workspace_id)
    finally:
        Path(path).unlink(missing_ok=True)


def _parse_stale_reason(qnr: Questionnaire, storage_key: str) -> str | None:
    """Why a parse job's input no longer matches the questionnaire (None if it still does)."""
    if getattr(qnr, "deleted_at", None) is not None:
        return "questionnaire_deleted"
    if qnr.storage_key and qnr.storage_key != storage_key:
        return "input_version_changed"
    return None


def _auto_classify_questionnaire(session, qnr_id: int, workspace_id: int) -> None:
    """Auto-detect frameworks and subject areas from parsed questions and update questionnaire metadata."""
    try:
        from app.services.mapping_llm_classify import bulk_classify_and_persist

        questions = session.query(Question).filter(Question.questionnaire_id == qnr_id).all()
        if not questions:
            return

        sample = questions[:60] if len(questions) > 60 else questions
        stats = bulk_classify_and_persist(session, sample, workspace_id, questionnaire_id=qnr_id)
        logging.getLogger(__name__).info(
            "auto_classify questionnaire=%s classified=%s failed=%s",
            qnr_id,
            stats.get("classified", 0),
            stats.get("failed", 0),
        )

        from app.models.question_mapping_signal import QuestionMappingSignal

        signals = (
            session.query(QuestionMappingSignal)
            .filter(
                QuestionMappingSignal.questionnaire_id == qnr_id,
                QuestionMappingSignal.workspace_id == workspace_id,
            )
            .all()
        )

        fw_set: set[str] = set()
        subj_set: set[str] = set()
        for sig in signals:
            if sig.framework_labels_json:
                for fw in json.loads(sig.framework_labels_json):
                    if fw and fw not in ("Other", "Unknown"):
                        fw_set.add(fw)
            if sig.subject_labels_json:
                for s in json.loads(sig.subject_labels_json):
                    if s and s != "Other":
                        subj_set.add(s)

        qnr = session.query(Questionnaire).filter(Questionnaire.id == qnr_id).first()
        if qnr:
            existing_fw = json.loads(qnr.frameworks_json or "[]")
            existing_sa = json.loads(qnr.subject_areas_json or "[]")
            if existing_fw == ["Other"] and fw_set:
                qnr.frameworks_json = json.dumps(sorted(fw_set))
            elif fw_set:
                merged = set(existing_fw) | fw_set
                merged.discard("Other")
                qnr.frameworks_json = json.dumps(sorted(merged))
            if existing_sa == ["Other"] and subj_set:
                qnr.subject_areas_json = json.dumps(sorted(subj_set))
            elif subj_set:
                merged = set(existing_sa) | subj_set
                merged.discard("Other")
                qnr.subject_areas_json = json.dumps(sorted(merged))
            session.commit()
            logging.getLogger(__name__).info(
                "auto_classify questionnaire=%s frameworks=%s subjects=%s",
                qnr_id,
                qnr.frameworks_json,
                qnr.subject_areas_json,
            )
    except Exception as e:
        logging.getLogger(__name__).warning(
            "auto_classify failed for questionnaire %s: %s", qnr_id, e
        )


def run_index_document(job: Job, session, payload: dict) -> None:
    """Index document: parse, chunk, embed (DOC-08, DOC-09). Validates document belongs to job workspace."""
    doc_id = payload.get("document_id")
    if not doc_id:
        raise ValueError("Missing document_id")
    doc = session.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise ValueError(f"Document {doc_id} not found")
    if doc.workspace_id != job.workspace_id:
        raise ValueError(
            f"Document {doc_id} workspace_id {doc.workspace_id} does not match job workspace_id {job.workspace_id}"
        )
    from app.models import Chunk
    from app.services.index_service import index_document

    effects = JobEffects(session, job)
    if effects.is_applied(EFFECT_CHUNKS):
        _set_outcome(job, "already_applied", effect=EFFECT_CHUNKS)
        # The post-commit cache invalidation may not have run before a crash; repeating it is harmless.
        _bump_corpus_version_best_effort(session, doc.workspace_id)
        return
    # Serialize concurrent index jobs for the same document; re-check under the lock.
    # populate_existing: FOR UPDATE alone returns the identity-map row. A concurrent
    # index that already committed would look un-indexed, so this job would re-embed
    # and then collide on the applied-marker unique key.
    doc = (
        session.query(Document)
        .filter(Document.id == doc_id)
        .populate_existing()
        .with_for_update()
        .first()
        or doc
    )
    if getattr(doc, "deleted_at", None) is not None:
        session.rollback()
        _set_outcome(job, "superseded", reason="document_deleted")
        return
    if job.input_version and doc.storage_key != job.input_version:
        session.rollback()
        _set_outcome(job, "superseded", reason="input_version_changed")
        return
    if (
        doc.status == "indexed"
        and session.query(Chunk.id).filter(Chunk.document_id == doc_id).first()
    ):
        # Another job already indexed this exact input: do not re-embed (cost) or rewrite chunks.
        effects.mark_applied(EFFECT_CHUNKS, {"reconciled": "already_indexed"})
        _set_outcome(job, "reconciled", effect=EFFECT_CHUNKS)
        session.commit()
        return
    storage = StorageClient()
    file_svc = FileService(storage)
    index_document(
        session,
        doc_id,
        storage,
        file_svc,
        job_id=job.id,
        effects=effects,
        effect_name=EFFECT_CHUNKS,
    )


def _bump_corpus_version_best_effort(session, workspace_id: int) -> None:
    try:
        from app.core.corpus_version import bump_corpus_version
        from app.services.retrieval_cache import invalidate_workspace

        bump_corpus_version(session, workspace_id)
        invalidate_workspace(session, workspace_id)
    except Exception:
        logging.getLogger(__name__).debug(
            "corpus version bump failed ws=%s", workspace_id, exc_info=True
        )


def run_generate_answers(job: Job, session, payload: dict) -> None:
    """Generate answers for questionnaire."""
    import json

    from app.core.config import get_settings  # noqa: F401
    from app.services.answer_generation import generate_answers_for_questionnaire

    qnr_id = payload.get("questionnaire_id")
    ws_id = payload.get("workspace_id")
    if not qnr_id or not ws_id:
        raise ValueError("Missing questionnaire_id or workspace_id")
    if ws_id != job.workspace_id:
        raise ValueError(f"Payload workspace_id {ws_id} != job workspace_id {job.workspace_id}")
    logging.getLogger(__name__).info(
        "WORKER: job received kind=generate_answers job_id=%s questionnaire_id=%s workspace_id=%s",
        job.id,
        qnr_id,
        ws_id,
    )
    model_override = payload.get("model")
    response_style_override = payload.get("response_style")
    qnr = (
        session.query(Questionnaire)
        .filter(Questionnaire.id == qnr_id, Questionnaire.workspace_id == ws_id)
        .first()
    )
    if qnr is not None and getattr(qnr, "deleted_at", None) is not None:
        _set_outcome(job, "superseded", reason="questionnaire_deleted")
        return
    effects = JobEffects(session, job)
    _record_usage_once(session, job, effects, "ai_jobs")
    count = generate_answers_for_questionnaire(
        session,
        qnr_id,
        ws_id,
        model_override=model_override,
        response_style_override=response_style_override,
        job=job,
        effects=effects,
    )
    logging.getLogger(__name__).info(
        "WORKER: answers saved job_id=%s questionnaire_id=%s count=%s",
        job.id,
        qnr_id,
        count,
    )
    try:
        prev = json.loads(job.result or "{}")
        prev["count"] = count
        prev["generated"] = count
        if "total" not in prev:
            prev["total"] = count
        job.result = json.dumps(prev)
    except Exception:
        job.result = json.dumps({"count": count, "generated": count, "total": count})
    _raise_for_generation_errors(job, session)


def _raise_for_generation_errors(job: Job, session) -> None:
    """TC-10-002: never label a run "completed" while provider errors left placeholders behind.

    Per-question provider failures become ``insufficient_evidence`` placeholders (``insufficient_reason=llm_error``)
    and are counted in ``result.stats`` by ``answer_generation``. Auth/permission/config failures stop the job
    explicitly (terminal); transient ones (429/timeout/5xx/connection, after the inner retries) fail the attempt as
    retryable so the job-level retry regenerates only those placeholders. Bad-request/unknown per-question errors
    stay as visible placeholders (counted in ``stats.llm_errors``) and do not fail the job.
    """
    try:
        data = json.loads(job.result or "{}")
    except (TypeError, ValueError):
        return
    stats = data.get("stats") if isinstance(data, dict) else None
    if not isinstance(stats, dict):
        return
    auth = int(stats.get("llm_errors_auth_config") or 0)
    transient = int(stats.get("llm_errors_retryable") or 0)
    if not auth and not transient:
        return
    total = data.get("total")
    session.commit()  # keep the progress/stats of this attempt visible on the job
    if auth:
        code = stats.get("llm_error_code_auth_config")
        if not is_fatal_code(code) or is_retryable_code(code):
            code = AUTH_FAILED
        raise TerminalJobError(
            code,
            f"{auth} of {total} question(s) failed: the AI provider rejected the credentials or configuration "
            f"({code}). Failed questions were left as insufficient-evidence placeholders.",
        )
    code = stats.get("llm_error_code_retryable")
    if not is_retryable_code(code):
        code = "upstream_unavailable"
    raise RetryableJobError(
        code,
        f"{transient} of {total} question(s) failed with a transient AI provider error ({code}); "
        "only those questions are regenerated on retry.",
    )


def run_export(job: Job, session, payload: dict) -> None:
    """Export questionnaire with answers to XLSX or DOCX (EXP-07, EXP-05)."""
    import json
    from pathlib import Path

    from app.models import Answer, ExportRecord, Question, Questionnaire
    from app.services.answer_evidence_policy import answer_text_for_export
    from app.services.docx_writer import create_export_from_questionnaire_docx
    from app.services.fallback_export import create_fallback_pack_docx
    from app.services.xlsx_writer import create_export_from_questionnaire

    # Keep this attempt's token even if a rollback/refresh later sees a newer owner.
    owner = _lease_owner(job)
    unavailable = "Export references are unavailable"
    if not isinstance(payload, dict):
        raise ValueError(unavailable)
    qnr_id = payload.get("questionnaire_id")
    ws_id = payload.get("workspace_id")
    # Enqueue emits JSON integers. Never coerce booleans, floats or strings into
    # authority, or pass out-of-range Integer references to the database.
    if any(type(value) is not int or not 0 < value <= 2147483647 for value in (qnr_id, ws_id)):
        raise ValueError(unavailable)
    current_workspace = session.query(Job.workspace_id).filter(Job.id == job.id).scalar()
    if ws_id != job.workspace_id or ws_id != current_workspace:
        raise ValueError(unavailable)
    qnr = (
        session.query(Questionnaire)
        .filter(
            Questionnaire.id == qnr_id,
            Questionnaire.workspace_id == ws_id,
            Questionnaire.deleted_at.is_(None),
        )
        .populate_existing()
        .first()
    )
    if not qnr or not qnr.storage_key:
        raise ValueError(unavailable)
    existing_rec = (
        session.query(ExportRecord)
        .filter(ExportRecord.job_id == job.id)
        .populate_existing()
        .first()
    )
    if existing_rec is not None:
        # A mismatched job-linked record is unavailable, not permission to render
        # again. Check current columns before exposing any replay metadata.
        if existing_rec.workspace_id != ws_id or existing_rec.questionnaire_id != qnr_id:
            raise ValueError(unavailable)
        # A previous attempt committed the record (and therefore uploaded its object): reuse it.
        job.result = json.dumps(
            {
                "export_record_id": existing_rec.id,
                "storage_key": existing_rec.storage_key,
                "outcome": "already_applied",
            }
        )
        return
    effects = JobEffects(session, job)
    _record_usage_once(session, job, effects, "exports")
    storage = StorageClient()
    file_svc = FileService(storage)
    raw_bytes = file_svc.download_raw(qnr.storage_key)
    questions = session.query(Question).filter(Question.questionnaire_id == qnr_id).all()
    answers = {
        a.question_id: a
        for a in session.query(Answer)
        .filter(Answer.question_id.in_([q.id for q in questions]))
        .all()
    }
    question_list = [
        {"id": q.id, "source_location": q.source_location, "text": q.text or ""} for q in questions
    ]
    question_to_answer = {
        q.id: answer_text_for_export(
            text=(answers[q.id].text if answers.get(q.id) else None),
            status=(answers[q.id].status if answers.get(q.id) else None),
        )
        for q in questions
    }
    offset = settings.export_answer_col_offset
    wanted = (payload.get("format") or "xlsx").lower()
    if wanted not in ("xlsx", "docx"):
        wanted = "xlsx"
    ext = Path(qnr.filename or qnr.storage_key or "export.xlsx").suffix.lower()
    use_fallback = ext == ".pdf"

    try:
        if wanted == "docx":
            if use_fallback or ext not in (".docx", ".doc"):
                out_bytes = create_fallback_pack_docx(question_list, question_to_answer)
                base = (qnr.filename or "export").rsplit(".", 1)[0]
                out_filename = f"{base}_answers.docx"
            else:
                out_bytes = create_export_from_questionnaire_docx(
                    raw_bytes, question_list, question_to_answer, answer_col_offset=offset
                )
                out_filename = qnr.filename or "export.docx"
        elif use_fallback or (wanted == "xlsx" and ext in (".docx", ".doc")):
            out_bytes = create_fallback_pack_docx(question_list, question_to_answer)
            base = (qnr.filename or "export").rsplit(".", 1)[0]
            out_filename = f"{base}_answers.docx"
        elif ext in (".docx", ".doc"):
            out_bytes = create_export_from_questionnaire_docx(
                raw_bytes, question_list, question_to_answer, answer_col_offset=offset
            )
            out_filename = qnr.filename or "export.docx"
        else:
            out_bytes = create_export_from_questionnaire(
                raw_bytes, question_list, question_to_answer, answer_col_offset=offset
            )
            out_filename = qnr.filename or "export.xlsx"
    except Exception:
        out_bytes = create_fallback_pack_docx(question_list, question_to_answer)
        base = (qnr.filename or "export").rsplit(".", 1)[0]
        out_filename = f"{base}_answers_fallback.docx"

    # The deterministic key is shared by retries. Serialize the final PUT/record commit with
    # claims, cancellation and orphan deletion using the existing job row lock. Render first,
    # so the lock does not cover expensive document work. A stale owner must never PUT.
    if owner:
        confirm_lease_for_commit(session, job.id, owner)
    try:
        key = file_svc.upload_export(ws_id, out_bytes, out_filename, job_id=job.id)
    except Exception:
        session.rollback()
        raise
    rec = ExportRecord(
        workspace_id=ws_id,
        questionnaire_id=qnr_id,
        storage_key=key,
        filename=out_filename,
        status="completed",
        job_id=job.id,
    )
    session.add(rec)
    effects.mark_applied(EFFECT_EXPORT, {"storage_key": key})
    from app.services.storage_reconcile import commit_or_discard_object

    commit_or_discard_object(session, storage, storage.bucket_exports, key)
    session.refresh(rec)
    job.result = json.dumps({"export_record_id": rec.id, "storage_key": key})


def _record_usage_once(session, job: Job, effects: JobEffects, resource_type: str) -> None:
    """Count quota usage once per job, not once per attempt (TC-10-003). Commits with the next commit."""
    from app.services.quota_service import record_usage

    effect = f"usage:{resource_type}"
    if effects.is_applied(effect):
        return
    record_usage(session, job.workspace_id, resource_type)
    effects.mark_applied(effect)


def run_job(job: Job, session) -> None:
    """Execute job based on kind. Quota usage for AI/export jobs is recorded once per job by the handlers."""
    payload = json.loads(job.payload) if job.payload else {}
    if job.kind == "parse_questionnaire":
        run_parse_questionnaire(job, session, payload)
    elif job.kind == "parse_evidence":
        pass
    elif job.kind == "index_document":
        run_index_document(job, session, payload)
    elif job.kind == "generate_answers":
        run_generate_answers(job, session, payload)
    elif job.kind == "export":
        run_export(job, session, payload)
    else:
        raise ValueError(f"Unknown job kind: {job.kind}")


def _persist_job_audit(
    session, job: Job, action: str, payload: dict, error: str | None, extra: dict | None = None
) -> None:
    """Persist job completion/failure/retry for audit trail."""
    details = {"kind": job.kind, "workspace_id": job.workspace_id}
    if extra:
        details.update(extra)
    if payload.get("document_id") is not None:
        details["document_id"] = payload["document_id"]
    if payload.get("questionnaire_id") is not None:
        details["questionnaire_id"] = payload["questionnaire_id"]
    if error:
        details["error"] = error[:1000]
    persist_audit(
        session,
        action,
        workspace_id=job.workspace_id,
        resource_type="job",
        resource_id=job.id,
        details=details,
    )


def _queued_duplicate_id(session, job: Job) -> int | None:
    """Id of another QUEUED job with the same (workspace, kind, idempotency_key), if any (TC-10-003 index)."""
    if not job.idempotency_key:
        return None
    row = (
        session.query(Job.id)
        .filter(
            Job.workspace_id == job.workspace_id,
            Job.kind == job.kind,
            Job.idempotency_key == job.idempotency_key,
            Job.status == JobStatus.QUEUED.value,
            Job.id != job.id,
        )
        .first()
    )
    return row[0] if row else None


def _still_running_for_owner(session, job: Job) -> bool:
    """Lock the row. True only when it is still ``running`` for this owner.

    A cancel, or another worker, that already committed a different status or owner makes this
    false. The caller then skips the terminal write. ``lease_owner`` NULL matches NULL.
    """
    owner = _lease_owner(job)
    with session.no_autoflush:
        row = session.execute(
            text("SELECT status, lease_owner FROM jobs WHERE id = :id FOR UPDATE"),
            {"id": job.id},
        ).fetchone()
    if row is None:
        return False
    status, lease_owner = row[0], row[1]
    # Fail closed. Only the string "running" for this owner may take the write.
    # None, a non-string, or any other status skips it.
    if status != JobStatus.RUNNING.value:
        return False
    return lease_owner == owner


def _try_schedule_retry(
    session, job: Job, code: str, message: str, next_at: datetime
) -> int | None:
    """Re-queue ``job`` for ``next_at``. Returns None on success, else the id of the identical queued job that
    already holds the queued idempotency slot (then the job is not re-queued)."""
    dup = _queued_duplicate_id(session, job)
    if dup is not None:
        return dup
    try:
        with session.begin_nested():
            job.status = JobStatus.QUEUED.value
            job.error_code = code
            job.error = message
            job.next_attempt_at = next_at
            job.completed_at = None
            job.lease_owner = None
            job.lease_expires_at = None
            session.flush()
    except IntegrityError:
        # Lost a race with a new enqueue of the same input (uq_jobs_queued_idempotency_key).
        return _queued_duplicate_id(session, job) or -1
    return None


def _clear_stale_attempt_error(
    job: Job, prior_error: str | None, prior_error_code: str | None
) -> None:
    """On success, drop the error an earlier failed attempt left on the job (history is in the audit log).

    Only values unchanged since the job was claimed are cleared: an ``error``/``error_code`` that the
    handler set during this run (e.g. a non-fatal ``evidence_gaps_failed`` on a completed job) is kept.
    """
    if getattr(job, "error_code", None) == prior_error_code:
        job.error_code = None
    if getattr(job, "error", None) == prior_error:
        job.error = None


def _job_already_completed(session, job: Job, *, reraise: bool = False) -> bool:
    """True when the database already records ``job`` as completed.

    The normal failure path rolls back and returns False when the status query fails, so a
    worker whose transaction is already broken can still classify the failure. Recovery holds
    ``FOR UPDATE`` (TC-10-001a). Rolling back there would drop that lock after the token swap
    and then classify without it, so ``reraise=True`` lets the error propagate. The caller
    rolls the open transaction back, and the job stays as it was.
    """
    try:
        status = session.query(Job.status).filter(Job.id == job.id).scalar()
    except Exception:
        if reraise:
            raise
        session.rollback()
        return False
    return status == JobStatus.COMPLETED.value


def _handle_job_failure(
    session,
    job: Job,
    payload: dict,
    exc: Exception,
    duration_ms: float,
    *,
    rollback_first: bool = True,
    abandoned_owner_prefix: str | None = None,
) -> None:
    """TC-10-002: classify the failure, then either schedule a bounded retry or fail explicitly.

    * Retryable (429 / timeout / 5xx / connection / DB unavailable) and attempts left: the job goes back to
      ``queued`` with ``error_code``, a safe ``error`` describing the failed attempt and ``next_attempt_at``
      (exponential backoff with jitter, capped). Audited as ``job.retry_scheduled``. No admin alert yet.
    * Otherwise: ``failed`` with ``error_code``. Retryable codes that ran out of attempts are prefixed
      "Retries exhausted after N attempts" so exhaustion is never mistaken for success or a one-off failure.
    Raw provider/storage bodies are never stored in ``job.error`` for upstream codes.
    """
    log = logging.getLogger(__name__)
    # Recovery holds FOR UPDATE and must not drop that lock before the status write.
    if rollback_first:
        session.rollback()
    if _job_already_completed(session, job, reraise=not rollback_first):
        # The job's completion is already committed (e.g. a post-commit step raised). Never turn it into a
        # failure or retry, and keep the error_code it completed with (a completed job can carry a
        # non-fatal code, e.g. TC-02-BUG-015's evidence_gaps_failed).
        log.warning(
            "job_id=%s kind=%s raised after it completed; status and error_code left unchanged (%s)",
            job.id,
            job.kind,
            type(exc).__name__,
        )
        return
    # A cancel (or a lost lease) that committed while this attempt ran must not be overwritten
    # by a retry or a failure row.
    if not _still_running_for_owner(session, job):
        session.rollback()
        log.warning(
            "job_id=%s is no longer running for this owner; failure was not applied",
            job.id,
        )
        return
    code = classify(exc)
    retryable = is_retryable_code(code)
    attempt = int(job.attempt or 0)
    max_attempts = effective_max_attempts(job.max_attempts)
    safe = safe_error_message(exc, code)
    now = _utcnow_naive()
    try:
        mark_unsettled_uncertain(session, job)
    except Exception:
        log.warning("mark_unsettled_uncertain failed job_id=%s", job.id, exc_info=True)

    dup_id = None
    if retryable and attempt < max_attempts:
        delay = backoff_delay(
            attempt,
            base=retry_base_seconds(),
            cap=retry_max_seconds(),
            retry_after=retry_after_seconds(exc),
        )
        next_at = now + timedelta(seconds=delay)
        message = (
            f"Attempt {attempt} of {max_attempts} failed ({code}): {safe}. "
            f"Next attempt scheduled at {next_at.isoformat(timespec='seconds')}Z."
        )
        dup_id = _try_schedule_retry(session, job, code, message, next_at)
        if dup_id is None:
            log_job_failure(
                job.kind,
                job.id,
                job.workspace_id,
                message,
                duration_ms,
                document_id=payload.get("document_id"),
                questionnaire_id=payload.get("questionnaire_id"),
            )
            JOB_COMPLETED_TOTAL.labels(kind=job.kind, status="retry_scheduled").inc()
            log.warning(
                "JOB_RETRY_SCHEDULED job_id=%s kind=%s workspace_id=%s error_code=%s attempt=%s/%s delay=%.1fs",
                job.id,
                job.kind,
                job.workspace_id,
                code,
                attempt,
                max_attempts,
                delay,
            )
            if abandoned_owner_prefix is not None:
                _flush_abandoned_audit(
                    session, job, payload, abandoned_owner_prefix, attempt, max_attempts
                )
            _persist_job_audit(
                session,
                job,
                "job.retry_scheduled",
                payload,
                error=message,
                extra={
                    "error_code": code,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "next_attempt_at": next_at.isoformat(),
                    "delay_seconds": round(delay, 3),
                },
            )
            if job.kind == "index_document" and payload.get("document_id"):
                # index_service marks the document failed before raising; a retry is pending, so show the
                # document as awaiting indexing (with the attempt's error) rather than permanently failed.
                doc = session.query(Document).filter(Document.id == payload["document_id"]).first()
                if doc is not None and doc.status == "failed":
                    doc.status = "uploaded"
                    doc.index_error = message[:512]
            session.commit()
            return

    exhausted = retryable and dup_id is None
    if dup_id is not None:
        ref = f"job {dup_id}" if dup_id > 0 else "another job"
        message = (
            f"Attempt {attempt} of {max_attempts} failed ({code}): {safe}. Not retried: an identical queued "
            f"{ref} will process this input."
        )
    elif exhausted:
        message = f"Retries exhausted after {attempt} attempt(s) ({code}): {safe}"
    else:
        message = safe
    job.status = JobStatus.FAILED.value
    job.error_code = code
    job.error = message
    job.next_attempt_at = None
    job.lease_owner = None
    job.lease_expires_at = None
    job.completed_at = datetime.now(timezone.utc)
    session.merge(job)
    log_job_failure(
        job.kind,
        job.id,
        job.workspace_id,
        message,
        duration_ms,
        document_id=payload.get("document_id"),
        questionnaire_id=payload.get("questionnaire_id"),
    )
    JOB_COMPLETED_TOTAL.labels(kind=job.kind, status="failed").inc()
    logging.getLogger("trustcopilot.alert").warning(
        "ALERT_JOB_FAILURE job_id=%s kind=%s workspace_id=%s error_code=%s error=%s",
        job.id,
        job.kind,
        job.workspace_id,
        code,
        message[:200],
    )
    if abandoned_owner_prefix is not None:
        _flush_abandoned_audit(session, job, payload, abandoned_owner_prefix, attempt, max_attempts)
    _persist_job_audit(
        session,
        job,
        "job.failed",
        payload,
        error=message,
        extra={
            "error_code": code,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "retries_exhausted": exhausted,
        },
    )
    if job.kind in ("export", "generate_answers"):
        try:
            label = "Export" if job.kind == "export" else "Draft answer generation"
            notify_admins(
                session,
                job.workspace_id,
                f"{label} failed",
                message[:200],
                category="error",
                link="/dashboard/exports" if job.kind == "export" else "/dashboard/review",
            )
        except Exception:
            pass
    if job.kind == "index_document":
        doc_id = payload.get("document_id")
        if doc_id:
            doc = session.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.status = "failed"
                doc.index_error = message[:512] if message else None
                session.merge(doc)
    if job.kind == "parse_questionnaire" and isinstance(exc, PdfTextError):
        # Image-only / encrypted / corrupt PDF (TC-01-003a): surface the readable message on the questionnaire
        # too, instead of leaving it "uploaded". PdfTextError is a ValueError, so it is terminal (bad_input).
        qnr_id = payload.get("questionnaire_id")
        if qnr_id:
            qnr = session.query(Questionnaire).filter(Questionnaire.id == qnr_id).first()
            if qnr:
                qnr.status = "failed"
                qnr.parse_metadata = json.dumps({"count": 0, "error": str(exc)})
                session.merge(qnr)
    session.commit()


_last_orphan_sweep_monotonic = 0.0


def enqueue_missing_index_jobs(session) -> None:
    """Startup hook: missing index and parse jobs, then the orphan sweep.

    The name is kept so a probe test can replace this whole hook. The sweep logs and continues
    when storage is unavailable. It does not raise.
    """
    global _last_orphan_sweep_monotonic
    from app.services.storage_reconcile import startup_reconcile

    startup_reconcile(session)
    _last_orphan_sweep_monotonic = time.monotonic()


def _maybe_sweep_orphans() -> None:
    """On an idle loop, sweep again only after a full grace period since the last attempt."""
    global _last_orphan_sweep_monotonic
    from app.services.storage_reconcile import orphan_grace_seconds, sweep_orphans_best_effort

    if time.monotonic() - _last_orphan_sweep_monotonic < orphan_grace_seconds():
        return
    _last_orphan_sweep_monotonic = time.monotonic()
    session = SessionFactory()
    try:
        sweep_orphans_best_effort(session)
    finally:
        session.close()


def _lease_owner(job) -> str | None:
    owner = getattr(job, "lease_owner", None)
    return owner if isinstance(owner, str) and owner else None


def _start_job_lease_heartbeat(job_id: int, owner: str) -> JobLeaseHeartbeat:
    """Background renewal for one claimed job. Uses its own sessions so the job transaction stays open."""

    def _renew() -> bool:
        return renew_lease(
            job_id,
            owner,
            extend_seconds=lease_seconds(),
            session_factory=SessionFactory,
        )

    heartbeat = JobLeaseHeartbeat(_renew, interval_sec=lease_heartbeat_seconds())
    heartbeat.start()
    return heartbeat


def _audit_lease_lost(job_id: int, workspace_id: int | None, owner: str) -> None:
    """Record that this owner stopped without committing. Separate session; the job session rolled back."""
    session = SessionFactory()
    try:
        persist_audit(
            session,
            "job.lease_lost",
            workspace_id=workspace_id,
            resource_type="job",
            resource_id=job_id,
            details={"owner_prefix": owner[:8], "reason": "lease_lost"},
        )
    except Exception:
        session.rollback()
        logging.getLogger(__name__).warning(
            "job.lease_lost audit failed job_id=%s", job_id, exc_info=True
        )
    finally:
        session.close()


def _flush_abandoned_audit(
    session, job: Job, payload: dict, owner_prefix: str, attempt: int, max_attempts: int
) -> None:
    """Add ``job.abandoned`` to the open transaction. The classifying commit writes it.

    ``persist_audit`` commits, so this must not call it. The classification's own audit
    commit is what makes this row durable.
    """
    from app.models import AuditEvent

    details = {
        "kind": job.kind,
        "workspace_id": job.workspace_id,
        "error_code": LEASE_EXPIRED,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "previous_owner_prefix": owner_prefix,
        "status": job.status,
    }
    if payload.get("document_id") is not None:
        details["document_id"] = payload["document_id"]
    if payload.get("questionnaire_id") is not None:
        details["questionnaire_id"] = payload["questionnaire_id"]
    if job.error:
        details["error"] = str(job.error)[:1000]
    session.add(
        AuditEvent(
            action="job.abandoned",
            workspace_id=job.workspace_id,
            resource_type="job",
            resource_id=str(job.id),
            details=json.dumps(details),
        )
    )
    session.flush()


def recover_abandoned_jobs(session, *, limit: int = 20) -> int:
    """Send abandoned running jobs back through retry classification (TC-10-001, TC-10-001b).

    One row is atomic. ``FOR UPDATE SKIP LOCKED``, the replacement owner token, the
    ``job.abandoned`` audit row, and the retry-or-fail classification commit together.
    The abandoned audit is flushed before that commit, so a claim cannot land between
    the classification and the audit.

    The next row is not atomic with this one. After the commit a worker may claim the
    job before this loop reads it again. That claim is a normal claim of a queued job.
    If the post-commit read no longer shows the classified status, this row is logged
    and the loop continues. The abandoned audit is already committed. The remaining
    rows are still recovered.

    An expired lease is taken first. A NULL lease is not an expired lease. It is abandoned
    only when ``COALESCE(updated_at, started_at)`` is at least ``JOB_NULL_LEASE_GRACE_SECONDS``
    before database ``now()`` (TC-10-001b). A younger row, or a row with neither timestamp,
    is left alone. The attempt was counted at claim time and is not incremented here.
    """
    log = logging.getLogger(__name__)
    exc = RetryableJobError(LEASE_EXPIRED, LEASE_EXPIRED_MESSAGE)
    count = 0
    while count < limit:
        locked = lock_expired_lease(session)
        if locked is None:
            locked = lock_null_lease_past_grace(session, null_lease_grace_seconds())
        if locked is None:
            session.rollback()
            return count
        job_id, previous_owner = locked
        token = new_lease_owner_token()
        claim_lease_expiry(session, job_id, token, lease_seconds())
        session.expire_all()
        job = session.get(Job, job_id)
        if job is None or job.lease_owner != token:
            # The swap is still uncommitted. Continuing would lock this same row again.
            log.warning(
                "abandoned job recovery skipped job_id=%s; lease token was not kept", job_id
            )
            session.rollback()
            return count
        payload = json.loads(job.payload) if job.payload else {}
        prefix = (previous_owner or "")[:8]
        attempt_before = int(job.attempt or 0)
        _handle_job_failure(
            session,
            job,
            payload,
            exc,
            0.0,
            rollback_first=False,
            abandoned_owner_prefix=prefix,
        )
        session.expire_all()
        job = session.get(Job, job_id)
        if (
            job is None
            or int(job.attempt or 0) != attempt_before
            or job.status not in (JobStatus.QUEUED.value, JobStatus.FAILED.value)
        ):
            log.warning(
                "abandoned job recovery lost job_id=%s after classify; continuing the batch",
                job_id,
            )
            session.rollback()
            continue
        count += 1
    return count


def _process_one_job() -> bool:
    """Claim and process one job in a thread-safe manner. Returns True if work was done."""
    session = SessionFactory()
    lease_heartbeat = None
    try:
        HEARTBEAT_STATE.loop_tick()

        global last_compliance_webhook_run, last_usage_cleanup_run, last_dedupe_prune_run
        if time.time() - last_dedupe_prune_run >= USAGE_CLEANUP_INTERVAL_SEC:
            try:
                from app.services.notification_service import prune_dedupe_claims

                if prune_dedupe_claims(session):
                    session.commit()
            except Exception:
                session.rollback()
            finally:
                last_dedupe_prune_run = time.time()
        if time.time() - last_usage_cleanup_run >= USAGE_CLEANUP_INTERVAL_SEC:
            try:
                from app.services.quota_service import cleanup_old_usage

                cleaned = cleanup_old_usage(session)
                if cleaned:
                    session.commit()
            except Exception:
                session.rollback()
            try:
                from app.core.idempotency import cleanup_expired

                cleanup_expired(session)
            except Exception:
                session.rollback()
                logging.getLogger(__name__).warning("idempotency key cleanup failed", exc_info=True)
            finally:
                last_usage_cleanup_run = time.time()
        if time.time() - last_compliance_webhook_run >= COMPLIANCE_WEBHOOK_INTERVAL_SEC:
            try:
                process_compliance_webhook_outbox(session)
            except Exception as e:
                session.rollback()
                logging.getLogger(__name__).warning("compliance_webhook_outbox run failed: %s", e)
            finally:
                last_compliance_webhook_run = time.time()

        recovered = 0
        try:
            recovered = recover_abandoned_jobs(session)
        except Exception:
            session.rollback()
            logging.getLogger(__name__).warning("abandoned job recovery failed", exc_info=True)
        job = claim_job(session)
        if not job:
            return recovered > 0

        job_started_at = time.monotonic()
        payload = json.loads(job.payload) if job.payload else {}
        log_job_start(
            job.kind,
            job.id,
            job.workspace_id,
            document_id=payload.get("document_id"),
            questionnaire_id=payload.get("questionnaire_id"),
        )
        JOB_STARTED_TOTAL.labels(kind=job.kind).inc()
        HEARTBEAT_STATE.job_started(job.id)
        # TC-10-002: what an earlier failed attempt left on the job (cleared on success below).
        prior_error = getattr(job, "error", None)
        prior_error_code = getattr(job, "error_code", None)
        # TC-10-001: captured before a rollback expires the ORM object.
        owner = _lease_owner(job)
        leased_job_id = job.id
        leased_workspace_id = job.workspace_id
        try:
            if owner:
                lease_heartbeat = _start_job_lease_heartbeat(leased_job_id, owner)
                install_commit_fence(session, leased_job_id, owner)
            run_job(job, session)
            # TC-10-001: lock and confirm the lease BEFORE the completion is flushed.
            # persist_audit flushes then commits, so a fence check after that flush would see
            # status=completed and refuse the commit that just wrote it.
            # A cancel clears the lease, so the heartbeat loses and this confirm raises LeaseLost.
            # The result is not written.
            if owner:
                if lease_heartbeat is not None and lease_heartbeat.lost:
                    raise LeaseLost(leased_job_id)
                confirm_lease_for_commit(session, leased_job_id, owner)
                uninstall_commit_fence(session)
            job.status = JobStatus.COMPLETED.value
            job.completed_at = datetime.now(timezone.utc)
            _clear_stale_attempt_error(job, prior_error, prior_error_code)
            job.next_attempt_at = None
            if owner:
                job.lease_owner = None
                job.lease_expires_at = None
            duration_ms = (time.monotonic() - job_started_at) * 1000
            log_job_success(
                job.kind,
                job.id,
                job.workspace_id,
                duration_ms,
                document_id=payload.get("document_id"),
                questionnaire_id=payload.get("questionnaire_id"),
            )
            JOB_COMPLETED_TOTAL.labels(kind=job.kind, status="completed").inc()
            _persist_job_audit(session, job, "job.completed", payload, error=None)
            if _job_outcome(job) == "superseded":
                # TC-10-003: the job's input changed or was deleted before it ran; nothing was overwritten.
                _persist_job_audit(session, job, "job.superseded", payload, error=None)
            if job.kind == "export":
                try:
                    notify_workspace(
                        session,
                        job.workspace_id,
                        "Export completed",
                        "Your export is ready for download.",
                        category="success",
                        link="/dashboard/exports",
                    )
                except Exception:
                    pass
            elif job.kind == "generate_answers":
                try:
                    notify_workspace(
                        session,
                        job.workspace_id,
                        "Draft answers ready",
                        "AI draft answers are in the review workspace. Open the questionnaire to review supporting evidence and approve.",
                        category="success",
                        link="/dashboard/review",
                    )
                except Exception:
                    pass
                try:
                    evaluate_generation_result(session, job, payload)
                except Exception:
                    pass
                try:
                    ws_name = "Workspace"
                    from app.models.workspace import Workspace

                    ws = session.query(Workspace).filter(Workspace.id == job.workspace_id).first()
                    if ws:
                        ws_name = ws.name or ws_name
                    evaluate_and_fire_compliance_events(
                        session, job.workspace_id, ws_name, job_id=job.id
                    )
                except Exception:
                    pass
            elif job.kind == "parse_questionnaire" and _job_outcome(job) != "superseded":
                # TC-10-003d: commit the parse completion before auto-generate.
                # enqueue_job rolls this session back when it raises EnqueueConflictError,
                # which would drop completion state that was still pending. The conflict
                # is logged and recorded on the job result; it does not fail the parse.
                session.commit()
                try:
                    maybe_auto_generate(session, job, payload)
                except EnqueueConflictError:
                    _record_auto_generate_enqueue_conflict(job)
                except Exception:
                    pass
            session.commit()
        except LeaseLost:
            uninstall_commit_fence(session)
            session.rollback()
            # A completion that already committed (the fence opens after that) is not a lost result.
            if not _job_already_completed(session, job):
                _audit_lease_lost(leased_job_id, leased_workspace_id, owner or "")
        except Exception as e:
            uninstall_commit_fence(session)
            lost = bool(owner) and not owns_lease(SessionFactory, leased_job_id, owner)
            if lost and not _job_already_completed(session, job):
                session.rollback()
                _audit_lease_lost(leased_job_id, leased_workspace_id, owner or "")
            else:
                _handle_job_failure(
                    session, job, payload, e, (time.monotonic() - job_started_at) * 1000
                )
        return True
    except Exception as e:
        print(f"Worker thread error: {e}")
        return False
    finally:
        uninstall_commit_fence(session)
        if lease_heartbeat is not None:
            lease_heartbeat.stop()
        HEARTBEAT_STATE.job_finished()
        session.close()


def main():
    # TC-07-001: same fail-closed startup check as the API; in production the worker must never
    # sign/derive keys from a random per-process secret.
    from app.core.session import enforce_production_session_secret

    enforce_production_session_secret("worker")
    # TC-03-001: the rest of the configuration contract (same production detector), before polling jobs.
    from app.core.config_contract import enforce_startup_contract

    for _problem in enforce_startup_contract("worker"):
        print(f"config warning: {_problem}", flush=True)
    from app.core.database import warn_if_database_time_zone_is_not_utc

    warn_if_database_time_zone_is_not_utc()
    print(
        f"Trust Copilot worker started (threads: {WORKER_MIN_THREADS}-{WORKER_MAX_THREADS}, initial: {WORKER_INITIAL_THREADS})"
    )
    heartbeat = HeartbeatThread(HEARTBEAT_STATE, write_db_heartbeat)
    heartbeat.start()
    session = SessionFactory()
    try:
        enqueue_missing_index_jobs(session)
    finally:
        session.close()

    while True:
        HEARTBEAT_STATE.loop_tick()
        had_work = _process_one_job()
        _adapt_thread_count(had_work)
        if not had_work:
            _maybe_sweep_orphans()
            time.sleep(2)


if __name__ == "__main__":
    main()
