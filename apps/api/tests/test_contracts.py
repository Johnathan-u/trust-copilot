"""Tests for contract ingestion (E2-09)."""

import pytest
from app.models.workspace import Workspace
from app.services import contract_service as cs


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200
    return client


class TestContractService:
    def test_ingest_extracts_clauses(self, db_session):
        ws = db_session.query(Workspace).first()
        result = cs.ingest_contract(
            db_session, ws.id, "MSA 2026",
            body_text="Customer data retention 90 days. Breach notification within 72 hours. AES-256 encryption.",
        )
        db_session.commit()
        assert result["document_id"]
        assert len(result["clauses"]) >= 1
        assert len(result["promise_ids"]) >= 1

    def test_list(self, db_session):
        ws = db_session.query(Workspace).first()
        cs.ingest_contract(db_session, ws.id, "Doc B", body_text="retention policy")
        db_session.commit()
        lst = cs.list_contracts(db_session, ws.id)
        assert len(lst) >= 1


class TestContractAPI:
    def test_ingest(self, admin_client):
        r = admin_client.post("/api/contracts/ingest", json={
            "title": "Security Addendum",
            "body_text": "90 day retention and encryption at rest",
        })
        assert r.status_code == 200
        assert "promise_ids" in r.json()

    def test_list(self, admin_client):
        r = admin_client.get("/api/contracts")
        assert r.status_code == 200
        assert "documents" in r.json()
