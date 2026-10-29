"""Demo proof package and evidence-backed demonstration summaries.

Everything produced from SAMPLE_QUESTIONNAIRE is synthetic example data.
The answers and confidence values are hardcoded illustrations, not output
from a real workspace, a real audit, or a verified deployment. Those outputs
carry data_basis and disclaimer fields so they cannot be shown as real.

Proof summary metrics are counts of rows stored for the caller's workspace.
Where a count cannot be read, the value is null and the state is unavailable.
Customers, revenue and traffic are unsupported. Nothing here is commercial
traction.

Schema version of the proof summary is "1". Legacy package keys are unchanged.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.demo_proof_summary import DemoProofSummary
from app.models.document import Document
from app.models.evidence_gap import GAP_STATUS_RESOLVED, EvidenceGap
from app.models.evidence_item import EvidenceItem
from app.models.export_record import ExportRecord
from app.models.questionnaire import Question, Questionnaire
from app.models.user import User

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1"
SYNTHETIC_DATA_BASIS = "synthetic_example"
SYNTHETIC_DISCLAIMER = (
    "Example data for demonstration only. Answers and confidence values are "
    "hardcoded illustrations, not results from a real customer, audit, or deployment."
)
TRACTION_REASON = (
    "This demonstration summary is not commercial traction. Stored counts are "
    "workspace records, not customers, revenue, or usage claims. Synthetic "
    "placeholders are excluded from these counts."
)

# name, collector, source table, denominator metric name
METRIC_SPEC = (
    ("questionnaires_stored", "questionnaires", "questionnaires", None),
    ("questions_stored", "questions", "questions", None),
    ("answers_stored", "answers", "answers", None),
    ("answers_approved", "answers", "answers", "answers_stored"),
    ("documents_stored", "documents", "documents", None),
    ("documents_indexed", "documents", "documents", "documents_stored"),
    ("evidence_items_stored", "evidence_items", "evidence_items", None),
    ("evidence_items_approved", "evidence_items", "evidence_items", "evidence_items_stored"),
    ("exports_stored", "exports", "export_records", None),
    ("exports_completed", "exports", "export_records", "exports_stored"),
    ("evidence_gaps_stored", "evidence_gaps", "evidence_gaps", None),
)

UNSUPPORTED_FACTS = (
    ("customers", "No customer register is stored. This summary does not infer customers."),
    ("revenue", "No revenue evidence is stored. This summary does not infer revenue."),
    ("traffic", "No traffic evidence is stored. This summary does not infer traffic."),
    (
        "commercial_usage",
        "Workspace activity counts are not a commercial usage claim.",
    ),
)


class WindowError(ValueError):
    """The caller sent a data window this summary cannot interpret."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field
        self.message = message


class SummaryUnreadable(Exception):
    """A stored snapshot exists but its JSON cannot be read. Do not replace it."""


