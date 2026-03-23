import json
import uuid
from datetime import datetime, timezone

import sqlalchemy
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.models import Document, Questionnaire, TrustRequest
from app.services.registry_metadata import FRAMEWORK_LABELS, SUBJECT_AREA_LABELS, normalize_labels


def test_schema_has_registry_columns(client: TestClient) -> None:  # noqa: ARG001 - client triggers DB setup
    """Assert documents, trust_requests, questionnaires have registry metadata columns."""
    import os
    from sqlalchemy import text
    engine = sqlalchemy.create_engine(os.environ["DATABASE_URL"])
    required = [
        ("documents", "display_id"),
        ("documents", "frameworks_json"),
        ("documents", "deleted_at"),
        ("trust_requests", "display_id"),
        ("trust_requests", "frameworks_json"),
        ("trust_requests", "deleted_at"),
        ("questionnaires", "display_id"),
        ("questionnaires", "frameworks_json"),
        ("questionnaires", "deleted_at"),
    ]
    with engine.connect() as conn:
        for table, col in required:
            r = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"
                ),
                {"t": table, "c": col},
            )
            assert r.scalar(), f"Expected column {table}.{col}"
    engine.dispose()


def _login(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert r.status_code == 200


def test_documents_preview_delete_restore_and_metadata(client: TestClient) -> None:
    _login(client)
    uid = uuid.uuid4().hex[:6]
    session = SessionLocal()
    try:
        d = Document(
            workspace_id=1,
            filename="lifecycle_doc.pdf",
            storage_key=f"raw/1/test_{uid}.pdf",
            status="indexed",
            display_id=f"DOC-T{uid}",
            frameworks_json=json.dumps(["SOC 2"]),
            subject_areas_json=json.dumps(["Access Control"]),
            created_at=datetime.now(timezone.utc),
        )
        session.add(d)
        session.commit()
        session.refresh(d)
        doc_id = d.id
    finally:
        session.close()

    # Re-auth after direct DB use so cookie/session cannot drift vs. app DB session (deterministic).
    _login(client)
    r = client.get(f"/api/documents/{doc_id}/delete-preview?workspace_id=1")
    assert r.status_code == 200
    data = r.json()
    assert data["display_id"]
    assert "unmodeled_warning" in data
    deps = data.get("dependencies", {})
    assert any(v == "unavailable" for v in deps.values()), "expect some unavailable deps"

    r = client.delete(f"/api/documents/{doc_id}?workspace_id=1")
    assert r.status_code == 200

    r = client.get("/api/documents/?workspace_id=1")
    assert r.status_code == 200
    assert all(row["id"] != doc_id for row in r.json())

    r = client.get("/api/documents/?workspace_id=1&archived=only")
    assert r.status_code == 200
    assert any(row["id"] == doc_id for row in r.json())

    _login(client)
    r = client.patch(
        f"/api/documents/{doc_id}/metadata?workspace_id=1",
        json={"frameworks": ["HIPAA"], "subject_areas": ["Logging"]},
    )
    assert r.status_code == 200

    _login(client)
    r = client.post(f"/api/documents/{doc_id}/restore?workspace_id=1")
    assert r.status_code == 200

    session = SessionLocal()
    try:
        d = session.query(Document).filter(Document.id == doc_id).first()
        assert d is not None
        assert d.status == "indexed"  # business status preserved
        assert d.deleted_at is None
    finally:
        session.close()


def test_questionnaires_lifecycle_endpoints(client: TestClient) -> None:
    _login(client)
    uid = uuid.uuid4().hex[:6]
    session = SessionLocal()
    try:
        q = Questionnaire(
            workspace_id=1,
            filename="lifecycle_qnr.xlsx",
            status="draft",
            display_id=f"QNR-T{uid}",
            frameworks_json=json.dumps(["SOC 2"]),
            subject_areas_json=json.dumps(["Access Control"]),
        )
        session.add(q)
        session.commit()
        session.refresh(q)
        qid = q.id
    finally:
        session.close()

    assert client.get(f"/api/questionnaires/{qid}/delete-preview?workspace_id=1").status_code == 200
    assert client.delete(f"/api/questionnaires/{qid}?workspace_id=1").status_code == 200
    _login(client)
    assert client.patch(
        f"/api/questionnaires/{qid}/metadata?workspace_id=1",
        json={"frameworks": ["NIST"], "subject_areas": ["Risk Management"]},
    ).status_code == 200
    _login(client)
    assert client.post(f"/api/questionnaires/{qid}/restore?workspace_id=1").status_code == 200

    session = SessionLocal()
    try:
        q = session.query(Questionnaire).filter(Questionnaire.id == qid).first()
        assert q is not None
        assert q.status == "draft"
        assert q.deleted_at is None
    finally:
        session.close()


def test_trust_requests_lifecycle_endpoints(client: TestClient) -> None:
    _login(client)
    uid = uuid.uuid4().hex[:6]
    session = SessionLocal()
    try:
        tr = TrustRequest(
            workspace_id=1,
            requester_email=f"req-{uid}@example.com",
            requester_name="Requester",
            subject="Lifecycle",
            message="Please review",
            status="in_progress",
            display_id=f"TR-T{uid}",
            frameworks_json=json.dumps(["SOC 2"]),
            subject_areas_json=json.dumps(["Vendor Management"]),
        )
        session.add(tr)
        session.commit()
        session.refresh(tr)
        tid = tr.id
    finally:
        session.close()

    _login(client)
    assert client.get(f"/api/trust-requests/{tid}/delete-preview?workspace_id=1").status_code == 200
    _login(client)
    assert client.delete(f"/api/trust-requests/{tid}?workspace_id=1").status_code == 200
    _login(client)
    assert client.patch(
        f"/api/trust-requests/{tid}/metadata?workspace_id=1",
        json={"frameworks": ["GDPR"], "subject_areas": ["Vendor Management"]},
    ).status_code == 200
    _login(client)
    assert client.post(f"/api/trust-requests/{tid}/restore?workspace_id=1").status_code == 200

    session = SessionLocal()
    try:
        tr = session.query(TrustRequest).filter(TrustRequest.id == tid).first()
        assert tr is not None
        assert tr.status == "in_progress"
        assert tr.deleted_at is None
    finally:
        session.close()


def test_documents_bulk_delete(client: TestClient) -> None:
    """Bulk-delete soft-deletes multiple documents."""
    _login(client)
    uid = uuid.uuid4().hex[:6]
    session = SessionLocal()
    ids = []
    try:
        for i in range(3):
            d = Document(
                workspace_id=1,
                filename=f"bulk_{uid}_{i}.pdf",
                storage_key=f"raw/1/bulk_{uid}_{i}.pdf",
                status="indexed",
                display_id=f"DOC-B{uid}{i}",
                frameworks_json=json.dumps(["Other"]),
                subject_areas_json=json.dumps(["Other"]),
                created_at=datetime.now(timezone.utc),
            )
            session.add(d)
            session.commit()
            session.refresh(d)
            ids.append(d.id)
    finally:
        session.close()

    _login(client)
    r = client.post(
        "/api/documents/bulk-delete",
        params={"workspace_id": 1},
        json={"ids": ids},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["deleted"] == 3
    assert data["errors"] == []

    r = client.get("/api/documents/?workspace_id=1")
    assert r.status_code == 200
    assert all(row["id"] not in ids for row in r.json())

    r = client.get("/api/documents/?workspace_id=1&archived=only")
    assert r.status_code == 200
    assert all(any(row["id"] == i for row in r.json()) for i in ids)


def test_questionnaires_bulk_delete(client: TestClient) -> None:
    """P06: Bulk soft-delete questionnaires (active only)."""
    _login(client)
    uid = uuid.uuid4().hex[:6]
    session = SessionLocal()
    ids: list[int] = []
    try:
        for i in range(2):
            q = Questionnaire(
                workspace_id=1,
                filename=f"bulk_q_{uid}_{i}.xlsx",
                storage_key=f"raw/1/bulk_q_{uid}_{i}.xlsx",
                status="draft",
                display_id=f"QNR-B{uid}{i}",
                frameworks_json=json.dumps(["Other"]),
                subject_areas_json=json.dumps(["Other"]),
            )
            session.add(q)
            session.commit()
            session.refresh(q)
            ids.append(q.id)
    finally:
        session.close()

    _login(client)
    r = client.post("/api/questionnaires/bulk-delete", params={"workspace_id": 1}, json={"ids": ids})
    assert r.status_code == 200
    data = r.json()
    assert data["deleted"] == 2
    assert data["errors"] == []

    r = client.get("/api/questionnaires/?workspace_id=1")
    assert r.status_code == 200
    assert all(row["id"] not in ids for row in r.json())

    r = client.get("/api/questionnaires/?workspace_id=1&archived=only")
    assert r.status_code == 200
    assert all(any(row["id"] == i for row in r.json()) for i in ids)


def test_trust_requests_bulk_delete(client: TestClient) -> None:
    """P06: Bulk soft-delete trust requests (active only)."""
    _login(client)
    uid = uuid.uuid4().hex[:6]
    session = SessionLocal()
    ids: list[int] = []
    try:
        for i in range(2):
            tr = TrustRequest(
                workspace_id=1,
                requester_email=f"bulk-{uid}-{i}@example.com",
                requester_name="Bulk",
                subject="Bulk",
                message="Test",
                status="new",
                display_id=f"TR-B{uid}{i}",
                frameworks_json=json.dumps(["Other"]),
                subject_areas_json=json.dumps(["Other"]),
            )
            session.add(tr)
            session.commit()
            session.refresh(tr)
            ids.append(tr.id)
    finally:
        session.close()

    _login(client)
    r = client.post("/api/trust-requests/bulk-delete", params={"workspace_id": 1}, json={"ids": ids})
    assert r.status_code == 200
    data = r.json()
    assert data["deleted"] == 2
    assert data.get("errors") == []

    r = client.get("/api/trust-requests/")
    assert r.status_code == 200
    rows = r.json()
    assert all(row["id"] not in ids for row in rows)

    r = client.get("/api/trust-requests/?archived=only")
    assert r.status_code == 200
    rows_arch = r.json()
    assert all(any(row["id"] == i for row in rows_arch) for i in ids)


def test_normalize_labels_dedup_case_insensitive() -> None:
    """normalize_labels dedupes case-insensitively and trims."""
    out = normalize_labels(["soc 2", "SOC 2", "  HIPAA  "], allowed=FRAMEWORK_LABELS)
    assert out == ["SOC 2", "HIPAA"]
    out2 = normalize_labels(["Other", "other"], allowed=FRAMEWORK_LABELS)
    assert out2 == ["Other"]
    out3 = normalize_labels(["access control", "Access Control"], allowed=SUBJECT_AREA_LABELS)
    assert out3 == ["Access Control"]
