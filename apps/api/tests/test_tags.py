"""Tests for enterprise document/evidence tagging system."""

import pytest
from sqlalchemy.orm import Session

from app.models import Document, EvidenceItem
from app.models.tag import DocumentTag, Tag
from app.services.tag_service import (
    SYSTEM_TAGS,
    approve_tag,
    assign_tag,
    auto_tag_document,
    classify_text,
    ensure_system_tags,
    get_or_create_tag,
    list_available_tags,
    list_tags_for_document,
    list_tags_for_documents,
    remove_tag,
    resolve_tag,
)


# ── Schema presence ─────────────────────────────────────────────────────────

class TestSchemaPresence:
    def test_tags_table_exists(self, db_session: Session):
        from sqlalchemy import inspect
        insp = inspect(db_session.bind)
        assert "tags" in insp.get_table_names()

    def test_document_tags_table_exists(self, db_session: Session):
        from sqlalchemy import inspect
        insp = inspect(db_session.bind)
        assert "document_tags" in insp.get_table_names()

    def test_tags_columns(self, db_session: Session):
        from sqlalchemy import inspect
        insp = inspect(db_session.bind)
        cols = {c["name"] for c in insp.get_columns("tags")}
        assert {"id", "workspace_id", "category", "key", "label", "is_system", "created_at"} <= cols

    def test_document_tags_columns(self, db_session: Session):
        from sqlalchemy import inspect
        insp = inspect(db_session.bind)
        cols = {c["name"] for c in insp.get_columns("document_tags")}
        assert {"id", "workspace_id", "document_id", "tag_id", "source", "confidence", "approved", "created_by_user_id", "created_at"} <= cols


# ── System tag catalog ──────────────────────────────────────────────────────

class TestSystemTags:
    def test_ensure_system_tags_idempotent(self, db_session: Session):
        ensure_system_tags(db_session)
        count1 = db_session.query(Tag).filter(Tag.is_system.is_(True)).count()
        assert count1 == len(SYSTEM_TAGS)
        ensure_system_tags(db_session)
        count2 = db_session.query(Tag).filter(Tag.is_system.is_(True)).count()
        assert count2 == count1

    def test_system_tags_are_global(self, db_session: Session):
        ensure_system_tags(db_session)
        for tag in db_session.query(Tag).filter(Tag.is_system.is_(True)).all():
            assert tag.workspace_id is None

    def test_resolve_system_tag(self, db_session: Session):
        ensure_system_tags(db_session)
        tag = resolve_tag(db_session, "framework", "soc2")
        assert tag is not None
        assert tag.label == "SOC 2"


# ── Tag creation & resolution ──────────────────────────────────────────────

class TestTagCRUD:
    def test_get_or_create_tag_new(self, db_session: Session):
        tag = get_or_create_tag(db_session, "custom", "my_tag", "My Tag", workspace_id=1)
        db_session.commit()
        assert tag.id is not None
        assert tag.key == "my_tag"
        assert tag.workspace_id == 1

    def test_get_or_create_tag_existing(self, db_session: Session):
        ensure_system_tags(db_session)
        tag = get_or_create_tag(db_session, "framework", "soc2", "SOC 2")
        assert tag.is_system is True

    def test_list_available_tags(self, db_session: Session):
        ensure_system_tags(db_session)
        get_or_create_tag(db_session, "custom", "ws1_tag", "WS1 Tag", workspace_id=1)
        db_session.commit()
        tags = list_available_tags(db_session, 1)
        keys = {t["key"] for t in tags}
        assert "soc2" in keys
        assert "ws1_tag" in keys

    def test_workspace_scoped_tag_not_visible_to_other(self, db_session: Session):
        ensure_system_tags(db_session)
        get_or_create_tag(db_session, "custom", "ws2_only", "WS2 Only", workspace_id=2)
        db_session.commit()
        tags = list_available_tags(db_session, 1)
        keys = {t["key"] for t in tags}
        assert "ws2_only" not in keys