SAMPLE_QUESTIONNAIRE = {
    "title": "Sample SOC 2 Security Questionnaire",
    "framework": "SOC 2 Type II",
    "sections": [
        {
            "name": "Access Control",
            "questions": [
                {
                    "text": "How do you manage user access to production systems?",
                    "answer": "Access to production systems is managed through role-based access control (RBAC) with three tiers: admin, editor, and reviewer. Each role has explicitly defined permissions enforced at the API layer. All access changes are logged in the system audit trail. MFA is available and can be enforced at the workspace level.",
                    "confidence": 92,
                    "evidence": "RBAC implementation in auth_deps.py; UserMfa model; AuditEvent logging",
                },
                {
                    "text": "Do you enforce multi-factor authentication?",
                    "answer": "Yes. We support TOTP-based multi-factor authentication compatible with standard authenticator apps. MFA can be enforced at the workspace level by administrators through the mfa_required workspace setting. Recovery codes are generated during MFA setup. MFA login tokens expire after 5 minutes.",
                    "confidence": 95,
                    "evidence": "UserMfa model with TOTP; MfaLoginToken with expiry; Workspace.mfa_required flag",
                },
                {
                    "text": "How do you handle user offboarding?",
                    "answer": "When a user is removed from a workspace, their workspace membership is deleted and all active sessions are invalidated. Suspended users receive a 403 response on any API request. Audit logs record all membership changes including removals.",
                    "confidence": 88,
                    "evidence": "WorkspaceMember suspension; session invalidation in auth_deps.py",
                },
            ],
        },
        {
            "name": "Data Protection",
            "questions": [
                {
                    "text": "Is customer data encrypted at rest?",
                    "answer": "Yes. All data at rest is encrypted using AES-256 encryption. Database volumes use full-disk encryption provided by DigitalOcean managed databases. Object storage (S3-compatible) uses server-side encryption with managed keys.",
                    "confidence": 94,
                    "evidence": "DigitalOcean managed database encryption; S3 server-side encryption configuration",
                },
                {
                    "text": "Is data encrypted in transit?",
                    "answer": "Yes. All data in transit uses TLS 1.2 or higher. The application is served behind Caddy which provides automatic HTTPS with Let's Encrypt certificates. All API endpoints reject non-HTTPS connections in production.",
                    "confidence": 96,
                    "evidence": "Caddy TLS configuration; HTTPS enforcement in deployment",
                },
                {
                    "text": "How do you ensure data isolation between tenants?",
                    "answer": "Workspace-level tenant isolation is enforced at the application layer. Every database query is scoped to the authenticated user's workspace_id. Storage paths include workspace identifiers. Vector search is filtered by workspace_id. Background jobs are workspace-scoped.",
                    "confidence": 97,
                    "evidence": "Workspace scoping in all API routes; test_tenant_isolation.py; auth_deps.py workspace filtering",
                },
            ],
        },
        {
            "name": "Logging & Monitoring",
            "questions": [
                {
                    "text": "Do you maintain audit logs of system activity?",
                    "answer": "Yes. All significant actions are recorded in a comprehensive audit log including: authentication events, workspace changes, document operations, questionnaire processing, answer generation, export operations, and admin actions. Logs include timestamps, user identity, action type, and affected resources. Audit events are accessible to workspace administrators via the API.",
                    "confidence": 95,
                    "evidence": "AuditEvent model; audit routes; persist_audit calls throughout codebase",
                },
                {
                    "text": "How do you monitor for security incidents?",
                    "answer": "We use Sentry for real-time error monitoring and alerting. Application metrics are exposed via a Prometheus-compatible /metrics endpoint tracking request counts, latency, and error rates. Suspicious authentication patterns (brute force, credential stuffing) are detected by rate limiting and logged as security events.",
                    "confidence": 85,
                    "evidence": "Sentry integration in main.py; metrics endpoint; rate_limit.py threat detection",
                },
            ],
        },
        {
            "name": "Incident Response",
            "questions": [
                {
                    "text": "Do you have an incident response plan?",
                    "answer": "Yes. Our incident response process includes detection through application monitoring, classification by severity, containment and investigation, resolution and recovery, and post-incident documentation. For security incidents affecting customer data, we notify affected customers within 72 hours consistent with GDPR requirements.",
                    "confidence": 80,
                    "evidence": "Monitoring infrastructure; notification service for alerts",
                },
                {
                    "text": "How do you handle vulnerability management?",
                    "answer": "We employ automated dependency scanning, regular security reviews, and infrastructure-level patching. Critical vulnerabilities are prioritized for immediate remediation. We maintain a responsible disclosure policy for external researchers.",
                    "confidence": 78,
                    "evidence": "Dependency management; CI pipeline; security review process",
                },
            ],
        },
        {
            "name": "Business Continuity",
            "questions": [
                {
                    "text": "What is your backup and recovery strategy?",
                    "answer": "Database backups are automated daily by the managed database service with point-in-time recovery available for 7 days. Backups are encrypted and stored in a separate geographic location. Object storage uses built-in redundancy with automatic replication. Backup restoration procedures are documented.",
                    "confidence": 90,
                    "evidence": "DigitalOcean managed database backups; S3 replication",
                },
            ],
        },
    ],
}


def _synthetic_fields() -> dict:
    return {
        "origin": "synthetic",
        "basis": "not_measured",
        "measured": False,
        "estimated": False,
        "commercial_traction": False,
        "data_basis": SYNTHETIC_DATA_BASIS,
        "data_window": _empty_window(
            applicable=False,
            reason="Synthetic placeholder has no observation window.",
        ),
        "disclaimer": SYNTHETIC_DISCLAIMER,
    }


def generate_demo_package(
    db: Session,
    workspace_id: int,
    user_id: int | None = None,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    persist: bool = False,
) -> dict:
    """Return the legacy package plus the proof summary.

    Sample blocks stay so existing clients keep their keys. They are labeled
    synthetic and are not inputs to the proof summary. persist=True stores a
    snapshot for this workspace only. The default reads and does not write.
    """
    questionnaire = _build_sample_questionnaire()
    coverage = _build_coverage_report(questionnaire)
    gaps = _build_gap_list(questionnaire)
    walkthrough = _build_walkthrough()
    proof = build_proof_summary(
        db,
        workspace_id,
        user_id=user_id,
        window_start=window_start,
        window_end=window_end,
        persist=persist,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(datetime.now(timezone.utc)),
        "workspace_id": workspace_id,
        "commercial_traction": False,
        "sample_data_origin": "synthetic",
        "data_basis": SYNTHETIC_DATA_BASIS,
        "disclaimer": SYNTHETIC_DISCLAIMER,
        "sample_questionnaire": questionnaire,
        "coverage_report": coverage,
        "gap_list": gaps,
        "walkthrough": walkthrough,
        "live_stats": _live_stats_from_summary(proof),
        "proof_summary": proof,
    }


