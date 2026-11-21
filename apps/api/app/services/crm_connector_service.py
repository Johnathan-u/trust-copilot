"""CRM connector service (E1-02, E1-03, TC-20-050).

Salesforce reads the selected pipeline from ``SALESFORCE_API_BASE_URL``
(a local fixture server in tests) and enqueues the shared ``crm_sync`` job.
HubSpot still returns the labeled example until TC-20-053. Neither path
calls a provider hostname from this module, and neither stores a credential.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.crm_connection import CrmConnection
from app.models.deal import Deal
from app.models.job import Job, JobKind
from app.services.deal_service import manual_field_names, parse_amount
from app.services.job_effects import enqueue_job, job_idempotency_key
from app.services.salesforce_pipeline_client import (
    SalesforceClientError,
    SalesforceOpportunity,
    SalesforcePipelineClient,
    parse_opportunity,
    salesforce_base_url,
)

logger = logging.getLogger(__name__)

_MAX_PAGES = 50
_LOCK_GROUPS = (
    frozenset({"deal_value_arr", "currency"}),
    frozenset({"close_date", "expected_close_date"}),
)


class ConnectionNotFound(LookupError):
    """No CRM connection with this id in the caller's workspace."""


class PipelineMismatch(ValueError):
    """The connection is not the selected pipeline."""


def stable_crm_id(workspace_id: int, connection_id: int, provider: str, external_id: str) -> str:
    """Identity that does not change for one workspace, connection, provider, and external id."""
    return f"{workspace_id}:{connection_id}:{provider}:{external_id}"


def _field_locked(key: str, manual: set[str]) -> bool:
    if key in manual:
        return True
    return any(key in group and manual.intersection(group) for group in _LOCK_GROUPS)


def _values(opportunity: SalesforceOpportunity) -> dict:
    values = {"company_name": opportunity.company_name, "stage": opportunity.stage}
    if opportunity.amount is not None:
        values["deal_value_arr"] = parse_amount(opportunity.amount)
        values["currency"] = opportunity.currency
    if opportunity.close_date is not None:
        day = opportunity.close_date
        values["close_date"] = datetime(day.year, day.month, day.day)
        values["expected_close_date"] = day
    return values


def _load_seen(raw: str | None) -> set[str]:
    if not raw:
        return set()
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise SalesforceClientError("bad_input") from exc
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise SalesforceClientError("bad_input")
    return set(value)


def ensure_salesforce_connection(
    db: Session,
    workspace_id: int,
    pipeline_id: str,
    connection_id: int | None,
) -> CrmConnection:
    if connection_id is not None:
        row = (
            db.query(CrmConnection)
            .filter(
                CrmConnection.id == connection_id,
                CrmConnection.workspace_id == workspace_id,
                CrmConnection.provider == "salesforce",
            )
            .one_or_none()
        )
        if row is None:
            raise ConnectionNotFound(connection_id)
        if row.pipeline_id != pipeline_id:
            raise PipelineMismatch(pipeline_id)
        return row
    row = (
        db.query(CrmConnection)
        .filter(
            CrmConnection.workspace_id == workspace_id,
            CrmConnection.provider == "salesforce",
            CrmConnection.pipeline_id == pipeline_id,
        )
        .one_or_none()
    )
    if row is not None:
        return row
    row = CrmConnection(workspace_id=workspace_id, provider="salesforce", pipeline_id=pipeline_id)
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        row = (
            db.query(CrmConnection)
            .filter(
                CrmConnection.workspace_id == workspace_id,
                CrmConnection.provider == "salesforce",
                CrmConnection.pipeline_id == pipeline_id,
            )
            .one_or_none()
        )
        if row is None:
            raise
    return row


def _lookup_deal(db: Session, connection: CrmConnection, external_id: str) -> Deal | None:
    return (
        db.query(Deal)
        .filter(
            Deal.workspace_id == connection.workspace_id,
            Deal.connection_id == connection.id,
            Deal.provider == "salesforce",
            Deal.crm_external_id == external_id,
        )
        .one_or_none()
    )