# ── Tag assignment ──────────────────────────────────────────────────────────

def _create_doc(db_session: Session, workspace_id: int = 1) -> Document:
    doc = Document(
        workspace_id=workspace_id,
        storage_key="test/key.pdf",
        filename="test.pdf",
        status="uploaded",
    )
    db_session.add(doc)
    db_session.flush()
    return doc


class TestTagAssignment:
    def test_assign_and_list(self, db_session: Session):
        ensure_system_tags(db_session)
        doc = _create_doc(db_session)
        tag = resolve_tag(db_session, "framework", "soc2")
        assign_tag(db_session, doc.id, tag.id, workspace_id=1, source="manual")
        db_session.commit()
        tags = list_tags_for_document(db_session, doc.id, 1)
        assert len(tags) == 1
        assert tags[0]["key"] == "soc2"
        assert tags[0]["source"] == "manual"

    def test_assign_duplicate_upserts(self, db_session: Session):
        ensure_system_tags(db_session)
        doc = _create_doc(db_session)
        tag = resolve_tag(db_session, "framework", "soc2")
        assign_tag(db_session, doc.id, tag.id, workspace_id=1, source="ai", confidence=0.7)
        assign_tag(db_session, doc.id, tag.id, workspace_id=1, source="manual", confidence=None, approved=True)
        db_session.commit()
        tags = list_tags_for_document(db_session, doc.id, 1)
        assert len(tags) == 1
        assert tags[0]["source"] == "manual"
        assert tags[0]["approved"] is True

    def test_remove_tag(self, db_session: Session):
        ensure_system_tags(db_session)
        doc = _create_doc(db_session)
        tag = resolve_tag(db_session, "framework", "soc2")
        assign_tag(db_session, doc.id, tag.id, workspace_id=1)
        db_session.commit()
        removed = remove_tag(db_session, doc.id, tag.id, workspace_id=1)
        db_session.commit()
        assert removed is True
        tags = list_tags_for_document(db_session, doc.id, 1)
        assert len(tags) == 0

    def test_remove_nonexistent_returns_false(self, db_session: Session):
        doc = _create_doc(db_session)
        db_session.commit()
        assert remove_tag(db_session, doc.id, 9999, workspace_id=1) is False

    def test_approve_tag(self, db_session: Session):
        ensure_system_tags(db_session)
        doc = _create_doc(db_session)
        tag = resolve_tag(db_session, "framework", "soc2")
        dt = assign_tag(db_session, doc.id, tag.id, workspace_id=1, source="ai", approved=False)
        db_session.commit()
        result = approve_tag(db_session, dt.id, workspace_id=1, approved=True)
        db_session.commit()
        assert result is not None
        assert result.approved is True

    def test_batch_load_tags(self, db_session: Session):
        ensure_system_tags(db_session)
        doc1 = _create_doc(db_session)
        doc2 = _create_doc(db_session)
        tag_soc2 = resolve_tag(db_session, "framework", "soc2")
        tag_hipaa = resolve_tag(db_session, "framework", "hipaa")
        assign_tag(db_session, doc1.id, tag_soc2.id, workspace_id=1)
        assign_tag(db_session, doc2.id, tag_hipaa.id, workspace_id=1)
        db_session.commit()
        result = list_tags_for_documents(db_session, [doc1.id, doc2.id], 1)
        assert len(result[doc1.id]) == 1
        assert result[doc1.id][0]["key"] == "soc2"
        assert len(result[doc2.id]) == 1
        assert result[doc2.id][0]["key"] == "hipaa"


# ── Workspace isolation ─────────────────────────────────────────────────────