def build_proof_summary(
    db: Session,
    workspace_id: int,
    user_id: int | None = None,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    persist: bool = False,
) -> dict:
    """Build the evidence-backed summary for this workspace and window.

    persist=True stores a snapshot for this workspace. Otherwise an existing
    snapshot with the same evidence hash is returned, and a new result is not
    written.
    """
    window = (window_start, window_end)
    collected = {}
    unavailable = []
    for name, fn in COLLECTORS.items():
        result = _invoke_collector(db, name, fn, workspace_id, window)
        collected[name] = result
        if result.get("unavailable"):
            unavailable.append(name)

    raw_counts = {}
    foreign = []
    for name, result in collected.items():
        if result.get("unavailable"):
            continue
        raw_counts.update(result.get("counts") or {})
        foreign.extend(result.get("failures") or [])

    observed = _observed_bounds(raw_counts)
    if window_start is None and window_end is None:
        if observed[0] is None:
            data_window = _empty_window(
                applicable=True,
                reason="No stored records. Nothing was backfilled.",
            )
        else:
            data_window = _window_dict(
                observed[0],
                observed[1],
                applicable=True,
                reason="Span of stored records included in this summary.",
                observed_start=observed[0],
                observed_end=observed[1],
            )
    else:
        data_window = _window_dict(
            window_start,
            window_end,
            applicable=True,
            reason="Caller-requested window. Records outside it are excluded.",
            observed_start=observed[0],
            observed_end=observed[1],
        )

    any_positive = any((item.get("value") or 0) > 0 for item in raw_counts.values())
    metrics = []
    for metric_name, collector, source, denominator_name in METRIC_SPEC:
        if collector in unavailable:
            metrics.append(_unavailable_metric(metric_name, source, data_window))
            continue
        raw = raw_counts.get(metric_name) or {
            "value": 0,
            "numerator": 0,
            "denominator": None,
            "freshness": None,
            "exclusions": _empty_exclusions(),
        }
        value = int(raw["value"])
        if value == 0 and not any_positive:
            state = "no_data"
        else:
            state = "measured"
        denominator = raw.get("denominator")
        if denominator_name is not None:
            denom_raw = raw_counts.get(denominator_name)
            denominator = None if denom_raw is None else int(denom_raw["value"])
        metrics.append(
            {
                "name": metric_name,
                "value": value,
                "unit": "count",
                "source": source,
                "origin": "real",
                "basis": "measured",
                "measured": True,
                "estimated": False,
                "data_window": data_window,
                "numerator": int(raw["numerator"]) if raw.get("numerator") is not None else value,
                "denominator": denominator,
                "currency": None,
                "freshness": _iso(raw.get("freshness")),
                "exclusions": raw.get("exclusions") or _empty_exclusions(),
                "commercial_traction": False,
                "state": state,
            }
        )

    partial = _partial_failures(foreign, unavailable)
    if unavailable or foreign:
        status = "partial"
    elif not any_positive:
        status = "no_data"
    else:
        status = "complete"

    body = {
        "schema_version": SCHEMA_VERSION,
        "workspace_id": workspace_id,
        "status": status,
        "commercial_traction": False,
        "commercial_traction_reason": TRACTION_REASON,
        "data_window": data_window,
        "metrics": metrics,
        "synthetic_placeholders": _synthetic_placeholders(),
        "unsupported": _unsupported(data_window),
        "partial_failures": partial,
    }
    digest = _body_digest(body)
    if persist:
        return _persist_summary(db, workspace_id, user_id, body, digest)
    existing = _find_snapshot(db, workspace_id, digest)
    if existing is not None:
        return existing
    return {
        **body,
        "generated_at": None,
        "content_hash": digest,
        "idempotency_key": digest,
        "summary_id": None,
        "persisted": False,
    }


def load_summary(db: Session, workspace_id: int, summary_id: int) -> dict:
    """Return one persisted snapshot for this workspace, or raise if unreadable."""
    row = (
        db.query(DemoProofSummary)
        .filter(
            DemoProofSummary.id == summary_id,
            DemoProofSummary.workspace_id == workspace_id,
        )
        .one_or_none()
    )
    if row is None:
        return None
    try:
        data = json.loads(row.summary_json)
    except json.JSONDecodeError as exc:
        logger.warning("demo proof summary %s is not valid JSON", row.id)
        raise SummaryUnreadable() from exc
    if not isinstance(data, dict):
        raise SummaryUnreadable()
    return data


