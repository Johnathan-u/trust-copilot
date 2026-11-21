"""Salesforce Opportunity query client (TC-20-050).

Reads one selected pipeline from a configured base URL using the Salesforce
REST query shape: ``totalSize``, ``done``, ``nextRecordsUrl``, and ``records``.
The base URL is the local fixture server in tests. Salesforce hostnames are
refused. No credential is read or sent.

TC-20-053 reuses the persisted ``crm_sync`` job, not this client.
"""

from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit

_API = "/services/data/v59.0"
_QUERY_PATH = f"{_API}/query"
_MAX_BODY = 1_000_000
_MAX_PAGE_RECORDS = 200
_MAX_TOTAL = 10_000
_PIPELINE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_EXTERNAL_ID = re.compile(r"^[A-Za-z0-9-]{1,255}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_SOQL = (
    "SELECT Id, Name, Amount, StageName, CloseDate, CurrencyIsoCode, "
    "Account.Name, LastModifiedDate FROM Opportunity "
    "WHERE PipelineId = '{pipeline}' ORDER BY Id"
)
_BLOCKED_HOSTS = (
    "salesforce.com",
    "force.com",
    "salesforce.mil",
    "cloudforce.com",
    "salesforce-sites.com",
    "documentforce.com",
    "forceusercontent.com",
)
_STAGES = {
    "prospect": "prospect",
    "prospecting": "prospect",
    "qualification": "prospect",
    "discovery": "discovery",
    "needs analysis": "discovery",
    "value proposition": "discovery",
    "id. decision makers": "discovery",
    "perception analysis": "discovery",
    "evaluation": "evaluation",
    "proposal/price quote": "evaluation",
    "negotiation": "negotiation",
    "negotiation/review": "negotiation",
    "closed won": "closed_won",
    "closed_won": "closed_won",
    "closed lost": "closed_lost",
    "closed_lost": "closed_lost",
}