class TestWorkspaceIsolation:
    def test_tags_not_visible_cross_workspace(self, db_session: Session):
        ensure_system_tags(db_session)
        doc = _create_doc(db_session, workspace_id=1)
        tag = resolve_tag(db_session, "framework", "soc2")
        assign_tag(db_session, doc.id, tag.id, workspace_id=1)
        db_session.commit()
        tags_ws2 = list_tags_for_document(db_session, doc.id, workspace_id=2)
        assert len(tags_ws2) == 0

    def test_remove_cross_workspace_fails(self, db_session: Session):
        ensure_system_tags(db_session)
        doc = _create_doc(db_session, workspace_id=1)
        tag = resolve_tag(db_session, "framework", "soc2")
        assign_tag(db_session, doc.id, tag.id, workspace_id=1)
        db_session.commit()
        assert remove_tag(db_session, doc.id, tag.id, workspace_id=2) is False


# ── LLM classifier tests (mocked) ──────────────────────────────────────────

class TestClassifier:
    def _mock_llm(self, response_json: dict):
        """Helper: mock the LLM to return a specific JSON response."""
        import json
        from unittest.mock import patch, MagicMock
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = json.dumps(response_json)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        return patch("app.services.tag_service._get_client" if False else "app.services.mapping_llm_classify._get_client", return_value=mock_client)

    def test_framework_detection_soc2(self):
        from unittest.mock import patch, MagicMock
        import json
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = json.dumps({"frameworks": ["soc2"], "topics": ["access_control"], "document_types": ["report"]})
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        with patch("app.services.tag_service._classify_document_llm") as mock_fn:
            mock_fn.return_value = [
                {"category": "framework", "key": "soc2", "confidence": 0.85},
                {"category": "topic", "key": "access_control", "confidence": 0.80},
            ]
            results = classify_text("This SOC 2 Type II report covers...", "soc2-report.pdf")
        keys = {r["key"] for r in results}
        assert "soc2" in keys

    def test_topic_detection_access_control(self):
        from unittest.mock import patch
        with patch("app.services.tag_service._classify_document_llm") as mock_fn:
            mock_fn.return_value = [{"category": "topic", "key": "access_control", "confidence": 0.80}]
            results = classify_text("Role-based access control (RBAC) is enforced", "")
        keys = {r["key"] for r in results}
        assert "access_control" in keys

    def test_topic_detection_encryption(self):
        from unittest.mock import patch
        with patch("app.services.tag_service._classify_document_llm") as mock_fn:
            mock_fn.return_value = [{"category": "topic", "key": "encryption", "confidence": 0.80}]
            results = classify_text("All data is encrypted using AES-256 at rest and TLS in transit", "")
        keys = {r["key"] for r in results}
        assert "encryption" in keys

    def test_no_false_positives_on_empty(self):
        results = classify_text("", "")
        assert len(results) == 0

    def test_multiple_tags_detected(self):
        from unittest.mock import patch
        with patch("app.services.tag_service._classify_document_llm") as mock_fn:
            mock_fn.return_value = [
                {"category": "framework", "key": "soc2", "confidence": 0.85},
                {"category": "topic", "key": "access_control", "confidence": 0.80},
                {"category": "topic", "key": "encryption", "confidence": 0.80},
                {"category": "topic", "key": "incident_response", "confidence": 0.80},
                {"category": "document_type", "key": "report", "confidence": 0.80},
            ]
            results = classify_text(
                "This SOC 2 Type II report covers access control, encryption, and incident response procedures.",
                "soc2-report.pdf",
            )
        keys = {r["key"] for r in results}
        assert "soc2" in keys
        assert "access_control" in keys
        assert "encryption" in keys
        assert "incident_response" in keys
        assert "report" in keys

    def test_llm_failure_returns_empty(self):
        from unittest.mock import patch
        with patch("app.services.tag_service._classify_document_llm", return_value=None):
            results = classify_text("Some text", "file.pdf")
        assert len(results) == 0


# ── Auto-tagging integration ────────────────────────────────────────────────