def parse_window(
    window_start: str | None,
    window_end: str | None,
) -> tuple[datetime | None, datetime | None]:
    """Parse an explicit UTC window. Both bounds are required together."""
    start_blank = window_start is None or window_start.strip() == ""
    end_blank = window_end is None or window_end.strip() == ""
    if start_blank and end_blank:
        return None, None
    if start_blank or end_blank:
        missing = "window_start" if start_blank else "window_end"
        raise WindowError(
            missing,
            "window_start and window_end must both be set, or both omitted.",
        )
    start = _parse_bound(window_start, "window_start")
    end = _parse_bound(window_end, "window_end")
    if end < start:
        raise WindowError("window_end", "window_end must be on or after window_start.")
    return start, end


def _parse_bound(value: str, field: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise WindowError(
            field,
            "Use an ISO-8601 timestamp with a numeric UTC offset.",
        ) from exc
    if parsed.tzinfo is None:
        raise WindowError(field, "Timestamp must include a numeric UTC offset.")
    return parsed.astimezone(timezone.utc)


def _build_sample_questionnaire() -> dict:
    questions = []
    for section in SAMPLE_QUESTIONNAIRE["sections"]:
        for q in section["questions"]:
            questions.append(
                {
                    "section": section["name"],
                    "question": q["text"],
                    "answer": q["answer"],
                    "confidence": q["confidence"],
                    "evidence_sources": q["evidence"],
                    "confidence_basis": "illustrative hardcoded values, not model output",
                    "evidence_sources_are_real": False,
                    "citation_status": "not_a_source_locator",
                    **_synthetic_fields(),
                }
            )
    return {
        "title": SAMPLE_QUESTIONNAIRE["title"],
        "framework": SAMPLE_QUESTIONNAIRE["framework"],
        "total_questions": len(questions),
        "questions": questions,
        "confidence_basis": "illustrative hardcoded values, not model output",
        **_synthetic_fields(),
    }


def _build_coverage_report(questionnaire: dict) -> dict:
    questions = questionnaire["questions"]
    total = len(questions)
    answered = sum(1 for q in questions if q["answer"])
    high_conf = sum(1 for q in questions if q["confidence"] >= 90)
    med_conf = sum(1 for q in questions if 70 <= q["confidence"] < 90)
    low_conf = sum(1 for q in questions if q["confidence"] < 70)
    avg_conf = sum(q["confidence"] for q in questions) / total if total else 0

    sections = {}
    for q in questions:
        sec = q["section"]
        if sec not in sections:
            sections[sec] = {"total": 0, "avg_confidence": 0, "confidences": []}
        sections[sec]["total"] += 1
        sections[sec]["confidences"].append(q["confidence"])

    section_summary = []
    for name, data in sections.items():
        avg = sum(data["confidences"]) / len(data["confidences"]) if data["confidences"] else 0
        section_summary.append(
            {
                "section": name,
                "questions": data["total"],
                "avg_confidence": round(avg, 1),
                **_synthetic_fields(),
            }
        )

    return {
        "total_questions": total,
        "answered": answered,
        "coverage_pct": round(answered / total * 100, 1) if total else 0,
        "avg_confidence": round(avg_conf, 1),
        "high_confidence": high_conf,
        "medium_confidence": med_conf,
        "low_confidence": low_conf,
        "by_section": section_summary,
        **_synthetic_fields(),
    }


def _build_gap_list(questionnaire: dict) -> dict:
    gaps = []
    for q in questionnaire["questions"]:
        if q["confidence"] < 85:
            gaps.append(
                {
                    "section": q["section"],
                    "question": q["question"],
                    "confidence": q["confidence"],
                    "recommendation": _gap_recommendation(q["section"], q["confidence"]),
                    **_synthetic_fields(),
                }
            )
    return {
        "total_gaps": len(gaps),
        "gaps": gaps,
        **_synthetic_fields(),
    }


def _gap_recommendation(section: str, confidence: int) -> str:
    if confidence < 70:
        return f"Synthetic placeholder only. This is not a measured gap for {section}."
    return f"Synthetic placeholder only. This is not a measured gap for {section}."


def _build_walkthrough() -> dict:
    return {
        "steps": [
            {
                "step": 1,
                "title": "Upload Evidence Documents",
                "description": (
                    "Upload compliance documents to the Documents module. "
                    "Indexing depends on the pipeline completing for that file."
                ),
            },
            {
                "step": 2,
                "title": "Upload the Questionnaire",
                "description": (
                    "Upload a questionnaire file the product can parse. "
                    "Extraction depends on the file being a supported format."
                ),
            },
            {
                "step": 3,
                "title": "Generate AI Answers with Citations",
                "description": (
                    "Draft answers are generated from retrieved workspace evidence. "
                    "A confidence figure is a heuristic unless a separate calibration "
                    "result says otherwise."
                ),
            },
            {
                "step": 4,
                "title": "Review and Approve",
                "description": (
                    "Review generated answers before they are treated as approved. "
                    "Approval is a stored review state, not a certification."
                ),
            },
            {
                "step": 5,
                "title": "Export and Send",
                "description": (
                    "Export writes a file from approved content. "
                    "A stored export record is not proof the file was delivered."
                ),
            },
        ],
        **_synthetic_fields(),
    }


def _live_stats_from_summary(summary: dict) -> dict:
    by_name = {metric["name"]: metric for metric in summary["metrics"]}

    def _value(name: str):
        metric = by_name[name]
        if metric["state"] == "unavailable":
            return None
        return metric["value"]

    return {
        "questionnaires_processed": _value("questionnaires_stored"),
        "questions_answered": _value("questions_stored"),
        "ai_answers_generated": _value("answers_stored"),
        "evidence_gaps_identified": _value("evidence_gaps_stored"),
        "origin": "real",
        "basis": "measured",
        "measured": True,
        "estimated": False,
        "commercial_traction": False,
        "data_window": summary["data_window"],
        "state": summary["status"],
        "schema_version": SCHEMA_VERSION,
        "legacy_field_notes": {
            "questions_answered": (
                "Counts stored questions in the data window, not approved answers. "
                "Not commercial traction."
            ),
        },
        "agrees_with": "proof_summary.metrics",
    }


def _synthetic_placeholders() -> list[dict]:
    names = (
        "sample_questionnaire",
        "sample_coverage_report",
        "sample_gap_list",
        "sample_walkthrough",
    )
    placeholders = []
    for name in names:
        placeholders.append(
            {
                "name": name,
                "value": None,
                "unit": None,
                "origin": "synthetic",
                "basis": "not_measured",
                "measured": False,
                "estimated": False,
                "commercial_traction": False,
                "state": "synthetic_placeholder",
                "data_window": _empty_window(
                    applicable=False,
                    reason="Synthetic placeholder has no observation window.",
                ),
                "disclaimer": SYNTHETIC_DISCLAIMER,
            }
        )
    return placeholders


def _unsupported(data_window: dict) -> list[dict]:
    rows = []
    for name, reason in UNSUPPORTED_FACTS:
        rows.append(
            {
                "name": name,
                "value": None,
                "unit": None,
                "source": None,
                "origin": None,
                "basis": None,
                "measured": False,
                "estimated": False,
                "data_window": data_window,
                "numerator": None,
                "denominator": None,
                "currency": None,
                "freshness": None,
                "commercial_traction": False,
                "state": "unsupported",
                "reason": reason,
            }
        )
    return rows


def _unavailable_metric(name: str, source: str, data_window: dict) -> dict:
    return {
        "name": name,
        "value": None,
        "unit": "count",
        "source": source,
        "origin": None,
        "basis": None,
        "measured": False,
        "estimated": False,
        "data_window": data_window,
        "numerator": None,
        "denominator": None,
        "currency": None,
        "freshness": None,
        "exclusions": _empty_exclusions(),
        "commercial_traction": False,
        "state": "unavailable",
    }


def _empty_exclusions() -> dict:
    return {
        "deleted": 0,
        "outside_window": 0,
        "missing_timestamp": 0,
        "foreign_reference": 0,
    }


def _empty_window(*, applicable: bool, reason: str) -> dict:
    return _window_dict(
        None,
        None,
        applicable=applicable,
        reason=reason,
        observed_start=None,
        observed_end=None,
    )


def _window_dict(
    start: datetime | None,
    end: datetime | None,
    *,
    applicable: bool,
    reason: str,
    observed_start: datetime | None = None,
    observed_end: datetime | None = None,
) -> dict:
    return {
        "start": _iso(start),
        "end": _iso(end),
        "timezone": "UTC",
        "applicable": applicable,
        "reason": reason,
        "observed_start": _iso(observed_start),
        "observed_end": _iso(observed_end),
    }


def _observed_bounds(raw_counts: dict) -> tuple[datetime | None, datetime | None]:
    earliest = [
        item["earliest"] for item in raw_counts.values() if item.get("earliest") is not None
    ]
    latest = [
        item["freshness"] for item in raw_counts.values() if item.get("freshness") is not None
    ]
    if not earliest or not latest:
        return None, None
    return min(earliest), max(latest)


def _partial_failures(foreign: list[dict], unavailable: list[str]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for item in foreign:
        grouped.setdefault(item["source"], []).append(item)
    rows = []
    for source in sorted(grouped):
        records = sorted(grouped[source], key=lambda row: (row["reason"], row["record_id"]))
        reasons: dict[str, int] = {}
        for record in records:
            reasons[record["reason"]] = reasons.get(record["reason"], 0) + 1
        count = len(records)
        rows.append(
            {
                "code": "foreign_reference_rejected",
                "source": source,
                "retryable": False,
                "count": count,
                "reasons": reasons,
                "record_ids": [record["record_id"] for record in records],
                "message": (
                    f"{count} {source} record(s) reference an object that is missing, "
                    "deleted, or outside this workspace. They are excluded from the proof count."
                ),
            }
        )
    for source in sorted(unavailable):
        rows.append(
            {
                "code": "source_unavailable",
                "source": source,
                "retryable": True,
                "count": None,
                "message": f"{source} could not be read. This count is unavailable, not zero.",
            }
        )
    rows.sort(key=lambda row: (row["code"], row["source"]))
    return rows


def _body_digest(body: dict) -> str:
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _persist_summary(
    db: Session, workspace_id: int, user_id: int | None, body: dict, digest: str
) -> dict:
    existing = _find_snapshot(db, workspace_id, digest)
    if existing is not None:
        return existing
    actor = _actor_id(db, user_id)
    window = body["data_window"]
    row = DemoProofSummary(
        workspace_id=workspace_id,
        schema_version=SCHEMA_VERSION,
        idempotency_key=digest,
        content_hash=digest,
        status=body["status"],
        window_start=_from_iso(window.get("start")),
        window_end=_from_iso(window.get("end")),
        timezone="UTC",
        summary_json="{}",
        created_by_user_id=actor,
    )
    payload = {
        **body,
        "generated_at": _iso(datetime.now(timezone.utc)),
        "content_hash": digest,
        "idempotency_key": digest,
        "summary_id": None,
    }
    try:
        db.add(row)
        db.flush()
        payload["summary_id"] = row.id
        row.summary_json = json.dumps(payload, sort_keys=True)
        db.commit()
    except IntegrityError:
        db.rollback()
        raced = _find_snapshot(db, workspace_id, digest)
        if raced is None:
            raise
        return raced
    return payload


def _find_snapshot(db: Session, workspace_id: int, digest: str) -> dict | None:
    row = (
        db.query(DemoProofSummary)
        .filter(
            DemoProofSummary.workspace_id == workspace_id,
            DemoProofSummary.idempotency_key == digest,
        )
        .one_or_none()
    )
    if row is None:
        return None
    try:
        data = json.loads(row.summary_json)
    except json.JSONDecodeError as exc:
        logger.warning("demo proof snapshot for workspace %s is not valid JSON", workspace_id)
        raise SummaryUnreadable() from exc
    if not isinstance(data, dict):
        raise SummaryUnreadable()
    if not data.get("summary_id"):
        # The winning transaction had not stored the id. This request lost the race
        # before the winner committed a readable snapshot. Caller retries the lookup
        # only when summary_id is present.
        return None
    return data


def _actor_id(db: Session, user_id: int | None) -> int | None:
    if user_id is None:
        return None
    found = db.query(User.id).filter(User.id == user_id).first()
    if found is None:
        return None
    return user_id


def _invoke_collector(db: Session, name: str, fn, workspace_id: int, window) -> dict:
    nested = db.begin_nested()
    try:
        result = fn(db, workspace_id, window)
        nested.commit()
        return result
    except Exception:
        logger.exception("demo proof collector %s failed", name)
        nested.rollback()
        return {"unavailable": True, "counts": {}, "failures": []}


def _collect_questionnaires(db: Session, workspace_id: int, window) -> dict:
    rows = db.query(Questionnaire).filter(Questionnaire.workspace_id == workspace_id).all()
    included, exclusions = _split_timed(rows, window, deleted=True)
    return _count_result(
        "questionnaires_stored",
        included,
        exclusions,
        numerator=len(included),
        denominator=None,
    )


def _collect_questions(db: Session, workspace_id: int, window) -> dict:
    rows = (
        db.query(Question)
        .join(Questionnaire, Question.questionnaire_id == Questionnaire.id)
        .filter(
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_(None),
        )
        .all()
    )
    included = []
    exclusions = _empty_exclusions()
    for row in rows:
        parent = db.get(Questionnaire, row.questionnaire_id)
        parent_slot = _time_slot(parent, window) if parent is not None else "missing_timestamp"
        if parent_slot != "included":
            exclusions[parent_slot] += 1
            continue
        slot = _time_slot(row, window)
        if slot != "included":
            exclusions[slot] += 1
            continue
        included.append(row)
    return _count_result(
        "questions_stored",
        included,
        exclusions,
        numerator=len(included),
        denominator=None,
    )


def _collect_answers(db: Session, workspace_id: int, window) -> dict:
    rows = (
        db.query(Answer)
        .join(Question, Answer.question_id == Question.id)
        .join(Questionnaire, Question.questionnaire_id == Questionnaire.id)
        .filter(
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_(None),
        )
        .all()
    )
    included = []
    exclusions = _empty_exclusions()
    for row in rows:
        question = db.get(Question, row.question_id)
        parent = db.get(Questionnaire, question.questionnaire_id) if question is not None else None
        parent_slot = _time_slot(parent, window) if parent is not None else "missing_timestamp"
        if parent_slot != "included":
            exclusions[parent_slot] += 1
            continue
        slot = _time_slot(row, window)
        if slot != "included":
            exclusions[slot] += 1
            continue
        included.append(row)
    approved = [row for row in included if row.status == "approved"]
    stored = _count_payload(included, exclusions, numerator=len(included), denominator=None)
    approved_payload = _count_payload(
        approved,
        exclusions,
        numerator=len(approved),
        denominator=len(included),
    )
    return {
        "unavailable": False,
        "counts": {
            "answers_stored": stored,
            "answers_approved": approved_payload,
        },
        "failures": [],
    }


def _collect_documents(db: Session, workspace_id: int, window) -> dict:
    rows = db.query(Document).filter(Document.workspace_id == workspace_id).all()
    included, exclusions = _split_timed(rows, window, deleted=True)
    indexed = [row for row in included if row.status == "indexed"]
    stored = _count_payload(included, exclusions, numerator=len(included), denominator=None)
    indexed_payload = _count_payload(
        indexed,
        exclusions,
        numerator=len(indexed),
        denominator=len(included),
    )
    return {
        "unavailable": False,
        "counts": {
            "documents_stored": stored,
            "documents_indexed": indexed_payload,
        },
        "failures": [],
    }


def _collect_evidence(db: Session, workspace_id: int, window) -> dict:
    rows = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == workspace_id).all()
    return _collect_referenced(
        db,
        workspace_id,
        window,
        rows,
        source="evidence_items",
        stored_name="evidence_items_stored",
        approved_name="evidence_items_approved",
        approved_attr="approval_status",
        approved_value="approved",
        ref_problem=_evidence_problem,
    )


def _collect_exports(db: Session, workspace_id: int, window) -> dict:
    rows = db.query(ExportRecord).filter(ExportRecord.workspace_id == workspace_id).all()
    included = []
    exclusions = _empty_exclusions()
    failures = []
    for row in rows:
        problem = _questionnaire_problem(db, workspace_id, row.questionnaire_id)
        if problem is not None:
            exclusions["foreign_reference"] += 1
            failures.append(
                {
                    "source": "exports",
                    "reason": problem,
                    "record_id": row.id,
                }
            )
            continue
        slot = _time_slot(row, window)
        if slot != "included":
            exclusions[slot] += 1
            continue
        included.append(row)
    completed = [row for row in included if row.status == "completed"]
    return {
        "unavailable": False,
        "counts": {
            "exports_stored": _count_payload(
                included, exclusions, numerator=len(included), denominator=None
            ),
            "exports_completed": _count_payload(
                completed, exclusions, numerator=len(completed), denominator=len(included)
            ),
        },
        "failures": failures,
    }


def _collect_gaps(db: Session, workspace_id: int, window) -> dict:
    rows = db.query(EvidenceGap).filter(EvidenceGap.workspace_id == workspace_id).all()
    included = []
    # TC-02-BUG-018: gaps closed by regeneration are not identified gaps. They are excluded from
    # the value and counted separately under exclusions["resolved"] (this metric only).
    exclusions = {**_empty_exclusions(), "resolved": 0}
    failures = []
    for row in rows:
        if row.status == GAP_STATUS_RESOLVED:
            exclusions["resolved"] += 1
            continue
        problem = _gap_problem(db, workspace_id, row)
        if problem is not None:
            exclusions["foreign_reference"] += 1
            failures.append(
                {
                    "source": "evidence_gaps",
                    "reason": problem,
                    "record_id": row.id,
                }
            )
            continue
        slot = _time_slot(row, window)
        if slot != "included":
            exclusions[slot] += 1
            continue
        included.append(row)
    return _count_result(
        "evidence_gaps_stored",
        included,
        exclusions,
        numerator=len(included),
        denominator=None,
        failures=failures,
    )


def _collect_referenced(
    db,
    workspace_id,
    window,
    rows,
    *,
    source,
    stored_name,
    approved_name,
    approved_attr,
    approved_value,
    ref_problem,
):
    included = []
    exclusions = _empty_exclusions()
    failures = []
    for row in rows:
        problem = ref_problem(db, workspace_id, row)
        if problem is not None:
            exclusions["foreign_reference"] += 1
            failures.append({"source": source, "reason": problem, "record_id": row.id})
            continue
        slot = _time_slot(row, window)
        if slot != "included":
            exclusions[slot] += 1
            continue
        included.append(row)
    approved = [row for row in included if getattr(row, approved_attr) == approved_value]
    return {
        "unavailable": False,
        "counts": {
            stored_name: _count_payload(
                included, exclusions, numerator=len(included), denominator=None
            ),
            approved_name: _count_payload(
                approved, exclusions, numerator=len(approved), denominator=len(included)
            ),
        },
        "failures": failures,
    }


def _count_result(name, included, exclusions, *, numerator, denominator, failures=None) -> dict:
    return {
        "unavailable": False,
        "counts": {
            name: _count_payload(
                included, exclusions, numerator=numerator, denominator=denominator
            ),
        },
        "failures": failures or [],
    }


def _count_payload(included, exclusions, *, numerator, denominator) -> dict:
    earliest, latest = _bounds(included)
    return {
        "value": len(included),
        "numerator": numerator,
        "denominator": denominator,
        "freshness": latest,
        "earliest": earliest,
        "exclusions": dict(exclusions),
    }


def _split_timed(rows, window, *, deleted: bool):
    included = []
    exclusions = _empty_exclusions()
    for row in rows:
        if deleted and getattr(row, "deleted_at", None) is not None:
            exclusions["deleted"] += 1
            continue
        slot = _time_slot(row, window)
        if slot != "included":
            exclusions[slot] += 1
            continue
        included.append(row)
    return included, exclusions


def _time_slot(row, window) -> str:
    if getattr(row, "created_at", None) is None:
        return "missing_timestamp"
    if not _in_window(row.created_at, window):
        return "outside_window"
    return "included"


def _in_window(value: datetime, window: tuple[datetime | None, datetime | None]) -> bool:
    start, end = window
    current = _as_utc(value)
    if current is None:
        return False
    if start is not None and current < start:
        return False
    if end is not None and current > end:
        return False
    return True


def _bounds(rows) -> tuple[datetime | None, datetime | None]:
    stamps = []
    for row in rows:
        if getattr(row, "created_at", None) is None:
            continue
        stamps.append(_as_utc(row.created_at))
    stamps = [stamp for stamp in stamps if stamp is not None]
    if not stamps:
        return None, None
    return min(stamps), max(stamps)


def _evidence_problem(db: Session, workspace_id: int, row: EvidenceItem) -> str | None:
    return _document_problem(db, workspace_id, row.document_id)


def _document_problem(db: Session, workspace_id: int, document_id: int | None) -> str | None:
    if document_id is None:
        return None
    document = db.get(Document, document_id)
    if document is None:
        return "missing"
    if document.workspace_id != workspace_id:
        return "other_workspace"
    if document.deleted_at is not None:
        return "deleted"
    return None


def _questionnaire_problem(db: Session, workspace_id: int, questionnaire_id: int | None):
    if questionnaire_id is None:
        return None
    row = db.get(Questionnaire, questionnaire_id)
    if row is None:
        return "missing"
    if row.workspace_id != workspace_id:
        return "other_workspace"
    if row.deleted_at is not None:
        return "deleted"
    return None


def _question_problem(db: Session, workspace_id: int, question_id: int | None) -> str | None:
    if question_id is None:
        return None
    row = db.get(Question, question_id)
    if row is None:
        return "missing"
    return _questionnaire_problem(db, workspace_id, row.questionnaire_id)


def _answer_problem(db: Session, workspace_id: int, answer_id: int | None) -> str | None:
    if answer_id is None:
        return None
    row = db.get(Answer, answer_id)
    if row is None:
        return "missing"
    return _question_problem(db, workspace_id, row.question_id)


def _gap_problem(db: Session, workspace_id: int, row: EvidenceGap) -> str | None:
    return (
        _questionnaire_problem(db, workspace_id, row.questionnaire_id)
        or _question_problem(db, workspace_id, row.question_id)
        or _answer_problem(db, workspace_id, row.answer_id)
    )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    current = _as_utc(value)
    if current is None:
        return None
    return current.isoformat().replace("+00:00", "Z")


def _from_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


COLLECTORS = {
    "questionnaires": _collect_questionnaires,
    "questions": _collect_questions,
    "answers": _collect_answers,
    "documents": _collect_documents,
    "evidence_items": _collect_evidence,
    "exports": _collect_exports,
    "evidence_gaps": _collect_gaps,
}
