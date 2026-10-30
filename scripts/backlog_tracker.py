#!/usr/bin/env python3
"""Build and maintain the dependency-free, offline TrustCopilot backlog.

The canonical plan is immutable. The state ledger is the sole mutable source;
data.js is a reproducible projection. Validation checks evidence records, not
the truth of remote evidence or the identity of a GitHub reviewer. The existing
coordinator lease, independent review and merge gates still apply.
"""

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("docs/planning/TrustCopilot_Execution_Backlog.json")
STATE = Path("docs/planning/backlog-state.json")
DISPLAY = Path("docs/tracker/data.js")
# Changing scope requires a separately reviewed versioned migration and explicit
# scope-change history. Editing the state hash/weights cannot redefine scope v1.
SCOPE_VERSION = 1
CANONICAL_SHA256 = "2ec27987ea9b4e3e89f88d409fc817aea22550cae2f2c10f6bd6e3c23190ff5a"
TOTAL_TICKETS, TOTAL_POINTS, TOTAL_EPICS = 384, 1864, 30
STATUSES = {
    "BASELINE_RECONCILIATION",
    "EVIDENCE_RECONCILIATION",
    "IMPLEMENTATION_GAPS_IDENTIFIED",
    "IN_PROGRESS",
    "READY",
    "BLOCKED",
    "IN_REVIEW",
    "DONE",
    "REOPENED",
}
EVIDENCE_STATES = STATUSES | {"VERIFIED_ACCEPTED", "REGRESSION"}
GATE_STATUSES = {"NOT_VERIFIED", "OPEN", "BLOCKED_EXTERNAL", "BLOCKED", "PASSED"}
ACCEPTANCE_STATES = {"PENDING", "NOT_ACCEPTED", "ACCEPTED", "REVOKED"}
REQUIREMENT_STATUSES = {"NOT_VERIFIED", "PASS", "FAIL", "BLOCKED"}
CURRENT_KEYS = {
    "status",
    "evidence_state",
    "owner",
    "blockers",
    "next_action",
    "updated_at",
    "source_sha",
    "acceptance",
    "pr_links",
    "evidence_links",
    "audit",
}
ACCEPTANCE_KEYS = {
    "state",
    "assessed_by",
    "assessed_at",
    "assessed_sha",
    "assessment_evidence_urls",
    "tested_sha",
    "implemented_by",
    "independent_reviewer",
    "reviewed_at",
    "reviewed_sha",
    "review_evidence_urls",
    "criteria",
    "definition_of_done",
    "note",
}
GATE_KEYS = {"id", "title", "status", "note", "evidence_urls", "ticket_ids", "owner"}
FOLLOWUP_KEYS = {"id", "title", "parent_id", "story_points", "source_url", "source_path"}
# Scope-freeze section 8 explicitly supersedes the unchanged planning JSON.
# These four accepted rulings are a read-only projection, not an editable rules engine.
FRAMEWORK_RIGHTS_TICKETS = ["TC-21-001"] + [f"TC-21-{number:03}" for number in range(14, 23)]
LEGAL_RELEASE_TICKETS = ["TC-02-002", "TC-09-007", "TC-09-008"] + FRAMEWORK_RIGHTS_TICKETS
LEGAL_TICKET_IDS = {"TC-01-002", "TC-01-003", "TC-01-004"}
RULINGS_SOURCE_URL = (
    "https://github.com/Johnathan-u/trust-copilot/blob/"
    "b2bd1e0df5cdeb03b8d0cd240f5a161835ea621d/"
    "docs/acceptance/scope-freeze.md#8-coordinator-rulings-recorded-at-freeze"
)


class ValidationError(ValueError):
    """A malformed or unjustified state must never produce a successful build."""


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def obj(value, label):
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def keys(value, required, label, optional=()):
    obj(value, label)
    require(required <= value.keys(), f"{label} missing: {sorted(required - value.keys())}")
    require(value.keys() <= required | set(optional), f"{label} has unknown properties")


def text(value, label, nullable=False):
    if nullable and value is None:
        return
    require(isinstance(value, str) and bool(value.strip()), f"{label} must be nonempty text")


def identity(value, label, nullable=False):
    text(value, label, nullable)
    if value is not None:
        require(value == value.strip(), f"{label} must not have surrounding whitespace")


