"""
Ensure test data for AI verification: one trust request, and index the seed document so questionnaire AI has evidence.
Run from repo root: python -m apps.api.scripts.ensure_ai_test_data
Or from apps/api: python -m scripts.ensure_ai_test_data (with PYTHONPATH or sys.path)
"""
import json
import os
import sys
from pathlib import Path

# Allow running from repo root or apps/api
api_root = Path(__file__).resolve().parent.parent
repo_root = api_root.parent.parent
if str(api_root) not in sys.path:
    sys.path.insert(0, str(api_root))
os.chdir(api_root)

from dotenv import load_dotenv
load_dotenv(api_root / ".env")
load_dotenv(repo_root / ".env")

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models import Document, Job, JobStatus, TrustRequest

def main():
    db = SessionLocal()
    try:
        # 1) One trust request for workspace 1 (demo user)
        existing = db.query(TrustRequest).filter(TrustRequest.workspace_id == 1).first()
        if not existing:
            req = TrustRequest(
                workspace_id=1,
                requester_email="tester@example.com",
                subject="SOC 2 and security documentation",
                message="Could you please share your SOC 2 Type II report and a brief summary of your penetration testing process? We need this for our vendor risk assessment.",
                status="new",
            )
            db.add(req)
            db.commit()
            db.refresh(req)
            print(f"Created trust request id={req.id}")
        else:
            print(f"Trust request already exists id={existing.id}")

        # 2) Enqueue index_document for any uploaded document in workspace 1 so generate_answers has evidence
        for doc in db.query(Document).filter(Document.workspace_id == 1, Document.status == "uploaded").all():
            job = Job(
                workspace_id=1,
                kind="index_document",
                status=JobStatus.QUEUED.value,
                payload=json.dumps({"document_id": doc.id}),
            )
            db.add(job)
            db.commit()
            print(f"Enqueued index_document job for document id={doc.id} ({doc.filename})")
        db.commit()
    finally:
        db.close()

if __name__ == "__main__":
    main()
