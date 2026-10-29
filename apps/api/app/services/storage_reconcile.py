"""Reconcile object storage with database rows (TC-10-005).

Uploads write the object first, then commit the domain row and its job in one transaction. If that
commit fails, the request deletes the object when no row references it. If that delete also fails,
the object is an orphan. An export writes its artifact and then commits the export row; a failed
commit deletes the object on the same condition.

There is no outbox table. The sweep lists the raw and export buckets and deletes a key only when
all of the following hold:

* the key sits under ``raw/{workspace}/``, ``trust-requests/{workspace}/`` or ``exports/{workspace}/``
* no document, questionnaire, export, trust-request attachment, or evidence content ref uses it
* no queued or running job names it as ``input_version`` or as a payload ``storage_key``
* the object store's ``LastModified`` is strictly older than the grace period

Object age is the store clock, not a database column. Dry-run is the default for the CLI. The
worker sweep deletes. Both are safe to run again. A missing ``LastModified`` is kept.

Raw upload keys stay random. A content-hash key would let a rolled-back second upload of the same
bytes delete the live original. The sweep lists keys instead of recomputing them. Export keys are
already one object per job.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.orphan_grace import orphan_grace_seconds
from app.models import (
    Document,
    EvidenceVersion,
    ExportRecord,
    Job,
    JobStatus,
    Questionnaire,
    TrustRequest,
)
from app.services.job_effects import EnqueueConflictError, enqueue_job, job_idempotency_key

logger = logging.getLogger(__name__)

_KEY_WORKSPACE = re.compile(r"^(raw|trust-requests|exports)/([0-9]+)/")
_ACTIVE_JOB = (JobStatus.QUEUED.value, JobStatus.RUNNING.value)


@dataclass(frozen=True)
class OrphanReconcileResult:
    """What one sweep saw. ``candidates`` is sorted by bucket, then key."""

    dry_run: bool
    grace_seconds: int
    workspace_id: int | None
    candidates: tuple[tuple[str, str], ...]
    deleted: tuple[tuple[str, str], ...]
    failed: tuple[tuple[str, str], ...]
    spared: tuple[tuple[str, str], ...]


def object_workspace_id(key: str | None) -> int | None:
    """Workspace id encoded in a raw, trust-request, or export key. None when the layout differs."""
    match = _KEY_WORKSPACE.match(key or "")
    if not match:
        return None
    return int(match.group(2))


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _payload_storage_key(payload: str | None) -> str | None:
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    key = data.get("storage_key")
    if isinstance(key, str) and key:
        return key
    return None


def referenced_storage_keys(session: Session) -> set[str]:
    """Every key a sweep must not delete. Raises if the database cannot be read.

    Soft-deleted rows are included. An archived document is still an original.
    """
    keys: set[str] = set()
    columns = (
        session.query(Document.storage_key),
        session.query(Questionnaire.storage_key),
        session.query(ExportRecord.storage_key),
        session.query(TrustRequest.attachment_storage_key),
        session.query(EvidenceVersion.content_ref),
        session.query(Job.input_version).filter(Job.status.in_(_ACTIVE_JOB)),
    )
    for query in columns:
        for (value,) in query:
            if isinstance(value, str) and value:
                keys.add(value)
    for (payload,) in session.query(Job.payload).filter(Job.status.in_(_ACTIVE_JOB)):
        found = _payload_storage_key(payload)
        if found:
            keys.add(found)
    return keys


def storage_key_is_referenced(session: Session, key: str) -> bool:
    """True when any protecting row currently names ``key``. Raises if the read fails."""
    if not key:
        return True
    point = (
        session.query(Document.id).filter(Document.storage_key == key).first(),
        session.query(Questionnaire.id).filter(Questionnaire.storage_key == key).first(),
        session.query(ExportRecord.id).filter(ExportRecord.storage_key == key).first(),
        session.query(TrustRequest.id).filter(TrustRequest.attachment_storage_key == key).first(),
        session.query(EvidenceVersion.id).filter(EvidenceVersion.content_ref == key).first(),
        session.query(Job.id).filter(Job.input_version == key, Job.status.in_(_ACTIVE_JOB)).first(),
    )
    if any(point):
        return True
    for (payload,) in session.query(Job.payload).filter(Job.status.in_(_ACTIVE_JOB)):
        if _payload_storage_key(payload) == key:
            return True
    return False


def discard_if_unreferenced(session: Session, storage, bucket: str, key: str | None) -> bool:
    """Delete ``key`` when nothing references it. Never raises.

    Returns True only when the delete succeeded. A referenced key, a failed reference read, and a
    failed delete all return False and leave the object in place. The sweep retries a failed delete
    after the grace period.
    """
    if not key:
        return False
    try:
        referenced = storage_key_is_referenced(session, key)
    except Exception:
        logger.warning(
            "refusing to delete storage object; reference check failed bucket=%s key=%s",
            bucket,
            key,
            exc_info=True,
        )
        return False
    if referenced:
        logger.warning(
            "refusing to delete storage object; a row still references it bucket=%s key=%s",
            bucket,
            key,
        )
        return False
    try:
        storage.delete(bucket, key)
    except Exception:
        logger.warning(
            "failed to delete unreferenced storage object bucket=%s key=%s",
            bucket,
            key,
            exc_info=True,
        )
        return False
    return True


def commit_or_discard_object(session: Session, storage, bucket: str, key: str | None) -> None:
    """Commit ``session``. On failure, roll back and delete ``key`` when nothing references it.

    The original exception propagates either way. A failed rollback leaves the object alone.
    """
    try:
        session.commit()
    except Exception:
        logger.warning(
            "storage commit failed; rolling back and discarding an unreferenced object bucket=%s key=%s",
            bucket,
            key,
            exc_info=True,
        )
        try:
            session.rollback()
        except Exception:
            logger.warning(
                "rollback failed after storage commit error; leaving object bucket=%s key=%s",
                bucket,
                key,
                exc_info=True,
            )
        else:
            discard_if_unreferenced(session, storage, bucket, key)
        raise


def _buckets(storage) -> tuple[tuple[str, str], ...]:
    return (
        (storage.bucket_raw, "raw"),
        (storage.bucket_exports, "exports"),
    )


def reconcile_orphan_objects(
    session: Session,
    storage,
    *,
    dry_run: bool = True,
    grace_seconds: int | None = None,
    now: datetime | None = None,
    workspace_id: int | None = None,
) -> OrphanReconcileResult:
    """Delete unreferenced objects strictly older than the grace period.

    ``dry_run`` lists them and deletes nothing. ``workspace_id`` limits the keys by prefix. A key
    referenced by any workspace is kept even when the prefix is this workspace. Keys whose prefix
    is not a workspace layout are kept. The reference load and the bucket list both happen before
    any delete. If either raises, nothing is deleted.

    Immediately before a delete the key is read again. A row that landed in that window is spared.
    A delete error is recorded and the sweep continues. A reference read that fails spares that key.
    """
    if workspace_id is not None and int(workspace_id) < 1:
        raise ValueError("workspace_id must be a positive integer")
    grace = orphan_grace_seconds() if grace_seconds is None else int(grace_seconds)
    if grace < 0:
        raise ValueError("grace_seconds must be >= 0")
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    else:
        moment = moment.astimezone(timezone.utc)
    cutoff = moment - timedelta(seconds=grace)
    referenced = referenced_storage_keys(session)
    candidates: list[tuple[str, str]] = []
    for bucket, _label in _buckets(storage):
        for item in storage.list_objects(bucket):
            key = item.get("key")
            if not isinstance(key, str) or not key:
                continue
            owner = object_workspace_id(key)
            if owner is None:
                continue
            if workspace_id is not None and owner != int(workspace_id):
                continue
            if key in referenced:
                continue
            modified = _as_utc(item.get("last_modified"))
            if modified is None or modified >= cutoff:
                continue
            candidates.append((bucket, key))
    candidates_t = tuple(sorted(set(candidates)))
    deleted: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []
    spared: list[tuple[str, str]] = []
    if not dry_run:
        for bucket, key in candidates_t:
            try:
                if storage_key_is_referenced(session, key):
                    spared.append((bucket, key))
                    continue
            except Exception:
                logger.warning(
                    "orphan sweep spared key; reference recheck failed bucket=%s key=%s",
                    bucket,
                    key,
                    exc_info=True,
                )
                failed.append((bucket, key))
                continue
            try:
                storage.delete(bucket, key)
            except Exception:
                logger.warning(
                    "orphan sweep failed to delete bucket=%s key=%s",
                    bucket,
                    key,
                    exc_info=True,
                )
                failed.append((bucket, key))
                continue
            deleted.append((bucket, key))
    result = OrphanReconcileResult(
        dry_run=dry_run,
        grace_seconds=grace,
        workspace_id=int(workspace_id) if workspace_id is not None else None,
        candidates=candidates_t,
        deleted=tuple(deleted),
        failed=tuple(failed),
        spared=tuple(spared),
    )
    logger.info(
        "orphan sweep dry_run=%s workspace_id=%s grace_seconds=%s candidates=%s deleted=%s failed=%s spared=%s",
        result.dry_run,
        result.workspace_id,
        result.grace_seconds,
        len(result.candidates),
        len(result.deleted),
        len(result.failed),
        len(result.spared),
    )
    return result


def sweep_orphans_best_effort(session: Session, storage=None) -> OrphanReconcileResult | None:
    """Worker entry. Deletes eligible orphans. Logs and returns None on any failure.

    A storage outage must not stop the claim loop. When ``storage`` is omitted, a client is built
    from the environment. Tests pass a fake and never open a network client.
    """
    try:
        if storage is None:
            from app.services.storage import StorageClient

            storage = StorageClient()
        return reconcile_orphan_objects(session, storage, dry_run=False)
    except Exception:
        logger.warning("orphan sweep failed; the worker will try again later", exc_info=True)
        return None


def _pending_ids(session: Session, kind: str, field: str) -> set[int]:
    pending: set[int] = set()
    rows = session.query(Job).filter(Job.kind == kind, Job.status.in_(_ACTIVE_JOB)).all()
    for job in rows:
        try:
            payload = json.loads(job.payload or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict) and field in payload:
            try:
                pending.add(int(payload[field]))
            except (TypeError, ValueError):
                continue
    return pending


def enqueue_missing_document_jobs(session: Session) -> int:
    """Queue ``index_document`` for an uploaded document that has no queued or running index job.

    The document row is already committed. Each new job commits on its own. One failure is logged
    and the next document is still attempted. Returns how many jobs were created.
    """
    pending = _pending_ids(session, "index_document", "document_id")
    added = 0
    docs = session.query(Document).filter(Document.status == "uploaded").all()
    for doc in docs:
        if doc.id in pending or not doc.storage_key:
            continue
        try:
            _job, created = enqueue_job(
                session,
                workspace_id=doc.workspace_id,
                kind="index_document",
                payload={"document_id": doc.id},
                idempotency_key=job_idempotency_key(
                    "index_document", doc.workspace_id, doc.id, doc.storage_key
                ),
                input_version=doc.storage_key,
            )
        except EnqueueConflictError:
            logger.info(
                "index re-enqueue lost the queued slot document_id=%s",
                doc.id,
            )
            session.rollback()
            continue
        except Exception:
            logger.warning(
                "index re-enqueue failed document_id=%s",
                doc.id,
                exc_info=True,
            )
            session.rollback()
            continue
        added += 1 if created else 0
    if added:
        print(f"Worker: enqueued {added} index_document job(s) for previously uploaded docs.")
    return added


def enqueue_missing_parse_jobs(session: Session) -> int:
    """Queue ``parse_questionnaire`` for an uploaded questionnaire with no queued or running parse.

    Same commit shape as the document hook. A questionnaire with no storage key is skipped: there
    is no object to parse. Returns how many jobs were created.
    """
    pending = _pending_ids(session, "parse_questionnaire", "questionnaire_id")
    added = 0
    rows = session.query(Questionnaire).filter(Questionnaire.status == "uploaded").all()
    for qnr in rows:
        if qnr.id in pending or not qnr.storage_key:
            continue
        try:
            _job, created = enqueue_job(
                session,
                workspace_id=qnr.workspace_id,
                kind="parse_questionnaire",
                payload={"questionnaire_id": qnr.id, "storage_key": qnr.storage_key},
                idempotency_key=job_idempotency_key(
                    "parse_questionnaire", qnr.workspace_id, qnr.id, qnr.storage_key
                ),
                input_version=qnr.storage_key,
            )
        except EnqueueConflictError:
            logger.info(
                "parse re-enqueue lost the queued slot questionnaire_id=%s",
                qnr.id,
            )
            session.rollback()
            continue
        except Exception:
            logger.warning(
                "parse re-enqueue failed questionnaire_id=%s",
                qnr.id,
                exc_info=True,
            )
            session.rollback()
            continue
        added += 1 if created else 0
    if added:
        print(f"Worker: enqueued {added} parse_questionnaire job(s) for previously uploaded files.")
    return added


def reconcile_missing_jobs(session: Session) -> dict[str, int]:
    """Detect domain rows committed without their job and enqueue the missing one."""
    return {
        "index_document": enqueue_missing_document_jobs(session),
        "parse_questionnaire": enqueue_missing_parse_jobs(session),
    }


def startup_reconcile(session: Session) -> dict[str, int]:
    """Worker startup: re-enqueue missing jobs, then sweep orphans. The sweep never raises."""
    counts = reconcile_missing_jobs(session)
    sweep_orphans_best_effort(session)
    return counts


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile stored objects with database rows. "
            "Dry-run is the default. Pass --execute to delete eligible orphans."
        )
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Delete eligible orphans. Without this flag the command only reports them.",
    )
    parser.add_argument(
        "--workspace-id",
        type=int,
        default=None,
        help="Only consider keys under this workspace's prefixes. References in every workspace still protect a key.",
    )
    parser.add_argument(
        "--enqueue-missing",
        action="store_true",
        help="Also enqueue index and parse jobs for uploaded rows that have none.",
    )
    return parser.parse_args(argv)


def execute_cli(argv: list[str] | None, *, session: Session, storage) -> int:
    """Run the CLI against an open session and a storage client. Does not close either.

    Exit 0 when every delete succeeded (or this was a dry-run). Exit 1 when a delete failed.
    Exit 2 when the arguments or the sweep itself failed. Nothing is deleted on exit 2.
    """
    args = parse_args(argv)
    try:
        if args.enqueue_missing:
            counts = reconcile_missing_jobs(session)
            print(
                "enqueue-missing "
                f"index_document={counts['index_document']} "
                f"parse_questionnaire={counts['parse_questionnaire']}"
            )
        result = reconcile_orphan_objects(
            session,
            storage,
            dry_run=not args.execute,
            workspace_id=args.workspace_id,
        )
    except Exception:
        logger.warning("storage reconcile failed", exc_info=True)
        print("storage reconcile failed; no further deletes were attempted")
        return 2
    print(
        f"{'dry-run' if result.dry_run else 'execute'} "
        f"candidates={len(result.candidates)} deleted={len(result.deleted)} "
        f"failed={len(result.failed)} spared={len(result.spared)}"
    )
    for bucket, key in result.candidates:
        print(f"candidate {bucket} {key}")
    return 1 if result.failed else 0


def main(argv: list[str] | None = None) -> int:
    """Operator entrypoint. Dry-run unless ``--execute`` is present. Not an HTTP route."""
    from app.core.database import SessionLocal
    from app.services.storage import StorageClient

    session = SessionLocal()
    try:
        storage = StorageClient()
        return execute_cli(argv, session=session, storage=storage)
    except Exception:
        logger.warning("storage reconcile could not start", exc_info=True)
        print("storage reconcile could not start")
        return 2
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