def sha(value, label, nullable=False):
    if nullable and value is None:
        return
    require(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) and value != "0" * 40,
        f"{label} must be a full lowercase 40-character commit SHA",
    )


def timestamp(value, label, nullable=False):
    if nullable and value is None:
        return None
    require(
        isinstance(value, str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value),
        f"{label} must be UTC YYYY-MM-DDTHH:MM:SSZ",
    )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValidationError(f"{label} is not a valid UTC date") from exc


def strings(value, label, nonempty=False):
    require(isinstance(value, list), f"{label} must be an array")
    require(not nonempty or bool(value), f"{label} needs at least one item")
    for item in value:
        text(item, label)
    require(len(value) == len(set(value)), f"{label} has duplicates")


def url(value, label):
    text(value, label)
    parsed = urlsplit(value)
    require(
        parsed.scheme in {"http", "https"}
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and not any(c.isspace() or ord(c) < 32 for c in value),
        f"{label} must be a public http(s) evidence URL without credentials",
    )


def urls(value, label, nonempty=False):
    strings(value, label, nonempty)
    for item in value:
        url(item, label)


def integer(value, label, minimum=0):
    require(type(value) is int and value >= minimum, f"{label} must be an integer >= {minimum}")


def unique_records(value, label):
    require(isinstance(value, list), f"{label} must be an array")
    records = {}
    for record in value:
        obj(record, label)
        text(record.get("id"), f"{label}.id")
        require(record["id"] not in records, f"{label}: duplicate id {record['id']}")
        records[record["id"]] = record
    return records


def read_json(path):
    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"{path}: duplicate JSON key {key}")
            result[key] = value
        return result

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=no_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValidationError(f"Invalid JSON number: {value}")
        ),
    )


def requirement_records(records, expected_ids, label, acceptance):
    by_id = unique_records(records, label)
    require(
        set(by_id) == set(expected_ids),
        f"{label} must cover every original requirement exactly once",
    )
    for record in records:
        keys(record, {"id", "status", "evidence_urls", "tested_sha"}, label)
        require(record["status"] in REQUIREMENT_STATUSES, f"{label}: unknown requirement status")
        verified = record["status"] != "NOT_VERIFIED"
        urls(record["evidence_urls"], label, nonempty=verified)
        sha(record["tested_sha"], label, nullable=not verified)
        if acceptance["state"] != "PENDING":
            require(
                verified,
                f"{label}: a complete assessment must disposition every original requirement",
            )
        if acceptance["state"] == "ACCEPTED":
            require(record["status"] == "PASS", f"{label}: accepted requirements must PASS")
            require(
                record["tested_sha"] == acceptance["tested_sha"],
                f"{label}: evidence must qualify the accepted tested SHA",
            )


def validate_acceptance(ticket, current, as_of):
    ticket_id = ticket["id"]
    value = current["acceptance"]
    keys(value, ACCEPTANCE_KEYS, f"{ticket_id}.acceptance")
    require(value["state"] in ACCEPTANCE_STATES, f"{ticket_id}: unknown acceptance state")
    assessed = value["state"] != "PENDING"
    accepted = value["state"] == "ACCEPTED"
    identity(value["assessed_by"], ticket_id, nullable=not assessed)
    assessed_at = timestamp(value["assessed_at"], ticket_id, nullable=not assessed)
    sha(value["assessed_sha"], ticket_id, nullable=not assessed)
    urls(value["assessment_evidence_urls"], ticket_id, nonempty=assessed)
    sha(value["tested_sha"], ticket_id, nullable=not accepted)
    identity(value["independent_reviewer"], ticket_id, nullable=not accepted)
    reviewed_at = timestamp(value["reviewed_at"], ticket_id, nullable=not accepted)
    sha(value["reviewed_sha"], ticket_id, nullable=not accepted)
    urls(value["review_evidence_urls"], ticket_id, nonempty=accepted)
    strings(value["implemented_by"], ticket_id, nonempty=accepted)
    for implementer in value["implemented_by"]:
        identity(implementer, ticket_id)
    text(value["note"], ticket_id)
    for recorded_at in (assessed_at, reviewed_at):
        require(
            recorded_at is None or recorded_at <= as_of,
            f"{ticket_id}: evidence date is after the snapshot",
        )
    if accepted:
        require(
            value["reviewed_sha"] == value["tested_sha"] == value["assessed_sha"],
            f"{ticket_id}: assessment, testing and review must qualify the same SHA",
        )
        implementers = {name.casefold().lstrip("@") for name in value["implemented_by"]}
        if current["owner"]:
            implementers.add(current["owner"].casefold().lstrip("@"))
        require(
            value["independent_reviewer"].casefold().lstrip("@") not in implementers,
            f"{ticket_id}: independent acceptance cannot be self-review",
        )
        require(not current["blockers"], f"{ticket_id}: unresolved blockers prevent acceptance")
    require(
        (current["status"] == "DONE") == accepted,
        f"{ticket_id}: DONE requires complete ACCEPTED evidence and vice versa",
    )
    requirement_records(value["criteria"], ticket["acceptance_ids"], f"{ticket_id}.criteria", value)
    requirement_records(
        value["definition_of_done"],
        [f"{ticket_id}-DOD{i + 1}" for i in range(len(ticket["definition_of_done"]))],
        f"{ticket_id}.definition_of_done",
        value,
    )


