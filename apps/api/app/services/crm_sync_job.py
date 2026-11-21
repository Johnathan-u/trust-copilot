"""Persisted CRM sync job (TC-20-050).

``crm_sync`` is the one job kind for CRM pipeline sync. The payload
``provider`` is ``salesforce`` or ``hubspot``. This ticket runs Salesforce.
TC-20-053 runs HubSpot on the same kind and the same history projection.
"""

from __future__ import annotations

from app.core.job_errors import (
    BAD_INPUT,
    CONFIG_ERROR,
    NOT_FOUND,
    RetryableJobError,
    TerminalJobError,
)
from app.services.crm_connector_service import (
    ConnectionNotFound,
    PipelineMismatch,
    sync_salesforce,
)
from app.services.salesforce_pipeline_client import SalesforceClientError

CRM_SYNC_KIND = "crm_sync"
CRM_SYNC_PROVIDERS = ("salesforce", "hubspot")

_RETRYABLE = frozenset({"timeout", "rate_limited", "upstream_unavailable", "connection_error"})


def _as_job_error(exc: SalesforceClientError) -> Exception:
    if exc.code in _RETRYABLE:
        return RetryableJobError(exc.code, exc.code)
    if exc.code == "config_error":
        return TerminalJobError(CONFIG_ERROR, "Salesforce pipeline sync is not configured.")
    if exc.code == "not_found":
        return TerminalJobError(NOT_FOUND, "CRM connection is no longer available.")
    return TerminalJobError(BAD_INPUT, "Salesforce pipeline page could not be read.")


def run_crm_sync_job(job, session, payload: dict) -> None:
    """Run one CRM sync. HubSpot is reserved on this kind and is not executed here."""
    if not isinstance(payload, dict):
        raise TerminalJobError(BAD_INPUT, "CRM sync input is not valid.")
    provider = payload.get("provider")
    if provider == "hubspot":
        raise TerminalJobError(BAD_INPUT, "HubSpot sync is not available yet.")
    if provider != "salesforce":
        raise TerminalJobError(BAD_INPUT, "CRM sync provider is not supported.")
    workspace_id = payload.get("workspace_id")
    connection_id = payload.get("connection_id")
    pipeline_id = payload.get("pipeline_id")
    if (
        type(workspace_id) is not int
        or workspace_id != job.workspace_id
        or type(connection_id) is not int
        or not isinstance(pipeline_id, str)
    ):
        raise TerminalJobError(BAD_INPUT, "CRM sync input is not valid.")
    try:
        sync_salesforce(
            session,
            job.workspace_id,
            pipeline_id=pipeline_id,
            connection_id=connection_id,
            job=job,
        )
    except ConnectionNotFound as exc:
        raise TerminalJobError(NOT_FOUND, "CRM connection is no longer available.") from exc
    except PipelineMismatch as exc:
        raise TerminalJobError(BAD_INPUT, "CRM connection does not use that pipeline.") from exc
    except SalesforceClientError as exc:
        raise _as_job_error(exc) from None
