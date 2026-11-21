"""Tests for CRM connectors (E1-02, E1-03, TC-20-050)."""

import pytest
from tests.salesforce_pipeline_fixture import PipelineFixture, opportunity

from app.models.crm_connection import CrmConnection
from app.models.deal import Deal
from app.models.job import Job
from app.models.workspace import Workspace
from app.services import crm_connector_service as svc

_PIPELINE = "selected-pipeline"
_OPP_A = "006FIXTURE000001AAA"
_OPP_B = "006FIXTURE000002AAA"


def _pages() -> list[list[dict]]:
    return [
        [
            opportunity(
                external_id=_OPP_A,
                company="Northwind Fixture",
                amount=150000,
                stage="Evaluation",
                close_date="2026-06-30",
                currency="USD",
                modified="2026-11-01T00:00:00.000Z",
            )
        ],
        [
            opportunity(
                external_id=_OPP_B,
                company="Globex Fixture",
                amount=85000,
                stage="Negotiation",
                close_date="2026-05-15",
                currency="EUR",
                modified="2026-11-02T00:00:00.000Z",
            )
        ],
    ]


def _cleanup(db, workspace_id: int) -> None:
    db.rollback()
    (
        db.query(Deal)
        .filter(Deal.workspace_id == workspace_id, Deal.crm_external_id.in_([_OPP_A, _OPP_B]))
        .delete(synchronize_session=False)
    )
    connections = (
        db.query(CrmConnection)
        .filter(
            CrmConnection.workspace_id == workspace_id,
            CrmConnection.pipeline_id == _PIPELINE,
        )
        .all()
    )
    ids = [row.id for row in connections]
    if ids:
        db.query(Deal).filter(Deal.connection_id.in_(ids)).delete(synchronize_session=False)
        db.query(CrmConnection).filter(CrmConnection.id.in_(ids)).delete(synchronize_session=False)
    (
        db.query(Job)
        .filter(
            Job.workspace_id == workspace_id,
            Job.kind == "crm_sync",
            Job.payload.contains(_PIPELINE),
        )
        .delete(synchronize_session=False)
    )
    db.commit()


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200
    return client


@pytest.fixture
def editor_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
    assert r.status_code == 200
    return client


class TestCRMConnectorService:
    def test_sync_salesforce(self, db_session, monkeypatch):
        ws = db_session.query(Workspace).first()
        server = PipelineFixture(_pages())
        try:
            monkeypatch.setenv("SALESFORCE_API_BASE_URL", server.start())
            result = svc.sync_salesforce(db_session, ws.id, pipeline_id=_PIPELINE)
            assert result["source"] == "salesforce"
            assert result["synced"] >= 2
            assert "mock" not in result
        finally:
            server.stop()
            _cleanup(db_session, ws.id)

    def test_sync_hubspot(self, db_session):
        ws = db_session.query(Workspace).first()
        result = svc.sync_hubspot(db_session, ws.id)
        db_session.commit()
        assert result["source"] == "hubspot"
        assert result["synced"] >= 1
        assert result["data_basis"] == "synthetic_example"

    def test_idempotent_sync(self, db_session, monkeypatch):
        ws = db_session.query(Workspace).first()
        server = PipelineFixture(_pages())
        try:
            monkeypatch.setenv("SALESFORCE_API_BASE_URL", server.start())
            svc.sync_salesforce(db_session, ws.id, pipeline_id=_PIPELINE)
            result = svc.sync_salesforce(db_session, ws.id, pipeline_id=_PIPELINE)
            assert all(d["action"] == "updated" for d in result["details"])
        finally:
            server.stop()
            _cleanup(db_session, ws.id)

    def test_sync_status(self, db_session, monkeypatch):
        ws = db_session.query(Workspace).first()
        server = PipelineFixture(_pages())
        try:
            monkeypatch.setenv("SALESFORCE_API_BASE_URL", server.start())
            svc.sync_salesforce(db_session, ws.id, pipeline_id=_PIPELINE)
            svc.sync_hubspot(db_session, ws.id)
            db_session.commit()
            status = svc.get_sync_status(db_session, ws.id)
            assert status["salesforce"] >= 2
            assert status["hubspot"] >= 1
        finally:
            server.stop()
            _cleanup(db_session, ws.id)


class TestCRMAPI:
    def test_sync_salesforce(self, admin_client, db_session, monkeypatch):
        monkeypatch.setenv("SALESFORCE_API_BASE_URL", "http://127.0.0.1:9")
        workspace_id = None
        try:
            r = admin_client.post("/api/crm/sync/salesforce", json={"pipeline_id": _PIPELINE})
            assert r.status_code == 200
            body = r.json()
            workspace_id = body["workspace_id"]
            assert body["source"] == "salesforce"
            assert body["kind"] == "crm_sync"
            assert "mock" not in body
            cancelled = admin_client.post(
                f"/api/jobs/{body['job_id']}/cancel?workspace_id={body['workspace_id']}"
            )
            assert cancelled.status_code == 200
        finally:
            if workspace_id is not None:
                _cleanup(db_session, workspace_id)

    def test_sync_hubspot(self, admin_client):
        r = admin_client.post("/api/crm/sync/hubspot")
        assert r.status_code == 200
        assert r.json()["source"] == "hubspot"

    def test_status(self, admin_client):
        r = admin_client.get("/api/crm/status")
        assert r.status_code == 200
        assert "total" in r.json()

    def test_editor_cannot_sync(self, editor_client):
        r = editor_client.post("/api/crm/sync/salesforce", json={"pipeline_id": _PIPELINE})
        assert r.status_code == 403