def validate_current(ticket, current, as_of):
    ticket_id = ticket["id"]
    keys(current, CURRENT_KEYS, ticket_id)
    require(current["status"] in STATUSES, f"{ticket_id}: unknown current status")
    require(current["evidence_state"] in EVIDENCE_STATES, f"{ticket_id}: unknown evidence state")
    identity(current["owner"], ticket_id, nullable=True)
    strings(current["blockers"], ticket_id)
    text(current["next_action"], ticket_id)
    require(
        timestamp(current["updated_at"], ticket_id) <= as_of,
        f"{ticket_id}: update date is after snapshot",
    )
    sha(current["source_sha"], ticket_id)
    urls(current["evidence_links"], ticket_id)
    obj(current["audit"], ticket_id)
    require(isinstance(current["pr_links"], list), f"{ticket_id}.pr_links must be an array")
    seen_prs = set()
    for pr in current["pr_links"]:
        obj(pr, ticket_id)
        require(
            {"number", "title", "url", "state", "head_sha"} <= pr.keys(),
            f"{ticket_id}: incomplete PR record",
        )
        integer(pr["number"], ticket_id, 1)
        require(pr["number"] not in seen_prs, f"{ticket_id}: duplicate PR")
        seen_prs.add(pr["number"])
        text(pr["title"], ticket_id)
        url(pr["url"], ticket_id)
        require(pr["state"] in {"open", "merged", "closed"}, f"{ticket_id}: unknown PR state")
        sha(pr["head_sha"], ticket_id)
    validate_acceptance(ticket, current, as_of)
    require(
        (current["evidence_state"] == "VERIFIED_ACCEPTED")
        == (current["status"] == "DONE" and current["acceptance"]["state"] == "ACCEPTED"),
        f"{ticket_id}: VERIFIED_ACCEPTED evidence requires complete DONE acceptance and vice versa",
    )
    require(
        current["status"] != "REOPENED" or current["evidence_state"] == "REGRESSION",
        f"{ticket_id}: reopened work must identify its evidence as REGRESSION",
    )


def validate_gates(gates, label, ticket_ids, required_ids=None):
    by_id = unique_records(gates, label)
    if required_ids is not None:
        require(set(by_id) == required_ids, f"{label} IDs must remain {sorted(required_ids)}")
    for gate in gates:
        keys(gate, GATE_KEYS, label, {"rule", "affects_points_numerator"})
        text(gate["title"], label)
        require(gate["status"] in GATE_STATUSES, f"{gate['id']}: unknown gate status")
        text(gate["note"], label)
        identity(gate["owner"], label, nullable=True)
        urls(gate["evidence_urls"], label, nonempty=gate["status"] == "PASSED")
        strings(gate["ticket_ids"], label)
        require(
            set(gate["ticket_ids"]) <= ticket_ids,
            f"{gate['id']}: unknown original ticket reference",
        )
    return by_id


