"""TC-20-050: paginated Salesforce pipeline sync against a local fixture server.

No Salesforce host, account, or credential is used. DoD6 sandbox evidence is
N/A under the owner ruling that Salesforce is qualified with fixtures and a
mock server.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.salesforce_pipeline_fixture import PipelineFixture, opportunity

from app.core.job_errors import RetryableJobError, TerminalJobError
from app.models.crm_connection import CrmConnection
from app.models.deal import Deal
from app.models.job import Job
from app.services.deal_service import update_deal
from app.services.salesforce_pipeline_client import SalesforceClientError, salesforce_base_url

PIPELINE = "selected-pipeline"
CANCEL_PIPELINE = "cancel-pipeline"
OPP_A = "006FIXTURE000001AAA"
OPP_B = "006FIXTURE000002AAA"
MOD_A = "2026-11-01T00:00:00.000Z"
MOD_B = "2026-11-02T00:00:00.000Z"


def _opp_a(company: str = "Northwind Fixture") -> dict:
    return opportunity(
        external_id=OPP_A,
        company=company,
        amount=150000,
        stage="Evaluation",
        close_date="2026-06-30",
        currency="USD",
        modified=MOD_A,
    )


def _opp_b() -> dict:
    return opportunity(
        external_id=OPP_B,
        company="Globex Fixture",
        amount=85000,
        stage="Negotiation",
        close_date="2026-05-15",
        currency="EUR",
        modified=MOD_B,
    )


def _two_pages(company: str = "Northwind Fixture") -> list[list[dict]]:
    return [[_opp_a(company)], [_opp_b()]]


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert response.status_code == 200
    return client


@pytest.fixture
def editor_client(client):
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
    assert response.status_code == 200
    return client


def _workspace(admin_client) -> int:
    me = admin_client.get("/api/auth/me")
    assert me.status_code == 200
    return me.json()["workspace_id"]


def _cleanup(db, workspace_id: int, pipelines: list[str], external_ids: list[str]) -> None:
    db.rollback()
    connections = (
        db.query(CrmConnection)
        .filter(
            CrmConnection.workspace_id == workspace_id,
            CrmConnection.pipeline_id.in_(pipelines),
        )
        .all()
    )
    connection_ids = [row.id for row in connections]
    if external_ids:
        (
            db.query(Deal)
            .filter(Deal.workspace_id == workspace_id, Deal.crm_external_id.in_(external_ids))
            .delete(synchronize_session=False)
        )
    if connection_ids:
        (
            db.query(Deal)
            .filter(Deal.connection_id.in_(connection_ids))
            .delete(synchronize_session=False)
        )
        (
            db.query(CrmConnection)
            .filter(CrmConnection.id.in_(connection_ids))
            .delete(synchronize_session=False)
        )
    for pipeline in pipelines:
        (
            db.query(Job)
            .filter(
                Job.workspace_id == workspace_id,
                Job.kind == "crm_sync",
                Job.payload.contains(pipeline),
            )
            .delete(synchronize_session=False)
        )
    db.commit()


def _history_item(admin_client, workspace_id: int, job_id: int) -> dict:
    response = admin_client.get(f"/api/jobs?workspace_id={workspace_id}&limit=25")
    assert response.status_code == 200
    return next(row for row in response.json()["items"] if row["id"] == job_id)


def _deals(db, workspace_id: int, connection_id: int) -> list[Deal]:
    db.expire_all()
    return (
        db.query(Deal)
        .filter(Deal.workspace_id == workspace_id, Deal.connection_id == connection_id)
        .order_by(Deal.crm_external_id)
        .all()
    )


def test_salesforce_host_and_unconfigured_base_are_refused(monkeypatch):
    monkeypatch.delenv("SALESFORCE_API_BASE_URL", raising=False)
    with pytest.raises(SalesforceClientError) as missing:
        salesforce_base_url()
    assert missing.value.code == "config_error"
    monkeypatch.setenv("SALESFORCE_API_BASE_URL", "https://example.salesforce.com")
    with pytest.raises(SalesforceClientError) as blocked:
        salesforce_base_url()
    assert blocked.value.code == "config_error"


def test_editor_cannot_sync(editor_client):
    denied = editor_client.post("/api/crm/sync/salesforce", json={"pipeline_id": PIPELINE})
    assert denied.status_code == 403


def test_bad_pipeline_and_missing_base_are_rejected(admin_client, monkeypatch):
    monkeypatch.setenv("SALESFORCE_API_BASE_URL", "http://127.0.0.1:9")
    invalid = admin_client.post("/api/crm/sync/salesforce", json={"pipeline_id": "has space"})
    assert invalid.status_code == 422
    monkeypatch.delenv("SALESFORCE_API_BASE_URL", raising=False)
    unconfigured = admin_client.post("/api/crm/sync/salesforce", json={"pipeline_id": PIPELINE})
    assert unconfigured.status_code == 409
    assert "mock" not in unconfigured.text


def test_paginated_sync_persists_identity_and_retry_does_not_duplicate(
    admin_client, db_session, monkeypatch
):
    workspace_id = _workspace(admin_client)
    server = PipelineFixture(_two_pages())
    try:
        monkeypatch.setenv("SALESFORCE_API_BASE_URL", server.start())
        queued = admin_client.post("/api/crm/sync/salesforce", json={"pipeline_id": PIPELINE})
        assert queued.status_code == 200, queued.text
        body = queued.json()
        assert body["source"] == "salesforce"
        assert body["kind"] == "crm_sync"
        assert body["workspace_id"] == workspace_id
        assert "mock" not in body
        assert body.get("data_basis") != "synthetic_example"
        from app.worker import run_job

        job = db_session.get(Job, body["job_id"])
        run_job(job, db_session)
        db_session.commit()
        result = json.loads(job.result)
        assert result["generated"] == 2
        assert result["total"] == 2
        assert result["provider"] == "salesforce"
        deals = _deals(db_session, workspace_id, body["connection_id"])
        assert [row.crm_external_id for row in deals] == [OPP_A, OPP_B]
        first, second = deals
        assert first.company_name == "Northwind Fixture"
        assert first.currency == "USD"
        assert str(first.deal_value_arr) == "150000.00"
        assert first.stage == "evaluation"
        assert first.close_date is not None and first.close_date.date().isoformat() == "2026-06-30"
        assert first.expected_close_date.isoformat() == "2026-06-30"
        assert second.currency == "EUR"
        assert second.stage == "negotiation"
        assert second.expected_close_date.isoformat() == "2026-05-15"
        stable_a = f"{workspace_id}:{body['connection_id']}:salesforce:{OPP_A}"
        stable_b = f"{workspace_id}:{body['connection_id']}:salesforce:{OPP_B}"
        assert first.crm_stable_id == stable_a
        assert second.crm_stable_id == stable_b
        assert first.provider == "salesforce"
        assert first.crm_source == "salesforce"
        connection = db_session.get(CrmConnection, body["connection_id"])
        assert connection.cursor_kind == "complete"
        assert connection.cursor == MOD_B
        assert any("PipelineId" in call and PIPELINE in call for call in server.calls)
        assert any("fixture-page-2" in call for call in server.calls)
        ids = [row.id for row in deals]
        from app.services.crm_connector_service import sync_salesforce

        again = sync_salesforce(
            db_session,
            workspace_id,
            pipeline_id=PIPELINE,
            connection_id=body["connection_id"],
        )
        assert again["created"] == 0
        assert again["updated"] == 2
        assert all(row["action"] == "updated" for row in again["details"])
        assert "mock" not in again
        retried = _deals(db_session, workspace_id, body["connection_id"])
        assert [row.id for row in retried] == ids
        assert retried[0].crm_stable_id == stable_a
        assert retried[1].crm_stable_id == stable_b
    finally:
        server.stop()
        _cleanup(db_session, workspace_id, [PIPELINE], [OPP_A, OPP_B])


def test_manual_edit_survives_and_removed_record_is_tombstoned(
    admin_client, db_session, monkeypatch
):
    workspace_id = _workspace(admin_client)
    server = PipelineFixture(_two_pages())
    try:
        monkeypatch.setenv("SALESFORCE_API_BASE_URL", server.start())
        from app.services.crm_connector_service import sync_salesforce

        first = sync_salesforce(db_session, workspace_id, pipeline_id=PIPELINE)
        deals = _deals(db_session, workspace_id, first["connection_id"])
        kept = next(row for row in deals if row.crm_external_id == OPP_A)
        removed = next(row for row in deals if row.crm_external_id == OPP_B)
        update_deal(
            db_session,
            kept.id,
            workspace_id=workspace_id,
            stage="closed_won",
            notes="buyer asked to keep this stage",
        )
        db_session.commit()
        server.pages[:] = [_two_pages("Northwind Updated")[0], _two_pages()[1]]
        second = sync_salesforce(
            db_session,
            workspace_id,
            pipeline_id=PIPELINE,
            connection_id=first["connection_id"],
        )
        assert second["created"] == 0
        db_session.expire_all()
        assert kept.stage == "closed_won"
        assert kept.notes == "buyer asked to keep this stage"
        assert kept.company_name == "Northwind Updated"
        assert kept.currency == "USD"
        assert kept.crm_stable_id == f"{workspace_id}:{first['connection_id']}:salesforce:{OPP_A}"
        server.pages[:] = [[_opp_a("Northwind Updated")]]
        third = sync_salesforce(
            db_session,
            workspace_id,
            pipeline_id=PIPELINE,
            connection_id=first["connection_id"],
        )
        assert third["tombstoned"] == 1
        db_session.expire_all()
        assert kept.crm_removed_at is None
        assert kept.stage == "closed_won"
        assert removed.crm_removed_at is not None
        assert removed.id != kept.id
        rows = _deals(db_session, workspace_id, first["connection_id"])
        assert len(rows) == 2
    finally:
        server.stop()
        _cleanup(db_session, workspace_id, [PIPELINE], [OPP_A, OPP_B])


def test_interrupted_page_resumes_without_a_second_row(admin_client, db_session, monkeypatch):
    workspace_id = _workspace(admin_client)
    server = PipelineFixture(_two_pages())
    server.fail_paths["/services/data/v59.0/query/fixture-page-2"] = 500
    try:
        monkeypatch.setenv("SALESFORCE_API_BASE_URL", server.start())
        queued = admin_client.post("/api/crm/sync/salesforce", json={"pipeline_id": PIPELINE})
        assert queued.status_code == 200
        body = queued.json()
        from app.worker import run_job

        job = db_session.get(Job, body["job_id"])
        with pytest.raises(RetryableJobError) as caught:
            run_job(job, db_session)
        assert caught.value.code == "upstream_unavailable"
        db_session.rollback()
        deals = _deals(db_session, workspace_id, body["connection_id"])
        assert len(deals) == 1
        assert deals[0].crm_external_id == OPP_A
        first_id = deals[0].id
        connection = db_session.get(CrmConnection, body["connection_id"])
        assert connection.cursor_kind == "page"
        assert connection.cursor == "/services/data/v59.0/query/fixture-page-2"
        server.fail_paths.clear()
        job = db_session.get(Job, body["job_id"])
        run_job(job, db_session)
        db_session.commit()
        deals = _deals(db_session, workspace_id, body["connection_id"])
        assert [row.crm_external_id for row in deals] == [OPP_A, OPP_B]
        assert deals[0].id == first_id
        connection = db_session.get(CrmConnection, body["connection_id"])
        assert connection.cursor_kind == "complete"
        assert connection.cursor == MOD_B
    finally:
        server.stop()
        _cleanup(db_session, workspace_id, [PIPELINE], [OPP_A, OPP_B])


def test_off_origin_next_page_is_not_followed(admin_client, db_session, monkeypatch):
    workspace_id = _workspace(admin_client)
    server = PipelineFixture([[_opp_a()]])
    server.forced_next = "https://example.salesforce.com/services/data/v59.0/query/006"
    try:
        monkeypatch.setenv("SALESFORCE_API_BASE_URL", server.start())
        queued = admin_client.post("/api/crm/sync/salesforce", json={"pipeline_id": PIPELINE})
        assert queued.status_code == 200
        from app.worker import run_job

        job = db_session.get(Job, queued.json()["job_id"])
        with pytest.raises(TerminalJobError) as caught:
            run_job(job, db_session)
        assert caught.value.code == "bad_input"
        db_session.rollback()
        assert server.calls
        assert all("salesforce.com" not in call for call in server.calls)
        assert (
            db_session.query(Deal)
            .filter(Deal.workspace_id == workspace_id, Deal.crm_external_id == OPP_A)
            .count()
            == 0
        )
    finally:
        server.stop()
        _cleanup(db_session, workspace_id, [PIPELINE], [OPP_A, OPP_B])


def test_same_external_id_is_distinct_per_connection_and_provider(db_session, monkeypatch):
    from app.models.workspace import Workspace

    workspace_id = db_session.query(Workspace).first().id
    hub = Deal(
        workspace_id=workspace_id,
        company_name="Hubspot fixture",
        stage="prospect",
        crm_source="hubspot",
        provider="hubspot",
        crm_external_id=OPP_A,
    )
    db_session.add(hub)
    db_session.commit()
    server = PipelineFixture([[_opp_a()]])
    try:
        from app.services.crm_connector_service import sync_salesforce

        monkeypatch.setenv("SALESFORCE_API_BASE_URL", server.start())
        first = sync_salesforce(db_session, workspace_id, pipeline_id=PIPELINE)
        second = sync_salesforce(db_session, workspace_id, pipeline_id="other-pipeline")
        assert first["connection_id"] != second["connection_id"]
        rows = (
            db_session.query(Deal)
            .filter(Deal.workspace_id == workspace_id, Deal.crm_external_id == OPP_A)
            .all()
        )
        assert len(rows) == 3
        assert {row.provider for row in rows} == {"hubspot", "salesforce"}
        db_session.expire_all()
        assert hub.company_name == "Hubspot fixture"
        assert hub.provider == "hubspot"
    finally:
        server.stop()
        _cleanup(db_session, workspace_id, [PIPELINE, "other-pipeline"], [OPP_A])


def test_unique_identity_rejects_a_second_row(db_session):
    definition = db_session.execute(
        text(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' "
            "AND indexname = 'uq_deals_ws_connection_provider_external'"
        )
    ).scalar_one()
    assert "UNIQUE" in definition.upper()
    for column in ("workspace_id", "connection_id", "provider", "crm_external_id"):
        assert column in definition
    from app.models.workspace import Workspace

    workspace_id = db_session.query(Workspace).first().id
    connection = CrmConnection(
        workspace_id=workspace_id, provider="salesforce", pipeline_id="unique-pipeline"
    )
    db_session.add(connection)
    db_session.flush()
    shared = dict(
        workspace_id=workspace_id,
        connection_id=connection.id,
        provider="salesforce",
        crm_external_id="006FIXTUREDUP000001",
        crm_source="salesforce",
        stage="prospect",
    )
    db_session.add(Deal(company_name="First fixture", **shared))
    db_session.flush()
    db_session.add(Deal(company_name="Second fixture", **shared))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_job_history_keeps_progress_link_cancel_and_retry(admin_client, db_session, monkeypatch):
    workspace_id = _workspace(admin_client)
    server = PipelineFixture(_two_pages())
    try:
        monkeypatch.setenv("SALESFORCE_API_BASE_URL", server.start())
        queued = admin_client.post("/api/crm/sync/salesforce", json={"pipeline_id": PIPELINE})
        assert queued.status_code == 200
        body = queued.json()
        from app.worker import run_job

        job = db_session.get(Job, body["job_id"])
        run_job(job, db_session)
        job.status = "completed"
        db_session.commit()
        link = {"type": "crm_connection", "id": body["connection_id"]}
        shown = _history_item(admin_client, workspace_id, body["job_id"])
        assert shown["kind"] == "crm_sync"
        assert shown["status"] == "completed"
        assert shown["progress"] == {"generated": 2, "total": 2}
        assert shown["object_ref"] == link
        reloaded = _history_item(admin_client, workspace_id, body["job_id"])
        assert reloaded["object_ref"] == link
        assert reloaded["progress"] == {"generated": 2, "total": 2}
        again = admin_client.post("/api/crm/sync/salesforce", json={"pipeline_id": CANCEL_PIPELINE})
        assert again.status_code == 200
        failed_id = again.json()["job_id"]
        failed_link = {"type": "crm_connection", "id": again.json()["connection_id"]}
        failed = db_session.get(Job, failed_id)
        failed.status = "failed"
        failed.error_code = "upstream_unavailable"
        failed.error = "upstream_unavailable"
        db_session.commit()
        retried = admin_client.post(f"/api/jobs/{failed_id}/retry?workspace_id={workspace_id}")
        assert retried.status_code == 200
        assert retried.json()["status"] == "queued"
        assert retried.json()["kind"] == "crm_sync"
        after_retry = _history_item(admin_client, workspace_id, failed_id)
        assert after_retry["status"] == "queued"
        assert after_retry["object_ref"] == failed_link
        cancelled = admin_client.post(f"/api/jobs/{failed_id}/cancel?workspace_id={workspace_id}")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        after_cancel = _history_item(admin_client, workspace_id, failed_id)
        assert after_cancel["status"] == "cancelled"
        assert after_cancel["object_ref"] == failed_link
        foreign = _history_item(admin_client, workspace_id, body["job_id"])
        assert foreign["object_ref"] == link
    finally:
        server.stop()
        _cleanup(db_session, workspace_id, [PIPELINE, CANCEL_PIPELINE], [OPP_A, OPP_B])
