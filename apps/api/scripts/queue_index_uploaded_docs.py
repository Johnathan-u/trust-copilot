"""
Re-queue index_document jobs for all documents stuck in status="uploaded".
Use when you have many uploaded docs that never got indexed (e.g. worker wasn't running, or jobs failed).

Run from repo root:
  python -m apps.api.scripts.queue_index_uploaded_docs
Or from apps/api (with PYTHONPATH=. or from apps/api):
  python scripts/queue_index_uploaded_docs.py

Optional: workspace_id as first arg to only process one workspace:
  python scripts/queue_index_uploaded_docs.py 1
"""
import json
import os
import sys
from pathlib import Path

api_root = Path(__file__).resolve().parent.parent
repo_root = api_root.parent.parent
if str(api_root) not in sys.path:
    sys.path.insert(0, str(api_root))
os.chdir(api_root)

from dotenv import load_dotenv
load_dotenv(api_root / ".env")
load_dotenv(repo_root / ".env")

from app.core.database import SessionLocal
from app.models import Document, Job, JobStatus


def main() -> None:
    workspace_id_filter = int(sys.argv[1]) if len(sys.argv) > 1 else None

    db = SessionLocal()
    try:
        query = db.query(Document).filter(Document.status == "uploaded")
        if workspace_id_filter is not None:
            query = query.filter(Document.workspace_id == workspace_id_filter)
        uploaded = query.all()
        if not uploaded:
            print("No documents with status='uploaded' found.")
            return

        # Document IDs that already have a queued or running index_document job
        pending = set()
        for job in db.query(Job).filter(
            Job.kind == "index_document",
            Job.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value]),
        ).all():
            try:
                payload = json.loads(job.payload or "{}")
                if "document_id" in payload:
                    pending.add(payload["document_id"])
            except Exception:
                pass

        enqueued = 0
        for doc in uploaded:
            if doc.id in pending:
                continue
            job = Job(
                workspace_id=doc.workspace_id,
                kind="index_document",
                status=JobStatus.QUEUED.value,
                payload=json.dumps({"document_id": doc.id}),
            )
            db.add(job)
            db.commit()
            enqueued += 1
            print(f"Enqueued index_document for doc id={doc.id} workspace_id={doc.workspace_id} ({doc.filename})")

        print(f"\nDone. Enqueued {enqueued} new index_document job(s) for {len(uploaded)} uploaded doc(s).")
        if pending:
            print(f"({len(uploaded) - enqueued} doc(s) already had a pending index job and were skipped.)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