def summarize(plan, state):
    assessed = sum(
        current["acceptance"]["state"] != "PENDING" for current in state["tickets"].values()
    )
    accepted_ids = {
        ticket_id
        for ticket_id, current in state["tickets"].items()
        if current["status"] == "DONE" and current["acceptance"]["state"] == "ACCEPTED"
    }
    claim_points = sum(
        ticket["story_points"] for ticket in plan["tickets"] if ticket["id"] in accepted_ids
    )
    verified = assessed == len(plan["tickets"])
    return {
        "accepted_points": claim_points if verified else None,
        "completion_percentage": round(100 * claim_points / TOTAL_POINTS, 4) if verified else None,
        "assessed_tickets": assessed,
        "total_tickets": TOTAL_TICKETS,
        "total_points": TOTAL_POINTS,
        "state_counts": dict(
            sorted(Counter(current["status"] for current in state["tickets"].values()).items())
        ),
        "accepted_claim_points": claim_points,
        "accepted_tickets": len(accepted_ids),
        "baseline_status": "VERIFIED" if verified else "PENDING",
    }


def metric_snapshot(plan, state):
    return {"scope_version": state["scope_version"], **summarize(plan, state)}


def validate_history(state, plan):
    history = state["history"]
    require(isinstance(history, list) and bool(history), "history must retain the initial snapshot")
    require(len(history) == state["revision"], "history must retain every revision")
    previous = None
    previous_at = None
    for revision, event in enumerate(history, 1):
        keys(
            event,
            {"revision", "at", "actor", "reason", "source_sha", "before", "after", "changes"},
            "history event",
        )
        require(
            type(event["revision"]) is int and event["revision"] == revision,
            "history revisions must be contiguous",
        )
        at = timestamp(event["at"], "history.at")
        require(
            previous_at is None or at >= previous_at, "history timestamps must be chronological"
        )
        identity(event["actor"], "history.actor")
        text(event["reason"], "history.reason")
        sha(event["source_sha"], "history.source_sha")
        obj(event["changes"], "history.changes")
        require(event["before"] == previous, "history must preserve the previous scope and metrics")
        after = obj(event["after"], "history.after")
        keys(after, set(metric_snapshot(plan, state)), "history.after")
        require(
            after.get("scope_version") == SCOPE_VERSION
            and after.get("total_points") == TOTAL_POINTS
            and after.get("total_tickets") == TOTAL_TICKETS,
            "history scope denominator drift",
        )
        require(
            after.get("baseline_status") in {"PENDING", "VERIFIED"},
            "history baseline status invalid",
        )
        for field in ("assessed_tickets", "accepted_tickets", "accepted_claim_points"):
            integer(after[field], f"history.{field}")
        require(
            after["accepted_tickets"] <= after["assessed_tickets"] <= TOTAL_TICKETS
            and after["accepted_tickets"] <= after["accepted_claim_points"] <= TOTAL_POINTS
            and after["accepted_claim_points"] <= 8 * after["accepted_tickets"],
            "historical acceptance cannot exceed assessed tickets or frozen original points",
        )
        counts = obj(after["state_counts"], "history.state_counts")
        require(counts.keys() <= STATUSES, "historical status is unknown")
        for count in counts.values():
            integer(count, "history.state_counts value")
        require(
            sum(counts.values()) == TOTAL_TICKETS
            and counts.get("DONE", 0) == after["accepted_tickets"],
            "historical status counts must describe the original parents exactly once",
        )
        require(
            (after["baseline_status"] == "VERIFIED")
            == (after["assessed_tickets"] == TOTAL_TICKETS),
            "historical baseline requires every original parent to be assessed",
        )
        if after["baseline_status"] == "PENDING":
            require(
                after.get("accepted_points") is None and after.get("completion_percentage") is None,
                "pending historical baseline cannot have a completion percentage",
            )
        else:
            require(
                after["accepted_points"] == after["accepted_claim_points"]
                and after["completion_percentage"]
                == round(100 * after["accepted_points"] / TOTAL_POINTS, 4),
                "historical completion must retain its recorded numerator and denominator",
            )
        previous, previous_at = after, at
    require(
        history[-1]["after"] == metric_snapshot(plan, state),
        "latest history metrics do not match the state; use the validated update command",
    )
    require(
        history[-1]["at"] == state["as_of_utc"]
        and history[-1]["source_sha"] == state["source_sha"],
        "latest history must identify the current source snapshot",
    )