def _apply_opportunity(
    db: Session, connection: CrmConnection, opportunity: SalesforceOpportunity
) -> dict:
    stable = stable_crm_id(
        connection.workspace_id, connection.id, "salesforce", opportunity.external_id
    )
    existing = _lookup_deal(db, connection, opportunity.external_id)
    values = _values(opportunity)
    if existing is None:
        deal = Deal(
            workspace_id=connection.workspace_id,
            company_name=values["company_name"],
            deal_value_arr=values.get("deal_value_arr"),
            currency=values.get("currency"),
            stage=values["stage"],
            close_date=values.get("close_date"),
            expected_close_date=values.get("expected_close_date"),
            crm_source="salesforce",
            provider="salesforce",
            connection_id=connection.id,
            crm_external_id=opportunity.external_id,
            crm_stable_id=stable,
        )
        try:
            with db.begin_nested():
                db.add(deal)
                db.flush()
        except IntegrityError:
            existing = _lookup_deal(db, connection, opportunity.external_id)
            if existing is None:
                raise
        else:
            return {
                "action": "created",
                "external_id": opportunity.external_id,
                "deal_id": deal.id,
                "stable_id": stable,
            }
    manual = manual_field_names(existing)
    for key, value in values.items():
        if _field_locked(key, manual):
            continue
        setattr(existing, key, value)
    if not existing.crm_stable_id:
        existing.crm_stable_id = stable
    existing.crm_removed_at = None
    existing.provider = "salesforce"
    if not existing.crm_source:
        existing.crm_source = "salesforce"
    db.flush()
    return {
        "action": "updated",
        "external_id": opportunity.external_id,
        "deal_id": existing.id,
        "stable_id": existing.crm_stable_id,
    }


def _tombstone_missing(db: Session, connection: CrmConnection, seen: set[str]) -> int:
    now = datetime.utcnow()
    rows = (
        db.query(Deal)
        .filter(
            Deal.workspace_id == connection.workspace_id,
            Deal.connection_id == connection.id,
            Deal.provider == "salesforce",
            Deal.crm_removed_at.is_(None),
        )
        .all()
    )
    count = 0
    for row in rows:
        if row.crm_external_id not in seen:
            row.crm_removed_at = now
            count += 1
    return count


def _record_progress(job: Job | None, generated: int, total: int) -> None:
    if job is None:
        return
    job.result = json.dumps(
        {"generated": generated, "total": max(total, generated), "provider": "salesforce"}
    )


def sync_salesforce(
    db: Session,
    workspace_id: int,
    *,
    pipeline_id: str,
    connection_id: int | None = None,
    job: Job | None = None,
) -> dict:
    """Read every page of one Salesforce pipeline and upsert its deals.

    A page cursor is stored after each committed page. A later call with that
    cursor resumes. A completed pass stores the newest provider modification
    time and tombstones deals from this connection that the provider no longer
    returned. Manual fields recorded by ``update_deal`` are left unchanged.
    """
    client = SalesforcePipelineClient(salesforce_base_url())
    connection = ensure_salesforce_connection(db, workspace_id, pipeline_id, connection_id)
    if connection.cursor_kind == "page" and connection.cursor:
        url = connection.cursor
        seen = _load_seen(connection.seen_external_ids)
    else:
        url = client.query_url(connection.pipeline_id)
        seen = set()
        connection.seen_external_ids = "[]"
        connection.cursor_kind = "page"
        connection.cursor = url
        db.commit()
    created = updated = tombstoned = 0
    details: list[dict] = []
    reported_total = 0
    modified: list[str] = []
    for _page in range(_MAX_PAGES):
        page = client.fetch(url)
        reported_total = max(reported_total, page.total_size)
        for record in page.records:
            opportunity = parse_opportunity(record)
            outcome = _apply_opportunity(db, connection, opportunity)
            seen.add(opportunity.external_id)
            details.append(outcome)
            if outcome["action"] == "created":
                created += 1
            else:
                updated += 1
            if opportunity.modified:
                modified.append(opportunity.modified)
        connection.seen_external_ids = json.dumps(sorted(seen))
        _record_progress(job, len(seen), reported_total)
        logger.info(
            "salesforce sync page workspace_id=%s connection_id=%s records=%s done=%s",
            connection.workspace_id,
            connection.id,
            len(page.records),
            page.done,
        )
        if page.done:
            tombstoned = _tombstone_missing(db, connection, seen)
            connection.cursor = (
                max(modified) if modified else datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            )
            connection.cursor_kind = "complete"
            connection.seen_external_ids = None
            _record_progress(job, len(seen), reported_total)
            db.commit()
            break
        if not page.next_records_url:
            raise SalesforceClientError("bad_input")
        client.resolve(page.next_records_url)
        connection.cursor = page.next_records_url
        connection.cursor_kind = "page"
        url = page.next_records_url
        db.commit()
    else:
        raise SalesforceClientError("bad_input")
    return {
        "source": "salesforce",
        "synced": created + updated,
        "created": created,
        "updated": updated,
        "tombstoned": tombstoned,
        "generated": len(seen),
        "total": max(reported_total, len(seen)),
        "connection_id": connection.id,
        "pipeline_id": connection.pipeline_id,
        "cursor": connection.cursor,
        "cursor_kind": connection.cursor_kind,
        "details": details,
    }


