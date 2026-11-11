"""Compliance alerts: persisted condition, lifecycle, and current source revision."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_can_review
from app.core.database import get_db
from app.core.idempotency import claim as idempotency_claim
from app.core.idempotency import get as idempotency_get
from app.core.idempotency import set as idempotency_set
from app.models import AuditEvent, EvidenceGap, WorkspaceControl
from app.models.compliance_alert import (
    ALERT_STATUS_ACKNOWLEDGED,
    ALERT_STATUS_ACTIVE,
    ALERT_STATUS_RESOLVED,
    ALERT_STATUS_SNOOZED,
    UQ_COMPLIANCE_ALERTS_ONE_ACTIVE,
    ComplianceAlert,
)
from app.models.evidence_gap import CONTROL_CHECK
from app.services.compliance_coverage import get_compliance_coverage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/compliance-alerts")

SCHEMA_VERSION = "compliance-alerts/v1"
ALERT_NOT_FOUND = "Alert not found"
_LOCK_NAMESPACE = 150017
_REQUEST_HASH = "_request_sha256"
COVERAGE_THRESHOLD = 80
INSUFFICIENT_THRESHOLD = 15

_OPEN = (ALERT_STATUS_ACTIVE, ALERT_STATUS_ACKNOWLEDGED, ALERT_STATUS_SNOOZED)


class NoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = None

    @field_validator("reason", mode="before")
    @classmethod
    def reason_text(cls, value: object) -> object:
        if isinstance(value, str) and "\x00" in value:
            raise ValueError("must not contain a NUL byte")
        return value

    @field_validator("reason")
    @classmethod
    def reason_length(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 500:
            raise ValueError("reason must be at most 500 characters")
        return value


class SnoozeBody(NoteBody):
    until: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _revision(parts: object) -> str:
    raw = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _control_revision(control: WorkspaceControl | None) -> str | None:
    if control is None:
        return None
    if control.content_version:
        return str(control.content_version)
    if control.updated_at is not None:
        return control.updated_at.isoformat()
    return None


def _payload(row: ComplianceAlert) -> dict:
    return {
        "id": row.id,
        "severity": row.severity,
        "title": row.title,
        "description": row.description,
        "metric": row.metric,
        "type": row.condition,
        "status": row.status,
        "condition": row.condition,
        "source_ref": row.source_ref,
        "source_revision": row.source_revision,
        "control_id": row.control_id,
        "control_revision": row.control_revision,
        "reason": row.reason,
        "snoozed_until": _iso(row.snoozed_until),
    }


def _envelope(alerts: list[dict], **extra: object) -> dict:
    body = {"schema_version": SCHEMA_VERSION, "alerts": alerts}
    body.update(extra)
    return body


def _coverage_conditions(data: dict) -> list[dict]:
    kpi = data["kpi"]
    if kpi["total_questions"] == 0:
        return []
    found: list[dict] = []
    if kpi["coverage_pct"] < COVERAGE_THRESHOLD:
        found.append(
            {
                "condition": "coverage_drop",
                "source_ref": "coverage",
                "source_revision": _revision(
                    [kpi["coverage_pct"], kpi["total_questions"], kpi["total_drafted"]]
                ),
                "control_id": None,
                "control_revision": None,
                "severity": "high",
                "title": "Low coverage",
                "description": (
                    f"Coverage is at {kpi['coverage_pct']}%, below the {COVERAGE_THRESHOLD}% target."
                ),
                "metric": kpi["coverage_pct"],
            }
        )
    if kpi["insufficient_pct"] > INSUFFICIENT_THRESHOLD:
        found.append(
            {
                "condition": "high_insufficient",
                "source_ref": "coverage",
                "source_revision": _revision([kpi["insufficient_pct"], kpi["total_insufficient"]]),
                "control_id": None,
                "control_revision": None,
                "severity": "high",
                "title": "High insufficient-answer rate",
                "description": (
                    f"{kpi['total_insufficient']} questions ({kpi['insufficient_pct']}%) "
                    "lack sufficient evidence."
                ),
                "metric": kpi["insufficient_pct"],
            }
        )
    if kpi["blind_spot_count"] > 0:
        top_blind = data["blind_spots"][:3]
        names = ", ".join(item["subject"] for item in top_blind)
        found.append(
            {
                "condition": "blind_spot",
                "source_ref": "coverage",
                "source_revision": _revision([kpi["blind_spot_count"], names]),
                "control_id": None,
                "control_revision": None,
                "severity": "medium" if kpi["blind_spot_count"] <= 2 else "high",
                "title": (
                    f"{kpi['blind_spot_count']} blind spot"
                    f"{'s' if kpi['blind_spot_count'] != 1 else ''} detected"
                ),
                "description": f"Subject areas with insufficient evidence: {names}.",
                "metric": kpi["blind_spot_count"],
            }
        )
    weak = data.get("weak_areas") or []
    if weak:
        worst = weak[0]
        found.append(
            {
                "condition": "weak_evidence",
                "source_ref": f"subject:{worst['subject']}",
                "source_revision": _revision(
                    [worst["subject"], worst["avg_confidence"], worst["count"]]
                ),
                "control_id": None,
                "control_revision": None,
                "severity": "medium",
                "title": "Weak evidence in key area",
                "description": (
                    f"{worst['subject']} has avg confidence of {worst['avg_confidence']}% "
                    f"across {worst['count']} answers."
                ),
                "metric": worst["avg_confidence"],
            }
        )
    for item in [row for row in data.get("framework_coverage", []) if row["coverage_pct"] < 70][:2]:
        found.append(
            {
                "condition": "framework_gap",
                "source_ref": f"framework:{item['framework']}",
                "source_revision": _revision(
                    [item["framework"], item["coverage_pct"], item["drafted"], item["total"]]
                ),
                "control_id": None,
                "control_revision": None,
                "severity": "medium",
                "title": f"Low {item['framework']} coverage",
                "description": (
                    f"Only {item['drafted']}/{item['total']} questions answered "
                    f"({item['coverage_pct']}%)."
                ),
                "metric": item["coverage_pct"],
            }
        )
    return found


def _control_conditions(db: Session, workspace_id: int) -> list[dict]:
    rows = (
        db.query(EvidenceGap, WorkspaceControl)
        .outerjoin(WorkspaceControl, WorkspaceControl.id == EvidenceGap.control_id)
        .filter(
            EvidenceGap.workspace_id == workspace_id,
            EvidenceGap.gap_type == CONTROL_CHECK,
            EvidenceGap.status == "open",
            EvidenceGap.control_id.isnot(None),
        )
        .all()
    )
    found: list[dict] = []
    for gap, control in rows:
        if control is not None and control.workspace_id != workspace_id:
            continue
        revision = _control_revision(control)
        source_revision = revision or _revision([gap.evaluation_state, gap.rule_code])
        found.append(
            {
                "condition": "control_gap",
                "source_ref": f"control:{gap.control_id}",
                "source_revision": source_revision,
                "control_id": gap.control_id,
                "control_revision": revision,
                "severity": "high",
                "title": "Control evidence gap",
                "description": "An open control check still needs qualifying evidence.",
                "metric": None,
            }
        )
    return found


def _desired(db: Session, workspace_id: int) -> list[dict]:
    data = get_compliance_coverage(db, workspace_id)
    return _coverage_conditions(data) + _control_conditions(db, workspace_id)


def _lock_alert_writes(db: Session, workspace_id: int) -> None:
    bind = db.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", None)
    if dialect != "postgresql":
        return
    db.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, :workspace_id)"),
        {"namespace": _LOCK_NAMESPACE, "workspace_id": int(workspace_id)},
    )


def _open_episode(
    db: Session, workspace_id: int, condition: str, source_ref: str
) -> ComplianceAlert | None:
    return (
        db.query(ComplianceAlert)
        .filter(
            ComplianceAlert.workspace_id == workspace_id,
            ComplianceAlert.condition == condition,
            ComplianceAlert.source_ref == source_ref,
            ComplianceAlert.status.in_(_OPEN),
        )
        .order_by(ComplianceAlert.id.desc())
        .first()
    )


def _active_row(
    db: Session, workspace_id: int, condition: str, source_ref: str
) -> ComplianceAlert | None:
    return (
        db.query(ComplianceAlert)
        .filter(
            ComplianceAlert.workspace_id == workspace_id,
            ComplianceAlert.condition == condition,
            ComplianceAlert.source_ref == source_ref,
            ComplianceAlert.status == ALERT_STATUS_ACTIVE,
        )
        .order_by(ComplianceAlert.id.desc())
        .first()
    )


def _apply(row: ComplianceAlert, item: dict, now: datetime) -> None:
    row.severity = item["severity"]
    row.title = item["title"]
    row.description = item["description"]
    row.metric = item["metric"]
    row.source_revision = item["source_revision"]
    row.control_id = item["control_id"]
    row.control_revision = item["control_revision"]
    row.updated_at = now
    if row.status == ALERT_STATUS_SNOOZED and row.snoozed_until is not None:
        until = row.snoozed_until
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        if until <= now:
            row.status = ALERT_STATUS_ACTIVE
            row.snoozed_until = None


def _active_conflict(exc: IntegrityError) -> bool:
    return UQ_COMPLIANCE_ALERTS_ONE_ACTIVE in str(getattr(exc, "orig", exc))


def _save_desired(db: Session, workspace_id: int, item: dict, now: datetime) -> ComplianceAlert:
    current = _open_episode(db, workspace_id, item["condition"], item["source_ref"])
    if current is not None:
        _apply(current, item, now)
        return current
    row = ComplianceAlert(
        workspace_id=workspace_id,
        condition=item["condition"],
        source_ref=item["source_ref"],
        source_revision=item["source_revision"],
        control_id=item["control_id"],
        control_revision=item["control_revision"],
        status=ALERT_STATUS_ACTIVE,
        severity=item["severity"],
        title=item["title"],
        description=item["description"],
        metric=item["metric"],
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError as exc:
        if not _active_conflict(exc):
            raise
        if row in db:
            db.expunge(row)
        current = _active_row(db, workspace_id, item["condition"], item["source_ref"])
        if current is None:
            raise HTTPException(status_code=409, detail="Active alert already exists") from None
        _apply(current, item, now)
        return current
    return row


def _resolve_cleared(
    db: Session, workspace_id: int, seen: set[tuple[str, str]], now: datetime
) -> None:
    rows = (
        db.query(ComplianceAlert)
        .filter(
            ComplianceAlert.workspace_id == workspace_id,
            ComplianceAlert.status.in_(_OPEN),
        )
        .all()
    )
    for row in rows:
        if (row.condition, row.source_ref) in seen:
            continue
        row.status = ALERT_STATUS_RESOLVED
        row.resolved_at = now
        row.updated_at = now


def _active_rows(db: Session, workspace_id: int) -> list[ComplianceAlert]:
    return (
        db.query(ComplianceAlert)
        .filter(
            ComplianceAlert.workspace_id == workspace_id,
            ComplianceAlert.status == ALERT_STATUS_ACTIVE,
        )
        .order_by(ComplianceAlert.id)
        .all()
    )


def _publish_scan(workspace_id: int, persisted: int) -> None:
    del workspace_id, persisted


def _body_hash(body: BaseModel) -> str:
    raw = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _idempotency_key(request: Request, workspace_id: int, action: str, subject: str) -> str:
    raw = (request.headers.get("Idempotency-Key") or "").strip()
    if not raw:
        raise HTTPException(status_code=422, detail="Idempotency-Key is required")
    if len(raw) > 120:
        raise HTTPException(status_code=422, detail="Idempotency-Key is too long")
    key = f"compliance-alerts:{workspace_id}:{action}:{subject}:{raw}"
    if len(key) > 256:
        raise HTTPException(status_code=422, detail="Idempotency-Key is too long")
    return key


def _public(stored: dict) -> dict:
    payload = dict(stored)
    payload.pop(_REQUEST_HASH, None)
    return payload


def _replay(db: Session, key: str, body_hash: str) -> JSONResponse | None:
    record = idempotency_get(db, key)
    if record is None:
        return None
    status, stored = record
    recorded = stored.get(_REQUEST_HASH) if isinstance(stored, dict) else None
    if isinstance(recorded, str) and recorded != body_hash:
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key was already used with a different request body",
        )
    if not isinstance(stored, dict):
        return None
    return JSONResponse(content=_public(stored), status_code=status)


def _claim(db: Session, key: str) -> str:
    owner = idempotency_claim(db, key)
    if owner is None:
        cached = idempotency_get(db, key)
        if cached:
            return ""
        raise HTTPException(
            status_code=409, detail="Request in progress; retry with same Idempotency-Key"
        )
    return owner


def _drop_claim(db: Session, key: str, owner: str | None) -> None:
    if not owner:
        return
    from sqlalchemy import text

    db.rollback()
    db.execute(
        text(
            "DELETE FROM idempotency_keys "
            "WHERE idempotency_key = :key AND owner_token = :owner AND status_code = 0"
        ),
        {"key": key, "owner": owner},
    )
    db.commit()


def _settle(db: Session, key: str, owner: str, status: int, payload: dict) -> None:
    db.rollback()
    try:
        idempotency_set(db, key, status, payload, owner=owner)
    except Exception:
        logger.exception("compliance alert idempotency store failed after commit")
        db.rollback()


def _alert_in_workspace(db: Session, alert_id: int, workspace_id: int) -> ComplianceAlert:
    row = db.query(ComplianceAlert).filter(ComplianceAlert.id == alert_id).first()
    if row is None or row.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail=ALERT_NOT_FOUND)
    return row


def _record_audit(
    db: Session, session: dict, action: str, row: ComplianceAlert, workspace_id: int
) -> None:
    db.add(
        AuditEvent(
            action=action,
            user_id=session.get("user_id"),
            email=session.get("email"),
            workspace_id=workspace_id,
            resource_type="compliance_alert",
            resource_id=str(row.id),
            details=json.dumps({"status": row.status}),
        )
    )


def _mutate(
    db: Session,
    request: Request,
    session: dict,
    alert_id: int,
    action: str,
    body: BaseModel,
    apply,
) -> dict:
    workspace_id = request.state.workspace_id
    body_hash = _body_hash(body)
    key = _idempotency_key(request, workspace_id, action, str(alert_id))
    replay = _replay(db, key, body_hash)
    if replay is not None:
        return replay
    owner = _claim(db, key)
    if owner == "":
        replay = _replay(db, key, body_hash)
        if replay is not None:
            return replay
        raise HTTPException(
            status_code=409, detail="Request in progress; retry with same Idempotency-Key"
        )
    try:
        row = _alert_in_workspace(db, alert_id, workspace_id)
        if row.status == ALERT_STATUS_RESOLVED:
            raise HTTPException(status_code=409, detail="already resolved")
        apply(row)
        row.actor_user_id = session.get("user_id")
        row.updated_at = _now()
        _record_audit(db, session, action, row, workspace_id)
        db.commit()
        db.refresh(row)
        payload = {"schema_version": SCHEMA_VERSION, "alert": _payload(row)}
        stored = {**payload, _REQUEST_HASH: body_hash}
        _settle(db, key, owner, 200, stored)
        return payload
    except HTTPException:
        db.rollback()
        _drop_claim(db, key, owner)
        raise
    except Exception:
        db.rollback()
        _drop_claim(db, key, owner)
        raise


@router.get("/active")
def get_active_alerts(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_can_admin),
):
    workspace_id = request.state.workspace_id
    rows = _active_rows(db, workspace_id)
    return _envelope([_payload(row) for row in rows])


@router.post("/scan")
def scan_alerts(
    request: Request,
    body: NoteBody,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    workspace_id = request.state.workspace_id
    body_hash = _body_hash(body)
    key = _idempotency_key(request, workspace_id, "scan", "workspace")
    replay = _replay(db, key, body_hash)
    if replay is not None:
        return replay
    owner = _claim(db, key)
    if owner == "":
        replay = _replay(db, key, body_hash)
        if replay is not None:
            return replay
        raise HTTPException(
            status_code=409, detail="Request in progress; retry with same Idempotency-Key"
        )
    try:
        now = _now()
        _lock_alert_writes(db, workspace_id)
        desired = _desired(db, workspace_id)
        for item in desired:
            _save_desired(db, workspace_id, item, now)
        _resolve_cleared(
            db,
            workspace_id,
            {(item["condition"], item["source_ref"]) for item in desired},
            now,
        )
        db.add(
            AuditEvent(
                action="alert_scanned",
                user_id=session.get("user_id"),
                email=session.get("email"),
                workspace_id=workspace_id,
                resource_type="compliance_alert",
                resource_id=str(workspace_id),
                details=json.dumps({"conditions": len(desired)}),
            )
        )
        db.commit()
        alerts = [_payload(row) for row in _active_rows(db, workspace_id)]
        partial = False
        try:
            _publish_scan(workspace_id, len(alerts))
        except Exception:
            logger.exception("compliance alert publish failed")
            partial = True
        payload = _envelope(alerts, partial=partial, persisted=len(alerts))
        if partial:
            payload["reason"] = "publish_failed"
        stored = {**payload, _REQUEST_HASH: body_hash}
        _settle(db, key, owner, 200, stored)
        return payload
    except HTTPException:
        db.rollback()
        _drop_claim(db, key, owner)
        raise
    except Exception:
        db.rollback()
        _drop_claim(db, key, owner)
        raise


@router.post("/{alert_id}/acknowledge")
def acknowledge_alert(
    alert_id: int,
    request: Request,
    body: NoteBody,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_review),
):
    def apply(row: ComplianceAlert) -> None:
        row.status = ALERT_STATUS_ACKNOWLEDGED
        row.reason = body.reason

    return _mutate(db, request, session, alert_id, "alert_acknowledged", body, apply)


@router.post("/{alert_id}/snooze")
def snooze_alert(
    alert_id: int,
    request: Request,
    body: SnoozeBody,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_review),
):
    def apply(row: ComplianceAlert) -> None:
        until = body.until
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        row.status = ALERT_STATUS_SNOOZED
        row.snoozed_until = until
        row.reason = body.reason

    return _mutate(db, request, session, alert_id, "alert_snoozed", body, apply)


@router.post("/{alert_id}/resolve")
def resolve_alert(
    alert_id: int,
    request: Request,
    body: NoteBody,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_review),
):
    def apply(row: ComplianceAlert) -> None:
        row.status = ALERT_STATUS_RESOLVED
        row.resolved_at = _now()
        row.reason = body.reason

    return _mutate(db, request, session, alert_id, "alert_resolved", body, apply)