def validate_state(plan, state, canonical_bytes):
    keys(
        state,
        {
            "schema_version",
            "scope_version",
            "revision",
            "as_of_utc",
            "source_sha",
            "baseline_status",
            "scope",
            "tickets",
            "release_gates",
            "operational_gates",
            "followups",
            "history",
            "audit_context",
            "pull_requests",
            "reconciliation_queue",
        },
        "state",
    )
    require(
        type(state["schema_version"]) is int and state["schema_version"] == 1,
        "unsupported state schema",
    )
    require(
        type(state["scope_version"]) is int and state["scope_version"] == SCOPE_VERSION,
        "scope change requires a reviewed, explicit version migration",
    )
    integer(state["revision"], "revision", 1)
    as_of = timestamp(state["as_of_utc"], "as_of_utc")
    require(
        as_of <= datetime.now(timezone.utc), "snapshot observation time cannot be in the future"
    )
    sha(state["source_sha"], "source_sha")
    require(
        hashlib.sha256(canonical_bytes).hexdigest() == CANONICAL_SHA256,
        "canonical source bytes changed; original scope v1 is frozen",
    )
    tickets = unique_records(plan["tickets"], "canonical tickets")
    epics = unique_records(plan["epics"], "canonical epics")
    require(
        len(tickets) == TOTAL_TICKETS
        and len(epics) == TOTAL_EPICS
        and sum(t["story_points"] for t in tickets.values()) == TOTAL_POINTS,
        "canonical original scope totals changed",
    )
    keys(
        state["scope"],
        {
            "canonical_sha256",
            "total_tickets",
            "total_points",
            "total_epics",
            "weights",
            "scope_changes",
        },
        "scope",
    )
    require(
        state["scope"]
        == {
            "canonical_sha256": CANONICAL_SHA256,
            "total_tickets": TOTAL_TICKETS,
            "total_points": TOTAL_POINTS,
            "total_epics": TOTAL_EPICS,
            "weights": {t["id"]: t["story_points"] for t in plan["tickets"]},
            "scope_changes": [],
        },
        "frozen scope IDs, weights, hash or totals drifted",
    )
    obj(state["tickets"], "tickets")
    require(
        set(state["tickets"]) == set(tickets), "state must contain exactly the original ticket IDs"
    )
    for ticket_id, ticket in tickets.items():
        require(
            ticket["epic"] in epics and set(ticket["depends_on"]) <= tickets.keys(),
            f"{ticket_id}: unknown canonical relationship",
        )
        validate_current(ticket, state["tickets"][ticket_id], as_of)
    require(
        state["baseline_status"] == summarize(plan, state)["baseline_status"],
        "baseline is complete only after every original parent is explicitly assessed",
    )
    for epic in epics.values():
        require(
            set(epic["tickets"]) == {t["id"] for t in tickets.values() if t["epic"] == epic["id"]},
            f"{epic['id']}: canonical membership mismatch",
        )
    validate_gates(
        state["release_gates"], "release_gates", set(tickets), {f"G{i}" for i in range(7)}
    )
    validate_gates(state["operational_gates"], "operational_gates", set(tickets))
    for followup in unique_records(state["followups"], "followups").values():
        keys(followup, FOLLOWUP_KEYS, "followup")
        require(
            followup["id"] not in tickets, "supplemental work cannot duplicate an original parent"
        )
        text(followup["title"], "followup.title")
        require(
            followup["parent_id"] is None or followup["parent_id"] in tickets,
            "unknown supplemental parent",
        )
        if followup["story_points"] is not None:
            integer(followup["story_points"], "supplemental story_points", 1)
        url(followup["source_url"], "followup.source_url")
        path = followup["source_path"]
        text(path, "followup.source_path")
        require(
            not Path(path).is_absolute() and ".." not in Path(path).parts and "\\" not in path,
            "supplemental source path must be repository relative",
        )
    obj(state["audit_context"], "audit_context")
    require(isinstance(state["pull_requests"], list), "pull_requests must be an array")
    require(
        isinstance(state["reconciliation_queue"], list), "reconciliation_queue must be an array"
    )
    for row in state["reconciliation_queue"]:
        require(
            isinstance(row, dict) and row.get("existing_parent_id") in tickets,
            "unknown reconciliation parent",
        )
    validate_history(state, plan)


def load(root):
    canonical_bytes = (root / SOURCE).read_bytes()
    plan, state = read_json(root / SOURCE), read_json(root / STATE)
    validate_state(plan, state, canonical_bytes)
    return plan, state, canonical_bytes


