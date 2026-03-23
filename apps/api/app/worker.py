"""Worker claim loop (JOB-02) — multi-threaded with adaptive scaling."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Same env semantics as main.py/database.py: in Docker do not load .env so compose env is used.
_in_docker = Path("/.dockerenv").exists() or os.environ.get("TRUST_COPILOT_IN_DOCKER") == "1"
if not _in_docker:
    _api_root = Path(__file__).resolve().parent.parent
    _repo_root = _api_root.parent.parent
    load_dotenv(_api_root / ".env", override=True)
    load_dotenv(_repo_root / ".env")

import io  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ThreadPoolExecutor, as_completed  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import and_, create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.pipeline_logging import log_job_failure, log_job_start, log_job_success  # noqa: E402
from app.core.metrics import JOB_COMPLETED_TOTAL, JOB_STARTED_TOTAL  # noqa: E402
from app.models import Document, Job, JobStatus, Question, Questionnaire  # noqa: E402
from app.core.audit import persist_audit  # noqa: E402
from app.services.file_service import FileService  # noqa: E402
from app.services.storage import StorageClient  # noqa: E402
from app.services.docx_questionnaire_parser import parse_docx_questionnaire  # noqa: E402
from app.services.pdf_questionnaire_parser import parse_pdf_questionnaire  # noqa: E402
from app.services.xlsx_questionnaire_parser import parse_xlsx_questionnaire  # noqa: E402
from app.services.compliance_webhook_delivery import process_compliance_webhook_outbox  # noqa: E402
from app.services.in_app_notification_service import notify_admins, notify_workspace  # noqa: E402
from app.services.automation_service import maybe_auto_generate, evaluate_generation_result  # noqa: E402
from app.services.compliance_event_service import evaluate_and_fire_compliance_events  # noqa: E402

settings = get_settings()
COMPLIANCE_WEBHOOK_INTERVAL_SEC = 30
USAGE_CLEANUP_INTERVAL_SEC = 3600
last_compliance_webhook_run = 0.0
last_usage_cleanup_run = 0.0
_last_claimed_workspace_id: int | None = None
engine = create_engine(settings.database_url, pool_size=12, max_overflow=8)
SessionFactory = sessionmaker(bind=engine)

WORKER_MIN_THREADS = 3
WORKER_MAX_THREADS = 10
WORKER_INITIAL_THREADS = 6

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
                logging.getLogger(__name__).info("worker: scaling up to %d threads", _active_threads)
        else:
            _consecutive_busy = 0
            _consecutive_idle += 1
            if _consecutive_idle >= 5 and _active_threads > WORKER_MIN_THREADS:
                _active_threads -= 1
                _consecutive_idle = 0
                logging.getLogger(__name__).info("worker: scaling down to %d threads", _active_threads)
        return _active_threads


def claim_job(session) -> Job | None:
    """Claim next queued job with round-robin fair scheduling across workspaces."""
    global _last_claimed_workspace_id

    base = session.query(Job).filter(
        and_(Job.status == JobStatus.QUEUED.value, Job.attempt < Job.max_attempts)
    )
    if _last_claimed_workspace_id is not None:
        job = (
            base.filter(Job.workspace_id != _last_claimed_workspace_id)
            .order_by(Job.created_at)
            .with_for_update(skip_locked=True)
            .first()
        )
        if not job:
            job = (
                base.order_by(Job.created_at)
                .with_for_update(skip_locked=True)
                .first()
            )
    else:
        job = (
            base.order_by(Job.created_at)
            .with_for_update(skip_locked=True)
            .first()
        )
    if not job:
        return None
    _last_claimed_workspace_id = job.workspace_id
    job.status = JobStatus.RUNNING.value
    job.attempt += 1
    job.started_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(job)
    return job


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
        raise ValueError(f"Questionnaire {qnr_id} workspace mismatch: {qnr.workspace_id} != {job.workspace_id}")
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
        for q in questions:
            session.add(Question(
                questionnaire_id=qnr_id,
                text=q["text"],
                section=q.get("section"),
                answer_type=q.get("answer_type"),
                source_location=q.get("source_location"),
                confidence=q.get("confidence"),
            ))
        qnr.status = "parsed"
        qnr.parse_metadata = json.dumps({"count": len(questions), "questions": questions[:50]})
        session.commit()
    finally:
        Path(path).unlink(missing_ok=True)


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
    storage = StorageClient()
    file_svc = FileService(storage)
    from app.services.index_service import index_document

    index_document(session, doc_id, storage, file_svc, job_id=job.id)


def run_generate_answers(job: Job, session, payload: dict) -> None:
    """Generate answers for questionnaire."""
    import json

    from app.core.config import get_settings
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
    count = generate_answers_for_questionnaire(
        session,
        qnr_id,
        ws_id,
        model_override=model_override,
        response_style_override=response_style_override,
        job=job,
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


def run_export(job: Job, session, payload: dict) -> None:
    """Export questionnaire with answers to XLSX or DOCX (EXP-07, EXP-05)."""
    import json
    from pathlib import Path

    from app.models import Answer, ExportRecord, Question, Questionnaire
    from app.services.answer_evidence_policy import answer_text_for_export
    from app.services.docx_writer import create_export_from_questionnaire_docx
    from app.services.fallback_export import create_fallback_pack_docx
    from app.services.xlsx_writer import create_export_from_questionnaire

    qnr_id = payload.get("questionnaire_id")
    ws_id = payload.get("workspace_id")
    if not qnr_id or not ws_id:
        raise ValueError("Missing questionnaire_id or workspace_id")
    qnr = session.query(Questionnaire).filter(
        Questionnaire.id == qnr_id,
        Questionnaire.workspace_id == ws_id,
    ).first()
    if not qnr or not qnr.storage_key:
        raise ValueError("Questionnaire not found or has no file")
    storage = StorageClient()
    file_svc = FileService(storage)
    raw_bytes = file_svc.download_raw(qnr.storage_key)
    questions = session.query(Question).filter(Question.questionnaire_id == qnr_id).all()
    answers = {a.question_id: a for a in session.query(Answer).filter(
        Answer.question_id.in_([q.id for q in questions])
    ).all()}
    question_list = [
        {"id": q.id, "source_location": q.source_location, "text": q.text or ""}
        for q in questions
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

    key = file_svc.upload_export(ws_id, out_bytes, out_filename)
    rec = ExportRecord(
        workspace_id=ws_id,
        questionnaire_id=qnr_id,
        storage_key=key,
        filename=out_filename,
        status="completed",
    )
    session.add(rec)
    session.commit()
    session.refresh(rec)
    job.result = json.dumps({"export_record_id": rec.id, "storage_key": key})


def run_job(job: Job, session) -> None:
    """Execute job based on kind. Enforces per-workspace quotas for AI and export jobs."""
    from app.services.quota_service import record_usage

    payload = json.loads(job.payload) if job.payload else {}
    if job.kind == "parse_questionnaire":
        run_parse_questionnaire(job, session, payload)
    elif job.kind == "parse_evidence":
        pass
    elif job.kind == "index_document":
        run_index_document(job, session, payload)
    elif job.kind == "generate_answers":
        record_usage(session, job.workspace_id, "ai_jobs")
        run_generate_answers(job, session, payload)
    elif job.kind == "export":
        record_usage(session, job.workspace_id, "exports")
        run_export(job, session, payload)
    else:
        raise ValueError(f"Unknown job kind: {job.kind}")


def _persist_job_audit(session, job: Job, action: str, payload: dict, error: str | None) -> None:
    """Persist job completion/failure for audit trail."""
    details = {"kind": job.kind, "workspace_id": job.workspace_id}
    if payload.get("document_id") is not None:
        details["document_id"] = payload["document_id"]
    if payload.get("questionnaire_id") is not None:
        details["questionnaire_id"] = payload["questionnaire_id"]
    if error:
        details["error"] = error[:1000]
    persist_audit(session, action, workspace_id=job.workspace_id, resource_type="job", resource_id=job.id, details=details)


def enqueue_missing_index_jobs(session) -> None:
    """At startup, queue index_document for any doc still 'uploaded' with no pending job (fixes backlogs)."""
    pending_doc_ids = set()
    for job in session.query(Job).filter(
        Job.kind == "index_document",
        Job.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value]),
    ).all():
        try:
            payload = json.loads(job.payload or "{}")
            if "document_id" in payload:
                pending_doc_ids.add(payload["document_id"])
        except Exception:
            pass
    added = 0
    for doc in session.query(Document).filter(Document.status == "uploaded").all():
        if doc.id in pending_doc_ids:
            continue
        session.add(Job(
            workspace_id=doc.workspace_id,
            kind="index_document",
            status=JobStatus.QUEUED.value,
            payload=json.dumps({"document_id": doc.id}),
        ))
        added += 1
    if added:
        session.commit()
        print(f"Worker: enqueued {added} index_document job(s) for previously uploaded docs.")


def _process_one_job() -> bool:
    """Claim and process one job in a thread-safe manner. Returns True if work was done."""
    session = SessionFactory()
    try:
        try:
            session.execute(text("UPDATE worker_heartbeat SET last_seen_utc = NOW() WHERE id = 1"))
            session.commit()
        except Exception:
            session.rollback()

        global last_compliance_webhook_run, last_usage_cleanup_run
        if time.time() - last_usage_cleanup_run >= USAGE_CLEANUP_INTERVAL_SEC:
            try:
                from app.services.quota_service import cleanup_old_usage
                cleaned = cleanup_old_usage(session)
                if cleaned:
                    session.commit()
            except Exception:
                session.rollback()
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

        job = claim_job(session)
        if not job:
            return False

        job_started_at = time.monotonic()
        payload = json.loads(job.payload) if job.payload else {}
        log_job_start(job.kind, job.id, job.workspace_id, document_id=payload.get("document_id"), questionnaire_id=payload.get("questionnaire_id"))
        JOB_STARTED_TOTAL.labels(kind=job.kind).inc()
        try:
            run_job(job, session)
            job.status = JobStatus.COMPLETED.value
            job.completed_at = datetime.now(timezone.utc)
            duration_ms = (time.monotonic() - job_started_at) * 1000
            log_job_success(job.kind, job.id, job.workspace_id, duration_ms, document_id=payload.get("document_id"), questionnaire_id=payload.get("questionnaire_id"))
            JOB_COMPLETED_TOTAL.labels(kind=job.kind, status="completed").inc()
            _persist_job_audit(session, job, "job.completed", payload, error=None)
            if job.kind == "export":
                try:
                    notify_workspace(session, job.workspace_id, "Export completed", "Your export is ready for download.", category="success", link="/dashboard/exports")
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
                    evaluate_and_fire_compliance_events(session, job.workspace_id, ws_name)
                except Exception:
                    pass
            elif job.kind == "parse_questionnaire":
                try:
                    maybe_auto_generate(session, job, payload)
                except Exception:
                    pass
            session.commit()
        except Exception as e:
            session.rollback()
            job.status = JobStatus.FAILED.value
            job.error = str(e)
            job.completed_at = datetime.now(timezone.utc)
            session.merge(job)
            duration_ms = (time.monotonic() - job_started_at) * 1000
            log_job_failure(job.kind, job.id, job.workspace_id, str(e), duration_ms, document_id=payload.get("document_id"), questionnaire_id=payload.get("questionnaire_id"))
            JOB_COMPLETED_TOTAL.labels(kind=job.kind, status="failed").inc()
            logging.getLogger("trustcopilot.alert").warning(
                "ALERT_JOB_FAILURE job_id=%s kind=%s workspace_id=%s error=%s",
                job.id, job.kind, job.workspace_id, (str(e))[:200],
            )
            _persist_job_audit(session, job, "job.failed", payload, error=str(e))
            if job.kind in ("export", "generate_answers"):
                try:
                    label = "Export" if job.kind == "export" else "Draft answer generation"
                    notify_admins(
                        session,
                        job.workspace_id,
                        f"{label} failed",
                        str(e)[:200],
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
                        doc.index_error = (str(e))[:512] if str(e) else None
                        session.merge(doc)
            session.commit()
        return True
    except Exception as e:
        print(f"Worker thread error: {e}")
        return False
    finally:
        session.close()


def main():
    print(f"Trust Copilot worker started (threads: {WORKER_MIN_THREADS}-{WORKER_MAX_THREADS}, initial: {WORKER_INITIAL_THREADS})")
    session = SessionFactory()
    try:
        enqueue_missing_index_jobs(session)
    finally:
        session.close()

    while True:
        had_work = _process_one_job()
        _adapt_thread_count(had_work)
        if not had_work:
            time.sleep(2)


if __name__ == "__main__":
    main()