class SalesforceClientError(Exception):
    """A pipeline read failed. ``code`` is a job error code. The message is the code only."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class OpportunityPage:
    total_size: int
    done: bool
    next_records_url: str | None
    records: list[dict]


@dataclass(frozen=True)
class SalesforceOpportunity:
    external_id: str
    company_name: str
    amount: Decimal | None
    currency: str | None
    stage: str
    close_date: date | None
    modified: str | None


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SalesforceClientError("bad_input")


_OPENER = urllib.request.build_opener(_RejectRedirects)


def _blocked_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(host == suffix or host.endswith("." + suffix) for suffix in _BLOCKED_HOSTS)


def require_base_url(raw: str) -> str:
    """Return the origin of a fixture base URL, or raise ``config_error``."""
    parts = urlsplit(raw.strip())
    host = parts.hostname or ""
    if (
        parts.scheme not in {"http", "https"}
        or not host
        or host.endswith(".")
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
        or _blocked_host(host)
    ):
        raise SalesforceClientError("config_error")
    return f"{parts.scheme}://{parts.netloc}"


def salesforce_base_url() -> str:
    """``SALESFORCE_API_BASE_URL`` at call time. Unset or a Salesforce host is ``config_error``."""
    raw = os.getenv("SALESFORCE_API_BASE_URL", "").strip()
    if not raw:
        raise SalesforceClientError("config_error")
    return require_base_url(raw)


def _validate_pipeline(pipeline_id: str) -> str:
    if not isinstance(pipeline_id, str) or not _PIPELINE.fullmatch(pipeline_id):
        raise SalesforceClientError("bad_input")
    return pipeline_id


def _amount(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, float):
        raise SalesforceClientError("bad_input")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        try:
            return Decimal(value)
        except ArithmeticError as exc:
            raise SalesforceClientError("bad_input") from exc
    raise SalesforceClientError("bad_input")


def parse_opportunity(record: object) -> SalesforceOpportunity:
    if not isinstance(record, dict):
        raise SalesforceClientError("bad_input")
    external_id = record.get("Id")
    if not isinstance(external_id, str) or not _EXTERNAL_ID.fullmatch(external_id):
        raise SalesforceClientError("bad_input")
    account = record.get("Account")
    company = ""
    if isinstance(account, dict) and isinstance(account.get("Name"), str):
        company = account["Name"].strip()
    if not company and isinstance(record.get("Name"), str):
        company = record["Name"].strip()
    if not company or len(company) > 255 or any(ord(char) < 32 for char in company):
        raise SalesforceClientError("bad_input")
    stage_raw = record.get("StageName")
    if not isinstance(stage_raw, str):
        raise SalesforceClientError("bad_input")
    stage = _STAGES.get(stage_raw.strip().casefold())
    if stage is None:
        raise SalesforceClientError("bad_input")
    amount = _amount(record.get("Amount"))
    currency = record.get("CurrencyIsoCode")
    if amount is None:
        currency_text = None
    else:
        if not isinstance(currency, str) or not _CURRENCY.fullmatch(currency):
            raise SalesforceClientError("bad_input")
        currency_text = currency
    close_raw = record.get("CloseDate")
    close = None
    if close_raw is not None:
        if not isinstance(close_raw, str) or not _DAY.fullmatch(close_raw):
            raise SalesforceClientError("bad_input")
        try:
            close = date.fromisoformat(close_raw)
        except ValueError as exc:
            raise SalesforceClientError("bad_input") from exc
    modified = record.get("LastModifiedDate")
    if modified is not None and (
        not isinstance(modified, str) or not modified or len(modified) > 40
    ):
        modified = None
    return SalesforceOpportunity(
        external_id=external_id,
        company_name=company,
        amount=amount,
        currency=currency_text,
        stage=stage,
        close_date=close,
        modified=modified,
    )


def parse_opportunity_page(payload: object) -> OpportunityPage:
    if not isinstance(payload, dict):
        raise SalesforceClientError("bad_input")
    records = payload.get("records")
    total = payload.get("totalSize")
    done = payload.get("done")
    if (
        not isinstance(records, list)
        or len(records) > _MAX_PAGE_RECORDS
        or type(total) is not int
        or not 0 <= total <= _MAX_TOTAL
        or type(done) is not bool
    ):
        raise SalesforceClientError("bad_input")
    nxt = payload.get("nextRecordsUrl")
    if done:
        nxt = None
    elif not isinstance(nxt, str) or not nxt:
        raise SalesforceClientError("bad_input")
    return OpportunityPage(total_size=total, done=done, next_records_url=nxt, records=records)


class SalesforcePipelineClient:
    """GET query pages from one configured origin. Redirects and other origins are refused."""

    def __init__(self, base_url: str):
        self.base_url = require_base_url(base_url)
        parts = urlsplit(self.base_url)
        self.scheme = parts.scheme
        self.netloc = parts.netloc

    def query_url(self, pipeline_id: str) -> str:
        pipeline = _validate_pipeline(pipeline_id)
        query = urllib.parse.urlencode({"q": _SOQL.format(pipeline=pipeline)})
        return f"{self.base_url}{_QUERY_PATH}?{query}"

    def resolve(self, url_or_cursor: str) -> str:
        if not isinstance(url_or_cursor, str) or not url_or_cursor:
            raise SalesforceClientError("bad_input")
        if url_or_cursor.startswith("/"):
            parts = urlsplit(url_or_cursor)
            if not parts.path.startswith(f"{_API}/") or parts.scheme or parts.netloc:
                raise SalesforceClientError("bad_input")
            return urlunsplit((self.scheme, self.netloc, parts.path, parts.query, ""))
        parts = urlsplit(url_or_cursor)
        host = parts.hostname or ""
        if (
            parts.scheme != self.scheme
            or parts.netloc != self.netloc
            or _blocked_host(host)
            or not parts.path.startswith(f"{_API}/")
        ):
            raise SalesforceClientError("bad_input")
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))

    def fetch(self, url_or_cursor: str) -> OpportunityPage:
        return parse_opportunity_page(self._get_json(self.resolve(url_or_cursor)))

    def _get_json(self, url: str) -> dict:
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"Accept": "application/json", "User-Agent": "TrustCopilot-crm-sync"},
        )
        try:
            with _OPENER.open(request, timeout=10) as response:
                status = getattr(response, "status", None) or response.getcode()
                raw = response.read(_MAX_BODY + 1)
        except SalesforceClientError:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise SalesforceClientError("rate_limited") from None
            if exc.code in (408, 504):
                raise SalesforceClientError("timeout") from None
            if 500 <= exc.code <= 599:
                raise SalesforceClientError("upstream_unavailable") from None
            raise SalesforceClientError("bad_input") from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise SalesforceClientError("timeout") from None
            raise SalesforceClientError("connection_error") from None
        except (TimeoutError, socket.timeout):
            raise SalesforceClientError("timeout") from None
        if status != 200 or len(raw) > _MAX_BODY:
            raise SalesforceClientError("bad_input")
        try:
            payload = json.loads(raw.decode("utf-8"), parse_float=Decimal)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SalesforceClientError("bad_input") from exc
        if not isinstance(payload, dict):
            raise SalesforceClientError("bad_input")
        return payload