def dependency_rulings():
    return [
        {
            "id": "R1",
            "title": "Approved text requires revision and review-state prerequisites",
            "note": (
                "TC-12-004 starts after TC-12-002 and TC-12-003. These replace its three "
                "original direct prerequisites, which remain transitive through those tickets."
            ),
            "source_url": RULINGS_SOURCE_URL,
            "ticket_ids": ["TC-12-004"],
            "dependency_ids": ["TC-12-002", "TC-12-003"],
        },
        {
            "id": "R2",
            "title": "Frontend diagnostics do not depend on billing reconciliation",
            "note": "TC-26-018 drops TC-24-005 and keeps TC-26-014 and TC-07-011.",
            "source_url": RULINGS_SOURCE_URL,
            "ticket_ids": ["TC-26-018"],
            "dependency_ids": ["TC-26-014", "TC-07-011", "TC-24-005"],
        },
        {
            "id": "R3",
            "title": "Framework content rights require the supplemental owner decision",
            "note": (
                "TC-01-007 records permitted redistribution for all nine framework catalogs. "
                "It gates G0/G5 release qualification of TC-21-001 and TC-21-014 through "
                "TC-21-022; its supplemental estimate never changes original-parent points."
            ),
            "source_url": RULINGS_SOURCE_URL,
            "ticket_ids": FRAMEWORK_RIGHTS_TICKETS.copy(),
            "dependency_ids": ["TC-01-007"],
        },
        {
            "id": "R4",
            "title": "Legal prerequisites gate release for the named engineering tickets",
            "note": (
                "The named engineering tickets may start before their legal prerequisites "
                "close. Those prerequisites, including TC-01-007 for framework work, still "
                "require Owner/seller acceptance before release qualification or G0/G5 pass. "
                "Transfer deliverables TC-29-006 and TC-30-004 retain their hard prerequisites."
            ),
            "source_url": RULINGS_SOURCE_URL,
            "ticket_ids": LEGAL_RELEASE_TICKETS + ["TC-29-006", "TC-30-004"],
            "dependency_ids": ["TC-01-002", "TC-01-003", "TC-01-004", "TC-01-007"],
        },
    ]


def payload(plan, state):
    summary = summarize(plan, state)
    tickets, epics = [], []
    followups = state["followups"]
    rulings = dependency_rulings()
    for ticket in plan["tickets"]:
        record = copy.deepcopy(ticket)
        effective = list(ticket["depends_on"])
        release = []
        if ticket["id"] == "TC-12-004":
            effective = ["TC-12-002", "TC-12-003"]
        elif ticket["id"] == "TC-26-018":
            effective = ["TC-26-014", "TC-07-011"]
        if ticket["id"] in LEGAL_RELEASE_TICKETS:
            release = [dependency for dependency in effective if dependency in LEGAL_TICKET_IDS]
            effective = [
                dependency for dependency in effective if dependency not in LEGAL_TICKET_IDS
            ]
        if ticket["id"] in FRAMEWORK_RIGHTS_TICKETS:
            release.append("TC-01-007")
        record["effective_depends_on"] = effective
        record["release_gate_dependencies"] = release
        record["dependency_ruling_ids"] = [
            ruling["id"] for ruling in rulings if ticket["id"] in ruling["ticket_ids"]
        ]
        record["current"] = copy.deepcopy(state["tickets"][ticket["id"]])
        record["followups"] = [
            copy.deepcopy(f) for f in followups if f["parent_id"] == ticket["id"]
        ]
        tickets.append(record)
    for epic in plan["epics"]:
        record = copy.deepcopy(epic)
        children = [ticket for ticket in tickets if ticket["epic"] == epic["id"]]
        accepted = [ticket for ticket in children if ticket["current"]["status"] == "DONE"]
        record["rollup"] = {
            "total_tickets": len(children),
            "total_points": sum(t["story_points"] for t in children),
            "assessed_tickets": sum(
                t["current"]["acceptance"]["state"] != "PENDING" for t in children
            ),
            "accepted_tickets": len(accepted),
            "accepted_points": sum(t["story_points"] for t in accepted)
            if summary["baseline_status"] == "VERIFIED"
            else None,
            "state_counts": dict(sorted(Counter(t["current"]["status"] for t in children).items())),
        }
        epics.append(record)
    return {
        "meta": {
            "title": "TrustCopilot backlog information radiator",
            "schema_version": state["schema_version"],
            "scope_version": state["scope_version"],
            "revision": state["revision"],
            "as_of_utc": state["as_of_utc"],
            "source_sha": state["source_sha"],
            "baseline_status": state["baseline_status"],
            "metric_label": "Accepted original-parent points",
            "formula": (
                "Accepted original-parent points / 1,864; "
                "unknown until every original parent is assessed."
            ),
            "snapshot_notice": (
                "Versioned static snapshot; does not poll GitHub. "
                "Reconcile current heads and gates before acting."
            ),
        },
        "summary": summary,
        "source_metadata": {
            key: copy.deepcopy(value)
            for key, value in plan.items()
            if key not in {"tickets", "epics"}
        },
        "epics": epics,
        "tickets": tickets,
        "dependency_rulings": rulings,
        "release_gates": copy.deepcopy(state["release_gates"]),
        "operational_gates": copy.deepcopy(state["operational_gates"]),
        "history": copy.deepcopy(state["history"]),
        "followups": copy.deepcopy(followups),
        "pull_requests": copy.deepcopy(state["pull_requests"]),
        "reconciliation_queue": copy.deepcopy(state["reconciliation_queue"]),
        "audit_context": copy.deepcopy(state["audit_context"]),
        "operating": {
            "ledger_url": "https://github.com/Johnathan-u/trust-copilot/issues/85",
            "state_path": STATE.as_posix(),
            "guide_path": "docs/release/PM_BACKLOG_PROTOCOL.md",
            "source_path": SOURCE.as_posix(),
            "commands": {
                "build": "python scripts/backlog_tracker.py build",
                "check": "python scripts/backlog_tracker.py check",
                "summary": "python scripts/backlog_tracker.py summary",
                "update": (
                    "python scripts/backlog_tracker.py update "
                    f"--expected-revision {state['revision']} --actor YOUR_ID "
                    "--reason 'Evidence reconciliation' --patch /tmp/backlog-patch.json"
                ),
                "tests": (
                    "python -m unittest discover -s scripts/tests "
                    "-p 'test_backlog_tracker.py' -v"
                ),
            },
        },
    }


