"""TC-15-016a document list contract.

SQLite control path with an injected reviewer. This does not qualify PostgreSQL
or the real session dependency. A caller that omits page, page_size, sort, and
order still receives the full JSON array.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.documents import router
from app.core.auth_deps import require_can_review
from app.core.config import get_settings
from app.core.database import Base, get_db
from app.models import Document, EvidenceItem, EvidenceVersion, Job, Workspace
from app.models.freshness_policy import FreshnessPolicy
from app.models.tag import DocumentTag, Tag
from app.services.storage import get_storage

_SECRET_KEY = "raw/1/secret-object"
_PRIVATE = "PRIVATE-KEY"


class _Storage:
    def __init__(self) -> None:
        self.bucket_raw = "raw"
        self.objects: dict[tuple[str, str], bytes] = {}
        self.fail = False

    def download_stream(self, bucket: str, key: str):
        if self.fail:
            raise FileNotFoundError(key)
        body = self.objects.get((bucket, key))
        if body is None:
            raise FileNotFoundError(key)
        return iter([body])


@pytest.fixture
def documents_api():
    """Local SQL only. The reviewer principal is injected."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    tables = [
        Workspace,
        Document,
        Job,
        EvidenceItem,
        EvidenceVersion,
        FreshnessPolicy,
        Tag,
        DocumentTag,
    ]
    Base.metadata.create_all(engine, tables=[model.__table__ for model in tables])
    storage = _Storage()
    with Session(engine) as db:
        db.add_all(
            [
                Workspace(id=1, name="Local", slug="local"),
                Workspace(id=2, name="Other", slug="other"),
            ]
        )
        db.commit()
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[require_can_review] = lambda: {
            "workspace_id": 1,
            "role": "reviewer",
            "user_id": 1,
            "email": "reviewer@example.com",
        }
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_storage] = lambda: storage
        with TestClient(app) as client:
            yield client, db, storage
    engine.dispose()