def enqueue_salesforce_sync(
    db: Session,
    workspace_id: int,
    *,
    pipeline_id: str,
    connection_id: int | None = None,
) -> dict:
    """Queue one ``crm_sync`` job. The same queued pipeline returns the existing job."""
    salesforce_base_url()
    connection = ensure_salesforce_connection(db, workspace_id, pipeline_id, connection_id)
    payload = {
        "workspace_id": workspace_id,
        "connection_id": connection.id,
        "pipeline_id": connection.pipeline_id,
        "provider": "salesforce",
    }
    job, created = enqueue_job(
        db,
        workspace_id=workspace_id,
        kind=JobKind.CRM_SYNC.value,
        payload=payload,
        idempotency_key=job_idempotency_key(
            JobKind.CRM_SYNC.value, workspace_id, "salesforce", connection.id
        ),
        commit=True,
    )
    return {
        "source": "salesforce",
        "kind": JobKind.CRM_SYNC.value,
        "job_id": job.id,
        "status": job.status,
        "connection_id": connection.id,
        "pipeline_id": connection.pipeline_id,
        "workspace_id": workspace_id,
        "created": created,
    }


def sync_hubspot(db: Session, workspace_id: int) -> dict:
    """Labeled HubSpot example. TC-20-053 replaces this with a pipeline read on ``crm_sync``."""
    mock_deals = [
        {
            "external_id": "hs-deal-001",
            "company_name": "StartupCo (example data)",
            "contact_name": "Alice Security",
            "contact_email": "alice@startupco.io",
            "deal_value": 45000,
            "stage": "discovery",
            "close_date": "2026-07-31",
        },
    ]
    synced = []
    for deal in mock_deals:
        existing = (
            db.query(Deal)
            .filter(
                Deal.workspace_id == workspace_id,
                Deal.crm_external_id == deal["external_id"],
                or_(
                    Deal.provider == "hubspot",
                    and_(Deal.provider.is_(None), Deal.crm_source == "hubspot"),
                ),
            )
            .first()
        )
        if existing:
            existing.company_name = deal["company_name"]
            existing.deal_value_arr = parse_amount(deal["deal_value"])
            existing.stage = deal["stage"]
            existing.provider = "hubspot"
            synced.append({"action": "updated", "external_id": deal["external_id"]})
        else:
            db.add(
                Deal(
                    workspace_id=workspace_id,
                    company_name=deal["company_name"],
                    buyer_contact_name=deal["contact_name"],
                    buyer_contact_email=deal["contact_email"],
                    deal_value_arr=parse_amount(deal["deal_value"]),
                    stage=deal["stage"],
                    crm_source="hubspot",
                    provider="hubspot",
                    crm_external_id=deal["external_id"],
                )
            )
            synced.append({"action": "created", "external_id": deal["external_id"]})
    db.flush()
    return {
        "source": "hubspot",
        "synced": len(synced),
        "details": synced,
        "mock": True,
        "data_basis": "synthetic_example",
    }


def get_sync_status(db: Session, workspace_id: int) -> dict:
    def _active():
        return Deal.crm_removed_at.is_(None)

    sf_count = (
        db.query(Deal)
        .filter(Deal.workspace_id == workspace_id, Deal.crm_source == "salesforce", _active())
        .count()
    )
    hs_count = (
        db.query(Deal)
        .filter(Deal.workspace_id == workspace_id, Deal.crm_source == "hubspot", _active())
        .count()
    )
    manual = (
        db.query(Deal)
        .filter(Deal.workspace_id == workspace_id, Deal.crm_source.is_(None), _active())
        .count()
    )
    return {
        "salesforce": sf_count,
        "hubspot": hs_count,
        "manual": manual,
        "total": sf_count + hs_count + manual,
    }