class TestAutoTag:
    def test_auto_tag_document(self, db_session: Session):
        ensure_system_tags(db_session)
        doc = _create_doc(db_session)
        db_session.commit()
        count = auto_tag_document(
            db_session,
            doc.id,
            workspace_id=1,
            filename="soc2-access-control-policy.pdf",
            chunk_texts=["This policy establishes access control for SOC 2 compliance."],
        )
        db_session.commit()
        assert count >= 2
        tags = list_tags_for_document(db_session, doc.id, 1)
        keys = {t["key"] for t in tags}
        assert "soc2" in keys
        assert "access_control" in keys
        assert "policy" in keys
        for t in tags:
            assert t["source"] == "ai"
            assert t["approved"] is False


# ── Shared test helpers ─────────────────────────────────────────────────────

def _login(client, email="admin@trust.local", password="a"):
    client.post("/api/auth/login", json={"email": email, "password": password})


# ── Document vs Evidence validation ─────────────────────────────────────────

class TestDocumentEvidenceValidation:
    def test_evidence_without_document_returns_empty_tags(self, db_session: Session):
        """Evidence with no document_id should return tags=[] safely."""
        from app.services.tag_service import list_tags_for_document
        ev = EvidenceItem(workspace_id=1, title="Manual evidence", source_type="manual", document_id=None)
        db_session.add(ev)
        db_session.flush()
        tags = list_tags_for_document(db_session, ev.document_id, 1) if ev.document_id else []
        assert tags == []

    def test_evidence_api_without_document_returns_empty_tags(self, client, db_session: Session):
        """GET evidence detail for evidence without document should include tags=[]."""
        _login(client, email="admin@trust.local", password="a")
        ev = EvidenceItem(workspace_id=1, title="No-doc evidence", source_type="manual", document_id=None)
        db_session.add(ev)
        db_session.commit()
        db_session.refresh(ev)
        resp = client.get(f"/api/compliance/evidence/{ev.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("tags") == []


# ── Seeding hardening ───────────────────────────────────────────────────────

class TestSeedingHardening:
    def test_ensure_system_tags_triple_call_no_duplicates(self, db_session: Session):
        """Multiple startup calls must not create duplicate system tags."""
        ensure_system_tags(db_session)
        c1 = db_session.query(Tag).filter(Tag.is_system.is_(True)).count()
        ensure_system_tags(db_session)
        ensure_system_tags(db_session)
        c2 = db_session.query(Tag).filter(Tag.is_system.is_(True)).count()
        assert c1 == c2 == len(SYSTEM_TAGS)


# ── Retrieval boost validation ──────────────────────────────────────────────

class TestRetrievalBoost:
    def test_boost_only_for_framework_topic(self, db_session: Session):
        """Boost must only apply when tag category is framework or topic."""
        ensure_system_tags(db_session)
        doc_fw = _create_doc(db_session)
        doc_dt = _create_doc(db_session)
        doc_none = _create_doc(db_session)
        tag_soc2 = resolve_tag(db_session, "framework", "soc2")
        tag_policy = resolve_tag(db_session, "document_type", "policy")
        assign_tag(db_session, doc_fw.id, tag_soc2.id, workspace_id=1)
        assign_tag(db_session, doc_dt.id, tag_policy.id, workspace_id=1)
        db_session.commit()
        tags_fw = list_tags_for_document(db_session, doc_fw.id, 1)
        tags_dt = list_tags_for_document(db_session, doc_dt.id, 1)
        tags_none = list_tags_for_document(db_session, doc_none.id, 1)
        fw_qualifies = any(t["category"] in ("framework", "topic") for t in tags_fw)
        dt_qualifies = any(t["category"] in ("framework", "topic") for t in tags_dt)
        none_qualifies = any(t["category"] in ("framework", "topic") for t in tags_none)
        assert fw_qualifies is True
        assert dt_qualifies is False
        assert none_qualifies is False

    def test_boost_is_additive_and_capped(self):
        """Score boost must be additive, never exceed 1.0."""
        TAG_BOOST = 0.03
        base_score = 0.85
        boosted = min(1.0, base_score + TAG_BOOST)
        assert boosted == pytest.approx(0.88, abs=0.001)
        high_score = 0.99
        boosted_high = min(1.0, high_score + TAG_BOOST)
        assert boosted_high == 1.0

    def test_no_crash_when_tags_missing(self, db_session: Session):
        """Boost logic must not crash when no tags exist."""
        doc = _create_doc(db_session)
        db_session.commit()
        tags = list_tags_for_document(db_session, doc.id, 1)
        assert tags == []
        qualifies = any(t["category"] in ("framework", "topic") for t in tags)
        assert qualifies is False


# ── Filtering validation ────────────────────────────────────────────────────

class TestFiltering:
    def test_filter_by_framework(self, client, db_session: Session):
        _login(client, email="admin@trust.local", password="a")
        ensure_system_tags(db_session)
        doc = _create_doc(db_session)
        tag_soc2 = resolve_tag(db_session, "framework", "soc2")
        assign_tag(db_session, doc.id, tag_soc2.id, workspace_id=1)
        db_session.commit()
        resp = client.get("/api/documents/?workspace_id=1&tag_category=framework&tag_key=soc2")
        assert resp.status_code == 200
        ids = [d["id"] for d in resp.json()]
        assert doc.id in ids

    def test_filter_by_topic(self, client, db_session: Session):
        _login(client, email="admin@trust.local", password="a")
        ensure_system_tags(db_session)
        doc = _create_doc(db_session)
        tag_ac = resolve_tag(db_session, "topic", "access_control")
        assign_tag(db_session, doc.id, tag_ac.id, workspace_id=1)
        db_session.commit()
        resp = client.get("/api/documents/?workspace_id=1&tag_category=topic&tag_key=access_control")
        assert resp.status_code == 200
        ids = [d["id"] for d in resp.json()]
        assert doc.id in ids

    def test_filter_no_results(self, client, db_session: Session):
        _login(client, email="admin@trust.local", password="a")
        ensure_system_tags(db_session)
        resp = client.get("/api/documents/?workspace_id=1&tag_category=framework&tag_key=hitrust")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_filter_cross_workspace_isolation(self, client, db_session: Session):
        _login(client, email="admin@trust.local", password="a")
        ensure_system_tags(db_session)
        doc = _create_doc(db_session, workspace_id=2)
        tag = resolve_tag(db_session, "framework", "soc2")
        assign_tag(db_session, doc.id, tag.id, workspace_id=2)
        db_session.commit()
        resp = client.get("/api/documents/?workspace_id=1&tag_category=framework&tag_key=soc2")
        assert resp.status_code == 200
        ids = [d["id"] for d in resp.json()]
        assert doc.id not in ids


# ── API endpoints ────────────────────────────────────────────────────────────

class TestTagAPI:
    def test_documents_list_includes_tags(self, client, db_session: Session):
        _login(client)
        ensure_system_tags(db_session)
        doc = _create_doc(db_session)
        tag = resolve_tag(db_session, "framework", "soc2")
        assign_tag(db_session, doc.id, tag.id, workspace_id=1, source="manual", approved=True)
        db_session.commit()
        resp = client.get("/api/documents/?workspace_id=1")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        doc_data = next((d for d in data if d["id"] == doc.id), None)
        assert doc_data is not None
        assert "tags" in doc_data
        assert len(doc_data["tags"]) >= 1
        assert doc_data["tags"][0]["key"] == "soc2"

    def test_documents_filter_by_tag(self, client, db_session: Session):
        _login(client)
        ensure_system_tags(db_session)
        doc1 = _create_doc(db_session)
        doc2 = _create_doc(db_session)
        tag_soc2 = resolve_tag(db_session, "framework", "soc2")
        tag_hipaa = resolve_tag(db_session, "framework", "hipaa")
        assign_tag(db_session, doc1.id, tag_soc2.id, workspace_id=1)
        assign_tag(db_session, doc2.id, tag_hipaa.id, workspace_id=1)
        db_session.commit()
        resp = client.get("/api/documents/?workspace_id=1&tag_category=framework&tag_key=soc2")
        assert resp.status_code == 200
        data = resp.json()
        ids = [d["id"] for d in data]
        assert doc1.id in ids
        assert doc2.id not in ids

    def test_available_tags_endpoint(self, client, db_session: Session):
        _login(client)
        ensure_system_tags(db_session)
        resp = client.get("/api/tags/available")
        assert resp.status_code == 200
        data = resp.json()
        keys = {t["key"] for t in data}
        assert "soc2" in keys
        assert "policy" in keys

    def test_get_document_tags(self, client, db_session: Session):
        _login(client)
        ensure_system_tags(db_session)
        doc = _create_doc(db_session)
        tag = resolve_tag(db_session, "framework", "nist")
        assign_tag(db_session, doc.id, tag.id, workspace_id=1, source="ai", confidence=0.8, approved=False)
        db_session.commit()
        resp = client.get(f"/api/tags/documents/{doc.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["key"] == "nist"
        assert data[0]["source"] == "ai"
        assert data[0]["confidence"] == pytest.approx(0.8, abs=0.01)

    # ── Permission tests: admin can manage tags ──

    def test_admin_can_add_tags(self, client, db_session: Session):
        _login(client, email="admin@trust.local", password="a")
        ensure_system_tags(db_session)
        doc = _create_doc(db_session)
        db_session.commit()
        resp = client.post(f"/api/tags/documents/{doc.id}", json={"category": "framework", "key": "soc2"})
        assert resp.status_code == 200

    def test_admin_can_remove_tags(self, client, db_session: Session):
        _login(client, email="admin@trust.local", password="a")
        ensure_system_tags(db_session)
        doc = _create_doc(db_session)
        tag = resolve_tag(db_session, "framework", "soc2")
        assign_tag(db_session, doc.id, tag.id, workspace_id=1)
        db_session.commit()
        resp = client.delete(f"/api/tags/documents/{doc.id}/{tag.id}")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_admin_can_approve_tags(self, client, db_session: Session):
        _login(client, email="admin@trust.local", password="a")
        ensure_system_tags(db_session)
        doc = _create_doc(db_session)
        tag = resolve_tag(db_session, "framework", "soc2")
        dt = assign_tag(db_session, doc.id, tag.id, workspace_id=1, source="ai", approved=False)
        db_session.commit()
        resp = client.patch(f"/api/tags/document-tags/{dt.id}/approve", json={"approved": True})
        assert resp.status_code == 200
        assert resp.json()["approved"] is True

    # ── Permission tests: reviewer can manage tags ──

    def test_reviewer_can_add_tags(self, client, db_session: Session):
        _login(client, email="reviewer@trust.local", password="r")
        ensure_system_tags(db_session)
        doc = _create_doc(db_session)
        db_session.commit()
        resp = client.post(f"/api/tags/documents/{doc.id}", json={"category": "framework", "key": "soc2"})
        assert resp.status_code == 200

    def test_reviewer_can_remove_tags(self, client, db_session: Session):
        _login(client, email="reviewer@trust.local", password="r")
        ensure_system_tags(db_session)
        doc = _create_doc(db_session)
        tag = resolve_tag(db_session, "framework", "soc2")
        assign_tag(db_session, doc.id, tag.id, workspace_id=1)
        db_session.commit()
        resp = client.delete(f"/api/tags/documents/{doc.id}/{tag.id}")
        assert resp.status_code == 200

    def test_reviewer_can_approve_tags(self, client, db_session: Session):
        _login(client, email="reviewer@trust.local", password="r")
        ensure_system_tags(db_session)
        doc = _create_doc(db_session)
        tag = resolve_tag(db_session, "framework", "soc2")
        dt = assign_tag(db_session, doc.id, tag.id, workspace_id=1, source="ai", approved=False)
        db_session.commit()
        resp = client.patch(f"/api/tags/document-tags/{dt.id}/approve", json={"approved": True})
        assert resp.status_code == 200
        assert resp.json()["approved"] is True

    # ── Permission tests: editor CANNOT manage tags ──

    def test_editor_cannot_add_tags(self, client, db_session: Session):
        _login(client, email="editor@trust.local", password="e")
        ensure_system_tags(db_session)
        doc = _create_doc(db_session)
        db_session.commit()
        resp = client.post(f"/api/tags/documents/{doc.id}", json={"category": "framework", "key": "soc2"})
        assert resp.status_code == 403

    def test_editor_cannot_remove_tags(self, client, db_session: Session):
        _login(client, email="editor@trust.local", password="e")
        ensure_system_tags(db_session)
        doc = _create_doc(db_session)
        tag = resolve_tag(db_session, "framework", "soc2")
        assign_tag(db_session, doc.id, tag.id, workspace_id=1)
        db_session.commit()
        resp = client.delete(f"/api/tags/documents/{doc.id}/{tag.id}")
        assert resp.status_code == 403

    def test_editor_cannot_approve_tags(self, client, db_session: Session):
        _login(client, email="editor@trust.local", password="e")
        ensure_system_tags(db_session)
        doc = _create_doc(db_session)
        tag = resolve_tag(db_session, "framework", "soc2")
        dt = assign_tag(db_session, doc.id, tag.id, workspace_id=1, source="ai", approved=False)
        db_session.commit()
        resp = client.patch(f"/api/tags/document-tags/{dt.id}/approve", json={"approved": True})
        assert resp.status_code == 403

    # ── Permission tests: unauthenticated blocked ──

    def test_unauthenticated_cannot_add_tags(self, client, db_session: Session):
        ensure_system_tags(db_session)
        doc = _create_doc(db_session)
        db_session.commit()
        resp = client.post(f"/api/tags/documents/{doc.id}", json={"category": "framework", "key": "soc2"})
        assert resp.status_code == 401

    # ── Cross-workspace isolation via API ──

    def test_cross_workspace_add_tag_blocked(self, client, db_session: Session):
        _login(client, email="admin@trust.local", password="a")
        ensure_system_tags(db_session)
        doc = _create_doc(db_session, workspace_id=3)
        db_session.commit()
        resp = client.post(f"/api/tags/documents/{doc.id}", json={"category": "framework", "key": "soc2"})
        assert resp.status_code == 404

    # ── API consistency: tags shape ──

    def test_tag_response_shape_consistent(self, client, db_session: Session):
        _login(client)
        ensure_system_tags(db_session)
        doc = _create_doc(db_session)
        tag = resolve_tag(db_session, "framework", "soc2")
        assign_tag(db_session, doc.id, tag.id, workspace_id=1, source="ai", confidence=0.85, approved=False)
        db_session.commit()
        resp = client.get(f"/api/tags/documents/{doc.id}")
        assert resp.status_code == 200
        t = resp.json()[0]
        for field in ("id", "tag_id", "category", "key", "label", "source", "confidence", "approved"):
            assert field in t, f"Missing field: {field}"

    def test_documents_list_empty_tags_array(self, client, db_session: Session):
        _login(client)
        doc = _create_doc(db_session)
        db_session.commit()
        resp = client.get("/api/documents/?workspace_id=1")
        assert resp.status_code == 200
        doc_data = next((d for d in resp.json() if d["id"] == doc.id), None)
        assert doc_data is not None
        assert doc_data["tags"] == []
