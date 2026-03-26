"""Tests for the customer-ready export pack (P0-14)."""

import pytest


@pytest.fixture
def auth_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200
    return client


def _ensure_questionnaire(db):
    """Ensure a test questionnaire exists and return its ID."""
    from app.models.questionnaire import Questionnaire, Question
    qnr = db.query(Questionnaire).filter(Questionnaire.workspace_id == 1).first()
    if not qnr:
        qnr = Questionnaire(workspace_id=1, filename="test_export.xlsx", status="parsed")
        db.add(qnr)
        db.flush()
        db.add(Question(questionnaire_id=qnr.id, text="Do you encrypt data at rest?", section="Data Protection"))
        db.add(Question(questionnaire_id=qnr.id, text="How is access managed?", section="Access Control"))
        db.add(Question(questionnaire_id=qnr.id, text="Do you maintain audit logs?", section="Logging"))
        db.commit()
        db.refresh(qnr)
    return qnr.id


class TestExportPackService:
    def test_cover_page(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.export_pack_service import generate_cover_page
        db = SessionLocal()
        try:
            qid = _ensure_questionnaire(db)
            cover = generate_cover_page(db, 1, qid)
            assert "workspace_name" in cover
            assert "generated_date" in cover
            assert "total_questions" in cover
            assert cover["total_questions"] >= 1
            assert "confidentiality_notice" in cover
            assert "powered_by" in cover
        finally:
            db.close()

    def test_executive_summary(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.export_pack_service import generate_executive_summary
        db = SessionLocal()
        try:
            qid = _ensure_questionnaire(db)
            summary = generate_executive_summary(db, 1, qid)
            assert "total_questions" in summary
            assert "completion_rate" in summary
            assert "methodology" in summary
            assert "recommendation" in summary
            assert "section_breakdown" in summary
        finally:
            db.close()

    def test_evidence_bundle(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.export_pack_service import generate_evidence_bundle
        db = SessionLocal()
        try:
            qid = _ensure_questionnaire(db)
            bundle = generate_evidence_bundle(db, 1, qid)
            assert "total_documents_cited" in bundle
            assert "documents" in bundle
            assert "evidence_gaps" in bundle
            assert "bundle_generated_at" in bundle
        finally:
            db.close()

    def test_full_pack(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.export_pack_service import generate_full_pack
        db = SessionLocal()
        try:
            qid = _ensure_questionnaire(db)
            pack = generate_full_pack(db, 1, qid)
            assert "cover_page" in pack
            assert "executive_summary" in pack
            assert "evidence_bundle" in pack
            assert "generated_at" in pack
        finally:
            db.close()

    def test_nonexistent_questionnaire(self, client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        from app.services.export_pack_service import generate_cover_page
        db = SessionLocal()
        try:
            with pytest.raises(ValueError, match="not found"):
                generate_cover_page(db, 1, 999999)
        finally:
            db.close()

    def test_recommendation_high_confidence(self):
        from app.services.export_pack_service import _summary_recommendation
        rec = _summary_recommendation(95, 100, 100)
        assert "ready for submission" in rec

    def test_recommendation_gaps(self):
        from app.services.export_pack_service import _summary_recommendation
        rec = _summary_recommendation(50, 30, 100)
        assert "Upload" in rec or "upload" in rec


class TestExportPackAPI:
    def test_full_pack(self, auth_client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        db = SessionLocal()
        qid = _ensure_questionnaire(db)
        db.close()
        r = auth_client.get(f"/api/export-pack?questionnaire_id={qid}")
        assert r.status_code == 200
        data = r.json()
        assert "cover_page" in data
        assert "executive_summary" in data

    def test_cover_endpoint(self, auth_client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        db = SessionLocal()
        qid = _ensure_questionnaire(db)
        db.close()
        r = auth_client.get(f"/api/export-pack/cover?questionnaire_id={qid}")
        assert r.status_code == 200
        assert "workspace_name" in r.json()

    def test_summary_endpoint(self, auth_client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        db = SessionLocal()
        qid = _ensure_questionnaire(db)
        db.close()
        r = auth_client.get(f"/api/export-pack/summary?questionnaire_id={qid}")
        assert r.status_code == 200
        assert "methodology" in r.json()

    def test_evidence_endpoint(self, auth_client, _ensure_test_data):
        if not _ensure_test_data:
            pytest.skip("Postgres not available")
        from app.core.database import SessionLocal
        db = SessionLocal()
        qid = _ensure_questionnaire(db)
        db.close()
        r = auth_client.get(f"/api/export-pack/evidence?questionnaire_id={qid}")
        assert r.status_code == 200
        assert "total_documents_cited" in r.json()

    def test_not_found(self, auth_client):
        r = auth_client.get("/api/export-pack?questionnaire_id=999999")
        assert r.status_code == 404

    def test_unauthenticated(self, client):
        r = client.get("/api/export-pack?questionnaire_id=1")
        assert r.status_code == 401