def display_bytes(plan, state):
    serialized = json.dumps(payload(plan, state), ensure_ascii=False, indent=2, allow_nan=False)
    for character, escaped in (
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("&", "\\u0026"),
        ("\u2028", "\\u2028"),
        ("\u2029", "\\u2029"),
    ):
        serialized = serialized.replace(character, escaped)
    return (
        "// Generated by scripts/backlog_tracker.py; edit the state ledger through update.\n"
        "window.TRUSTCOPILOT_BACKLOG = " + serialized + ";\n"
    ).encode("utf-8")


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as output:
            temporary = Path(output.name)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def writer_lock(root):
    # Lock a stable sibling inode in the OS temp directory, not the ledger inode
    # replaced by atomic_write. Crashed writers release the OS lock automatically.
    # This serializes one checkout only; cross-checkout publication still requires
    # the repository's coordinator lease and Git merge/review protocol.
    identifier = hashlib.sha256(str((root / STATE).resolve()).encode()).hexdigest()
    lock_path = Path(tempfile.gettempdir()) / f"trustcopilot-backlog-{identifier}.lock"
    with lock_path.open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            lock.write(b"0")
            lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def apply_patch(plan, state, patch, actor, reason, expected_revision):
    obj(patch, "patch")
    allowed = {
        "source_sha",
        "as_of_utc",
        "tickets",
        "release_gates",
        "operational_gates",
        "followups",
    }
    require(
        bool(patch) and patch.keys() <= allowed,
        "patch has no changes or contains immutable/unknown fields",
    )
    require(
        expected_revision == state["revision"],
        f"stale revision {expected_revision}; current revision is {state['revision']}; "
        "reread and reconcile",
    )
    identity(actor, "actor")
    text(reason, "reason")
    updated = copy.deepcopy(state)
    updated["source_sha"] = patch.get("source_sha", state["source_sha"])
    updated["as_of_utc"] = patch.get(
        "as_of_utc", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    sha(updated["source_sha"], "source_sha")
    require(
        timestamp(updated["as_of_utc"], "as_of_utc")
        >= timestamp(state["as_of_utc"], "previous as_of_utc"),
        "a new revision cannot predate the previous snapshot",
    )
    if updated["source_sha"] != state["source_sha"]:
        require("as_of_utc" in patch, "a new source SHA requires its observed as_of_utc")
    changes = {}
    for collection in ("tickets", "release_gates", "operational_gates", "followups"):
        if collection not in patch:
            continue
        entries = obj(patch[collection], f"patch.{collection}")
        existing = (
            updated["tickets"]
            if collection == "tickets"
            else {record["id"]: record for record in updated[collection]}
        )
        changes[collection] = {}
        for item_id, fields in entries.items():
            obj(fields, f"patch.{collection}.{item_id}")
            can_add = collection == "followups"
            require(item_id in existing or can_add, f"{collection}: unknown id {item_id}")
            old = copy.deepcopy(existing.get(item_id))
            permitted = (
                (CURRENT_KEYS - {"audit", "updated_at", "source_sha"})
                if collection == "tickets"
                else (FOLLOWUP_KEYS if can_add else GATE_KEYS - {"id"})
            )
            require(
                bool(fields) and fields.keys() <= permitted,
                f"{item_id}: immutable or unknown update property",
            )
            if old is None:
                require(
                    fields.get("id") == item_id,
                    f"{item_id}: new supplemental record needs matching id",
                )
                existing[item_id] = copy.deepcopy(fields)
            else:
                existing[item_id].update(copy.deepcopy(fields))
            current = existing[item_id]
            if collection == "tickets":
                current["updated_at"] = updated["as_of_utc"]
                current["source_sha"] = updated["source_sha"]
                if (
                    old["status"] == "DONE"
                    and current["status"] != "DONE"
                    and "acceptance" not in fields
                ):
                    current["acceptance"]["state"] = "REVOKED"
                if current["status"] == "DONE":
                    current["evidence_state"] = "VERIFIED_ACCEPTED"
                elif old["status"] == "DONE" or current["status"] == "REOPENED":
                    current["evidence_state"] = "REGRESSION"
            changes[collection][item_id] = {
                key: {"before": old.get(key) if old else None, "after": copy.deepcopy(value)}
                for key, value in current.items()
                if old is None or old.get(key) != value
            }
        if collection != "tickets":
            updated[collection] = list(existing.values())
    updated["revision"] += 1
    updated["baseline_status"] = summarize(plan, updated)["baseline_status"]
    updated["history"].append(
        {
            "revision": updated["revision"],
            "at": updated["as_of_utc"],
            "actor": actor,
            "reason": reason,
            "source_sha": updated["source_sha"],
            "before": metric_snapshot(plan, state),
            "after": metric_snapshot(plan, updated),
            "changes": changes,
        }
    )
    return updated


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=ROOT, help="Repository root (default: script's repository)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "check", "summary"):
        subparsers.add_parser(command)
    update = subparsers.add_parser(
        "update", help="Validate, record history and regenerate the browser snapshot"
    )
    update.add_argument("--expected-revision", required=True, type=int)
    update.add_argument("--actor", required=True)
    update.add_argument("--reason", required=True)
    update.add_argument("--patch", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        with writer_lock(root):
            plan, state, canonical_bytes = load(root)
            if args.command == "summary":
                report = {
                    "revision": state["revision"],
                    "scope_version": state["scope_version"],
                    "source_sha": state["source_sha"],
                    "as_of_utc": state["as_of_utc"],
                    "metric_label": "Accepted original-parent points",
                    **summarize(plan, state),
                }
                print(json.dumps(report, indent=2))
                return 0
            if args.command == "update":
                state = apply_patch(
                    plan,
                    state,
                    read_json(args.patch),
                    args.actor,
                    args.reason,
                    args.expected_revision,
                )
                validate_state(plan, state, canonical_bytes)
            generated = display_bytes(plan, state)
            if args.command == "check":
                require((root / DISPLAY).is_file(), f"{DISPLAY} is missing; run build")
                require(
                    (root / DISPLAY).read_bytes() == generated,
                    f"{DISPLAY} is stale or edited; run build and commit the result",
                )
                print(
                    f"Backlog valid: revision {state['revision']}, "
                    "384 original tickets, 1,864 points; generated snapshot matches."
                )
                return 0
            if args.command == "update":
                # State is authoritative. An interruption between these two atomic
                # replacements is detected by check and repaired by build.
                atomic_write(
                    root / STATE,
                    (
                        json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
                    ).encode("utf-8"),
                )
            atomic_write(root / DISPLAY, generated)
            print(
                f"Built {DISPLAY} from state revision {state['revision']} "
                f"(baseline {state['baseline_status']})."
            )
            return 0
    except (ValidationError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Backlog validation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
