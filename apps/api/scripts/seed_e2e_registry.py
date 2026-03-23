"""
Seed minimal deterministic records for registry lifecycle E2E tests.

Creates:
- DOC-E2E001 (active), DOC-E2E002 (archived), DOC-E2E003 (active)
- TR-E2E001 (active), TR-E2E002 (archived)
- QNR-E2E001 (active), QNR-E2E002 (archived)

Run from apps/api: python -m scripts.seed_e2e_registry
Requires: demo user/workspace from seed_demo_workspace; Postgres; MinIO for document storage.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from dotenv import load_dotenv

load_dotenv(API_ROOT / ".env")

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Document, Questionnaire, TrustRequest
from app.services.file_service import make_key
from app.services.storage import StorageClient

WORKSPACE_ID = 1
E2E_NOW = datetime.now(timezone.utc)


def ensure_e2e_documents(db: Session, storage: StorageClient) -> None:
    """Create/upsert DOC-E2E001, DOC-E2E003 (active) and DOC-E2E002 (archived).

    Two active E2E rows are required so bulk-select Playwright tests never skip.
    """
    for display_id, archived in [("DOC-E2E001", False), ("DOC-E2E002", True), ("DOC-E2E003", False)]:
        existing = db.query(Document).filter(Document.display_id == display_id).first()
        if existing:
            existing.deleted_at = E2E_NOW if archived else None
            existing.frameworks_json = json.dumps(["SOC 2"])
            existing.subject_areas_json = json.dumps(["Security"])
            existing.status = "uploaded"
            db.commit()
            continue
        key = make_key(WORKSPACE_ID, "raw", f"{display_id.lower()}.txt")
        storage.upload(
            storage.bucket_raw,
            key,
            f"E2E placeholder for {display_id}".encode(),
            content_type="text/plain",
        )
        doc = Document(
            workspace_id=WORKSPACE_ID,
            storage_key=key,
            filename=f"{display_id.lower()}.txt",
            content_type="text/plain",
            display_id=display_id,
            frameworks_json=json.dumps(["SOC 2"]),
            subject_areas_json=json.dumps(["Security"]),
            status="uploaded",
            created_at=E2E_NOW,
            deleted_at=E2E_NOW if archived else None,
        )
        db.add(doc)
    db.commit()
    print("Seeded documents: DOC-E2E001, DOC-E2E003 (active), DOC-E2E002 (archived)")


def ensure_e2e_trust_requests(db: Session) -> None:
    """Create/upsert TR-E2E001 (active) and TR-E2E002 (archived)."""
    for display_id, archived in [("TR-E2E001", False), ("TR-E2E002", True)]:
        existing = db.query(TrustRequest).filter(TrustRequest.display_id == display_id).first()
        if existing:
            existing.deleted_at = E2E_NOW if archived else None
            existing.frameworks_json = json.dumps(["SOC 2"])
            existing.subject_areas_json = json.dumps(["Security"])
            existing.status = "new"
            db.commit()
            continue
        tr = TrustRequest(
            workspace_id=WORKSPACE_ID,
            requester_email=f"{display_id.lower()}@e2e.test",
            requester_name=f"E2E {display_id}",
            subject=f"E2E trust request {display_id}",
            message=f"Placeholder message for {display_id}",
            display_id=display_id,
            frameworks_json=json.dumps(["SOC 2"]),
            subject_areas_json=json.dumps(["Security"]),
            status="new",
            created_at=E2E_NOW,
            deleted_at=E2E_NOW if archived else None,
        )
        db.add(tr)
    db.commit()
    print("Seeded trust requests: TR-E2E001 (active), TR-E2E002 (archived)")


def ensure_e2e_questionnaires(db: Session, storage: StorageClient) -> None:
    """Create/upsert QNR-E2E001 (active) and QNR-E2E002 (archived)."""
    for display_id, archived in [("QNR-E2E001", False), ("QNR-E2E002", True)]:
        existing = db.query(Questionnaire).filter(Questionnaire.display_id == display_id).first()
        if existing:
            existing.deleted_at = E2E_NOW if archived else None
            existing.frameworks_json = json.dumps(["SOC 2"])
            existing.subject_areas_json = json.dumps(["Security"])
            existing.status = "parsed"
            db.commit()
            continue
        key = make_key(WORKSPACE_ID, "raw", f"{display_id.lower()}.xlsx")
        storage.upload(
            storage.bucket_raw,
            key,
            b"PK\x03\x04",  # minimal xlsx header
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        qnr = Questionnaire(
            workspace_id=WORKSPACE_ID,
            storage_key=key,
            filename=f"{display_id.lower()}.xlsx",
            display_id=display_id,
            frameworks_json=json.dumps(["SOC 2"]),
            subject_areas_json=json.dumps(["Security"]),
            status="parsed",
            created_at=E2E_NOW,
            deleted_at=E2E_NOW if archived else None,
        )
        db.add(qnr)
    db.commit()
    print("Seeded questionnaires: QNR-E2E001 (active), QNR-E2E002 (archived)")


def main() -> None:
    db = SessionLocal()
    try:
        storage = StorageClient()
        storage.ensure_buckets()
        ensure_e2e_documents(db, storage)
        ensure_e2e_trust_requests(db)
        ensure_e2e_questionnaires(db, storage)
        print("E2E registry seed complete.")
    except Exception as e:
        print("E2E seed failed:", e)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