def _add_document(db: Session, **values) -> Document:
    now = datetime.now(timezone.utc)
    fields = dict(
        workspace_id=1,
        storage_key=_SECRET_KEY,
        filename="Policy.pdf",
        content_type="text/html",
        status="uploaded",
        created_at=now,
    )
    fields.update(values)
    row = Document(**fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _index_job(
    db: Session,
    document_id: int,
    status: str,
    *,
    workspace_id: int = 1,
    payload_document_id: object | None = None,
) -> int:
    body = {
        "document_id": document_id if payload_document_id is None else payload_document_id,
        "storage_key": _PRIVATE,
    }
    row = Job(
        workspace_id=workspace_id,
        kind="index_document",
        status=status,
        payload=json.dumps(body),
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


@pytest.mark.unit
def test_tc_15_016a_paged_list_sorts_reports_metadata_and_upload_limit(documents_api, monkeypatch):
    client, db, _storage = documents_api
    now = datetime.now(timezone.utc)
    alpha = _add_document(
        db,
        filename="Alpha.pdf",
        status="indexed",
        created_at=now - timedelta(days=3),
    )
    beta = _add_document(
        db,
        filename="Beta.pdf",
        status="uploaded",
        created_at=now - timedelta(days=1),
    )
    charlie = _add_document(
        db,
        filename="Charlie.pdf",
        status="failed",
        created_at=now - timedelta(days=2),
    )
    old = _add_document(
        db,
        filename="Old.pdf",
        status="indexed",
        created_at=now - timedelta(days=200),
    )
    archived = _add_document(
        db,
        filename="Archived.pdf",
        status="indexed",
        created_at=now - timedelta(days=4),
        deleted_at=now,
        storage_key="",
    )
    _add_document(db, workspace_id=2, filename="Foreign.pdf", created_at=now)
    evidence = EvidenceItem(
        workspace_id=1,
        document_id=beta.id,
        source_type="document",
        title="Beta evidence",
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    db.add_all(
        [
            EvidenceVersion(evidence_id=evidence.id, version_number=1),
            EvidenceVersion(evidence_id=evidence.id, version_number=4),
        ]
    )
    foreign_evidence = EvidenceItem(
        workspace_id=2,
        document_id=beta.id,
        source_type="document",
        title="Other workspace",
    )
    db.add(foreign_evidence)
    db.commit()
    db.refresh(foreign_evidence)
    db.add(EvidenceVersion(evidence_id=foreign_evidence.id, version_number=99))
    db.commit()
    _index_job(db, beta.id, "completed")
    failed_job = _index_job(db, beta.id, "failed")
    _index_job(db, alpha.id, "failed", payload_document_id="not-an-int")
    _index_job(db, beta.id, "queued", workspace_id=2)

    first = client.get(
        "/api/documents",
        params={
            "workspace_id": 1,
            "page": 1,
            "page_size": 2,
            "sort": "filename",
            "order": "asc",
        },
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert isinstance(body, dict)
    assert [row["filename"] for row in body["items"]] == ["Alpha.pdf", "Beta.pdf"]
    assert body["total"] == 4
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["sort"] == "filename"
    assert body["order"] == "asc"
    assert body["max_upload_bytes"] == get_settings().max_upload_bytes
    assert _PRIVATE not in first.text
    assert _SECRET_KEY not in first.text
    alpha_row = body["items"][0]
    beta_row = body["items"][1]
    assert alpha_row["id"] == alpha.id
    assert alpha_row["source_eligibility"] == "eligible"
    assert alpha_row["freshness"] == "fresh"
    assert alpha_row["version"] is None
    assert alpha_row["index_job_id"] is None
    assert alpha_row["index_job_status"] is None
    assert alpha_row["source_preview_url"] == (f"/api/documents/{alpha.id}/content?workspace_id=1")
    assert "storage_key" not in alpha_row
    assert beta_row["version"] == "4"
    assert beta_row["index_job_id"] == failed_job
    assert beta_row["index_job_status"] == "failed"
    assert beta_row["source_eligibility"] == "eligible"

    second = client.get(
        "/api/documents",
        params={
            "workspace_id": 1,
            "page": 2,
            "page_size": 2,
            "sort": "filename",
            "order": "asc",
        },
    )
    assert [row["filename"] for row in second.json()["items"]] == ["Charlie.pdf", "Old.pdf"]
    assert second.json()["total"] == 4
    assert second.json()["items"][0]["id"] == charlie.id
    assert second.json()["items"][1]["freshness"] == "stale"
    assert second.json()["items"][1]["id"] == old.id

    newest = client.get(
        "/api/documents",
        params={
            "workspace_id": 1,
            "page": 1,
            "page_size": 4,
            "sort": "created_at",
            "order": "desc",
        },
    )
    assert [row["filename"] for row in newest.json()["items"]] == [
        "Beta.pdf",
        "Charlie.pdf",
        "Alpha.pdf",
        "Old.pdf",
    ]
    found = client.get(
        "/api/documents",
        params={"workspace_id": 1, "page": 1, "search": "Beta", "sort": "filename", "order": "asc"},
    )
    assert found.json()["total"] == 1
    assert found.json()["items"][0]["id"] == beta.id

    archived_page = client.get(
        "/api/documents",
        params={"workspace_id": 1, "page": 1, "archived": "only"},
    )
    assert archived_page.json()["total"] == 1
    archived_row = archived_page.json()["items"][0]
    assert archived_row["id"] == archived.id
    assert archived_row["source_eligibility"] == "ineligible"
    assert archived_row["source_preview_url"] is None

    assert client.get("/api/documents", params={"workspace_id": 2, "page": 1}).status_code == 403
    assert (
        client.get(
            "/api/documents", params={"workspace_id": 1, "page": 1, "sort": "nope"}
        ).status_code
        == 400
    )
    assert (
        client.get(
            "/api/documents", params={"workspace_id": 1, "page": 1, "order": "sideways"}
        ).status_code
        == 400
    )
    assert (
        client.get(
            "/api/documents", params={"workspace_id": 1, "page": 0, "page_size": 25}
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/documents", params={"workspace_id": 1, "page": 1, "page_size": 101}
        ).status_code
        == 422
    )
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 4096)
    limited = client.get("/api/documents", params={"workspace_id": 1, "page": 1, "page_size": 1})
    assert limited.json()["max_upload_bytes"] == 4096


@pytest.mark.unit
def test_tc_15_016a_legacy_list_returns_every_row_with_the_same_metadata(documents_api):
    client, db, _storage = documents_api
    now = datetime.now(timezone.utc)
    older = _add_document(db, filename="Older.pdf", created_at=now - timedelta(days=2))
    newer = _add_document(db, filename="Newer.pdf", created_at=now - timedelta(days=1))
    for index in range(3):
        _add_document(
            db, filename=f"Extra-{index}.pdf", created_at=now - timedelta(days=10 + index)
        )
    response = client.get("/api/documents", params={"workspace_id": 1})
    assert response.status_code == 200, response.text
    rows = response.json()
    assert isinstance(rows, list)
    assert len(rows) == 5
    assert rows[0]["id"] == newer.id
    assert rows[1]["id"] == older.id
    assert rows[0]["source_eligibility"] == "eligible"
    assert rows[0]["freshness"] == "fresh"
    assert "version" in rows[0]
    assert "index_job_id" in rows[0]
    assert "index_job_status" in rows[0]
    assert rows[0]["source_preview_url"] == (f"/api/documents/{newer.id}/content?workspace_id=1")
    assert all("max_upload_bytes" not in row for row in rows)
    assert _SECRET_KEY not in response.text


@pytest.mark.unit
def test_tc_15_016a_content_preview_stays_in_workspace_and_hides_the_storage_key(documents_api):
    client, db, storage = documents_api
    storage.objects[("raw", _SECRET_KEY)] = b"%PDF-1.4 synthetic"
    row = _add_document(
        db,
        filename="evil\r\nX-Injected: 1.pdf",
        content_type="text/html",
        storage_key=_SECRET_KEY,
    )
    foreign = _add_document(db, workspace_id=2, filename="Foreign.pdf", storage_key=_SECRET_KEY)
    ok = client.get(f"/api/documents/{row.id}/content", params={"workspace_id": 1})
    assert ok.status_code == 200, ok.text
    assert ok.content == b"%PDF-1.4 synthetic"
    assert ok.headers["content-type"].startswith("application/pdf")
    disposition = ok.headers["content-disposition"]
    assert disposition.startswith("inline;")
    assert "\r" not in disposition
    assert "\n" not in disposition
    assert "x-injected" not in {name.lower() for name in ok.headers}
    assert _SECRET_KEY not in ok.text
    assert _SECRET_KEY not in disposition
    assert ok.headers["x-content-type-options"] == "nosniff"
    denied = client.get(f"/api/documents/{row.id}/content", params={"workspace_id": 2})
    assert denied.status_code == 403
    missing = client.get(f"/api/documents/{foreign.id}/content", params={"workspace_id": 1})
    assert missing.status_code == 404
    assert _SECRET_KEY not in missing.text
    storage.fail = True
    unavailable = client.get(f"/api/documents/{row.id}/content", params={"workspace_id": 1})
    assert unavailable.status_code == 404
    assert unavailable.json()["detail"] == "Document file not found"
    assert _SECRET_KEY not in unavailable.text


@pytest.mark.unit
def test_tc_15_016a_freshness_follows_the_document_policy(documents_api):
    client, db, _storage = documents_api
    now = datetime.now(timezone.utc)
    db.add(
        FreshnessPolicy(
            workspace_id=1,
            source_type="document",
            max_age_days=10,
            warn_before_days=3,
        )
    )
    db.commit()
    warning = _add_document(db, filename="Warning.pdf", created_at=now - timedelta(days=8))
    fresh = _add_document(db, filename="Fresh.pdf", created_at=now - timedelta(days=1))
    stale = _add_document(db, filename="Stale.pdf", created_at=now - timedelta(days=11))
    response = client.get(
        "/api/documents",
        params={"workspace_id": 1, "page": 1, "page_size": 10, "sort": "filename", "order": "asc"},
    )
    assert response.status_code == 200, response.text
    by_name = {row["filename"]: row["freshness"] for row in response.json()["items"]}
    assert by_name[fresh.filename] == "fresh"
    assert by_name[warning.filename] == "warning"
    assert by_name[stale.filename] == "stale"
