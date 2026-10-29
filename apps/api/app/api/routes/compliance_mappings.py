"""Compliance foundation: cross-framework control mappings; Phase 2 confirm/override; Phase 3 mapping-suggest.

TC-21-005 versions the workspace question-to-control decision. Precedence is
override, then confirmation, then proposal. GETs do not write.
"""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.auth_deps import require_can_admin, require_can_review
from app.core.compliance_rate_limit import check_compliance_write_allowed
from app.core.database import get_db
from app.core.idempotency import claim as idempotency_claim
from app.core.idempotency import get as idempotency_get
from app.core.idempotency import release as idempotency_release
from app.core.idempotency import set as idempotency_set
from app.models import (
    AuditEvent,
    ControlMapping,
    ControlMappingHistory,
    ControlMappingOverride,
    Framework,
    FrameworkControl,
    WorkspaceControl,
)
from app.services.compliance_hooks import question_to_controls
from app.services.compliance_webhook_emitter import (
    EVENT_MAPPING_CONFIRMED,
    EVENT_MAPPING_OVERRIDDEN,
    emit_compliance_event,
)
from app.services.in_app_notification_service import notify_admins
from app.services.question_normalizer import normalize_question, question_cache_hash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/compliance/control-mappings", tags=["compliance-mappings"])

PRECEDENCE = {"proposed": 1, "confirmed": 2, "overridden": 3}
CONTROL_NOT_FOUND = "Control not found"
MAPPING_NOT_FOUND = "Mapping not found"


class ConfirmMappingBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str
    control_ids: list[int] = []
    source_control_id: int | None = None
    rationale: str | None = None
    reviewer_id: int | None = None
    reviewed_at: str | None = None


class OverrideMappingBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str
    control_ids: list[int] = []
    source_control_id: int | None = None
    rationale: str | None = None
    reviewer_id: int | None = None
    reviewed_at: str | None = None


class RollbackMappingBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str
    reviewer_id: int | None = None
    reviewed_at: str | None = None


def _framework_id_by_name(db: Session, name: str) -> list[int]:
    """Exact stored name. A dev row does not resolve when an advertised row shares it."""
    from app.services.framework_catalog import framework_ids_for_exact_name

    return framework_ids_for_exact_name(db, name)


def _fc_ids_for_framework(db: Session, framework_name: str) -> list[int]:
    fw_ids = _framework_id_by_name(db, framework_name)
    if not fw_ids:
        return []
    return [
        r[0]
        for r in db.query(FrameworkControl.id)
        .filter(FrameworkControl.framework_id.in_(fw_ids))
        .all()
    ]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _ids(raw) -> list[int]:
    if not isinstance(raw, list):
        return []
    return [int(item) for item in raw if item is not None]


def _question_hash(question: str) -> str:
    norm = normalize_question(question or "")
    return question_cache_hash(norm) if norm else ""


def _public(row: ControlMappingOverride, *, updated: bool, precedence_held: bool) -> dict:
    state = row.state or "overridden"
    return {
        "id": row.id,
        "question_hash": row.question_hash,
        "control_ids": _ids(row.override_control_ids),
        "state": state,
        "version": row.version,
        "rationale": row.rationale,
        "precedence": PRECEDENCE.get(state, 0),
        "reviewed_by_user_id": row.reviewed_by_user_id,
        "reviewed_at": _iso(row.reviewed_at),
        "updated": updated,
        "precedence_held": precedence_held,
    }


def _require_same_workspace(db: Session, workspace_id: int, control_ids: list[int]) -> None:
    if not control_ids:
        return
    found = {
        row[0]
        for row in db.query(WorkspaceControl.id)
        .filter(
            WorkspaceControl.workspace_id == workspace_id,
            WorkspaceControl.id.in_(control_ids),
        )
        .all()
    }
    if set(control_ids) != found:
        raise HTTPException(status_code=404, detail=CONTROL_NOT_FOUND)


def _load(db: Session, workspace_id: int, question_hash: str) -> ControlMappingOverride | None:
    return (
        db.query(ControlMappingOverride)
        .filter(
            ControlMappingOverride.workspace_id == workspace_id,
            ControlMappingOverride.question_hash == question_hash,
        )
        .first()
    )


def _snapshot(db: Session, row: ControlMappingOverride) -> None:
    db.add(
        ControlMappingHistory(
            mapping_id=row.id,
            version=row.version,
            workspace_id=row.workspace_id,
            question_hash=row.question_hash,
            control_ids=_ids(row.override_control_ids),
            state=row.state,
            rationale=row.rationale,
            reviewed_by_user_id=row.reviewed_by_user_id,
            reviewed_at=row.reviewed_at,
            recorded_at=datetime.utcnow(),
        )
    )


def _add_audit(
    db: Session,
    session: dict,
    *,
    action: str,
    mapping_id: int,
    previous_state: str | None,
    new_state: str,
    rationale: str | None,
    version: int,
    control_ids: list[int],
) -> None:
    actor = session.get("user_id")
    stamp = datetime.utcnow().isoformat()
    details = {
        "actor_user_id": actor,
        "timestamp": stamp,
        "previous_state": previous_state,
        "new_state": new_state,
        "rationale": rationale,
        "version": version,
        "control_ids": control_ids,
    }
    audit_log(
        action,
        user_id=actor,
        email=session.get("email"),
        workspace_id=session.get("workspace_id"),
        resource_type="control_mapping",
        resource_id=mapping_id,
        details=details,
    )
    db.add(
        AuditEvent(
            action=action,
            user_id=actor,
            email=session.get("email"),
            workspace_id=session.get("workspace_id"),
            resource_type="control_mapping",
            resource_id=str(mapping_id),
            details=json.dumps(details),
        )
    )


def _idempotency_key(
    request: Request, workspace_id: int, action: str, question_hash: str
) -> str | None:
    raw = (request.headers.get("Idempotency-Key") or "").strip()
    if not raw:
        return None
    if len(raw) > 160:
        raise HTTPException(status_code=422, detail="Idempotency-Key is too long")
    return f"m:{workspace_id}:{action}:{question_hash}:{raw}"


def _claim_or_replay(db: Session, key: str | None) -> tuple[JSONResponse | None, str | None]:
    if not key:
        return None, None
    cached = idempotency_get(db, key)
    if cached:
        return JSONResponse(content=cached[1], status_code=cached[0]), None
    owner = idempotency_claim(db, key)
    if owner is None:
        cached_again = idempotency_get(db, key)
        if cached_again:
            return JSONResponse(content=cached_again[1], status_code=cached_again[0]), None
        raise HTTPException(
            status_code=409, detail="Request in progress; retry with same Idempotency-Key"
        )
    return None, owner


def _settle(db: Session, key: str | None, owner: str | None, payload: dict | None) -> None:
    """Store the committed mapping result. A second store failure is logged only."""
    if not key or payload is None:
        return
    db.rollback()
    try:
        idempotency_set(db, key, 200, payload, owner=owner)
    except Exception:
        logger.exception(
            "mapping idempotency store failed after commit; storing the committed result"
        )
        db.rollback()
        from app.core.idempotency import set as complete_claim

        try:
            complete_claim(db, key, 200, payload, owner=owner)
        except Exception:
            logger.exception(
                "mapping second idempotency store failed after commit; the original error is unchanged"
            )


def _apply_decision(
    db: Session,
    session: dict,
    *,
    workspace_id: int,
    question: str,
    control_ids: list[int],
    state: str,
    rationale: str | None,
    source_control_id: int | None = None,
) -> dict:
    question_hash = _question_hash(question)
    if not question_hash:
        raise HTTPException(status_code=400, detail="question is required")
    if state == "overridden" and not (rationale or "").strip():
        raise HTTPException(status_code=400, detail="rationale is required")
    cleaned = (rationale or "").strip() or None
    ids = [int(item) for item in control_ids]
    _require_same_workspace(db, workspace_id, ids)
    if source_control_id is not None:
        _require_same_workspace(db, workspace_id, [int(source_control_id)])
    actor = session.get("user_id")
    now = datetime.utcnow()
    row = _load(db, workspace_id, question_hash)
    if row is not None and state == "confirmed" and row.state == "overridden":
        return _public(row, updated=False, precedence_held=True)
    if row is None:
        proposal_ids, _confidence = question_to_controls(question or "", workspace_id, db)
        row = ControlMappingOverride(
            workspace_id=workspace_id,
            question_hash=question_hash,
            override_control_ids=proposal_ids,
            state="proposed",
            version=1,
            rationale=None,
            reviewed_by_user_id=None,
            reviewed_at=now,
        )
        db.add(row)
        db.flush()
        _add_audit(
            db,
            session,
            action="mapping.propose",
            mapping_id=row.id,
            previous_state=None,
            new_state="proposed",
            rationale=None,
            version=1,
            control_ids=proposal_ids,
        )
        _snapshot(db, row)
        row.state = state
        row.version = 2
        row.override_control_ids = ids
        row.rationale = cleaned
        row.reviewed_by_user_id = actor
        row.reviewed_at = now
        action = "mapping.override" if state == "overridden" else "mapping.confirm"
        _add_audit(
            db,
            session,
            action=action,
            mapping_id=row.id,
            previous_state="proposed",
            new_state=state,
            rationale=cleaned,
            version=2,
            control_ids=ids,
        )
    else:
        previous = row.state
        _snapshot(db, row)
        row.version = int(row.version or 1) + 1
        row.state = state
        row.override_control_ids = ids
        row.rationale = cleaned
        row.reviewed_by_user_id = actor
        row.reviewed_at = now
        action = "mapping.override" if state == "overridden" else "mapping.confirm"
        _add_audit(
            db,
            session,
            action=action,
            mapping_id=row.id,
            previous_state=previous,
            new_state=state,
            rationale=cleaned,
            version=row.version,
            control_ids=ids,
        )
    db.commit()
    db.refresh(row)
    return _public(row, updated=True, precedence_held=False)


def _apply_rollback(db: Session, session: dict, *, workspace_id: int, question: str) -> dict:
    question_hash = _question_hash(question)
    if not question_hash:
        raise HTTPException(status_code=400, detail="question is required")
    row = _load(db, workspace_id, question_hash)
    if row is None:
        raise HTTPException(status_code=404, detail=MAPPING_NOT_FOUND)
    prior = (
        db.query(ControlMappingHistory)
        .filter(ControlMappingHistory.mapping_id == row.id)
        .order_by(ControlMappingHistory.id.desc())
        .first()
    )
    if prior is None:
        raise HTTPException(status_code=400, detail="Nothing to roll back")
    previous = row.state
    _snapshot(db, row)
    row.version = int(row.version or 1) + 1
    row.state = prior.state
    row.override_control_ids = _ids(prior.control_ids)
    row.rationale = prior.rationale
    row.reviewed_by_user_id = session.get("user_id")
    row.reviewed_at = datetime.utcnow()
    _add_audit(
        db,
        session,
        action="mapping.rollback",
        mapping_id=row.id,
        previous_state=previous,
        new_state=prior.state,
        rationale=prior.rationale,
        version=row.version,
        control_ids=_ids(prior.control_ids),
    )
    db.commit()
    db.refresh(row)
    return _public(row, updated=True, precedence_held=False)


def _run_mutation(db: Session, request: Request, session: dict, action: str, question: str, writer):
    workspace_id = session.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=403, detail="No workspace")
    if not check_compliance_write_allowed(workspace_id):
        raise HTTPException(status_code=429, detail="Too many compliance writes; try again later.")
    question_hash = _question_hash(question)
    key = _idempotency_key(request, workspace_id, action, question_hash or "none")
    cached, owner = _claim_or_replay(db, key)
    if cached is not None:
        return cached
    try:
        payload = writer()
    except Exception:
        db.rollback()
        if key:
            idempotency_release(db, key, owner=owner)
        raise
    try:
        if payload.get("updated") and action in ("confirm", "override", "rollback"):
            if action == "override" or payload.get("state") == "overridden":
                event = EVENT_MAPPING_OVERRIDDEN
            else:
                event = EVENT_MAPPING_CONFIRMED
            try:
                emit_compliance_event(
                    db,
                    workspace_id,
                    event,
                    {
                        "resource_type": "mapping",
                        "resource_id": payload.get("question_hash"),
                        "question": (question or "")[:500] or None,
                        "question_hash": payload.get("question_hash"),
                        "control_ids": payload.get("control_ids", []),
                        "state": payload.get("state"),
                        "version": payload.get("version"),
                    },
                    user_id=session.get("user_id"),
                    email=session.get("email"),
                )
            except Exception:
                logger.exception("mapping compliance event failed after commit")
            try:
                title = "Mapping overridden" if action == "override" else "Mapping confirmed"
                if action == "rollback":
                    title = "Mapping rolled back"
                notify_admins(
                    db,
                    workspace_id,
                    title,
                    "Question-to-control mapping updated.",
                    category="warning" if action == "override" else "info",
                    link="/dashboard/review",
                )
            except Exception:
                logger.exception("mapping notification failed after commit")
        return payload
    finally:
        _settle(db, key, owner, payload if isinstance(payload, dict) else None)


@router.get("", response_model=list)
def list_control_mappings(
    source_framework: str | None = Query(None, description="Filter by source framework name"),
    target_framework: str | None = Query(None, description="Filter by target framework name"),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """List cross-framework control mappings. Optional filters by framework name.

    Read-only. Stored catalog names are returned as already saved. This route
    does not add framework requirement text.
    """
    del session
    q = db.query(ControlMapping).order_by(ControlMapping.id)
    if source_framework is not None:
        src_fc_ids = _fc_ids_for_framework(db, source_framework)
        if not src_fc_ids:
            return []
        q = q.filter(ControlMapping.source_control_id.in_(src_fc_ids))
    if target_framework is not None:
        tgt_fc_ids = _fc_ids_for_framework(db, target_framework)
        if not tgt_fc_ids:
            return []
        q = q.filter(ControlMapping.target_control_id.in_(tgt_fc_ids))
    rows = q.all()
    out = []
    for r in rows:
        src_fc = (
            db.query(FrameworkControl).filter(FrameworkControl.id == r.source_control_id).first()
        )
        src_fw = (
            db.query(Framework).filter(Framework.id == src_fc.framework_id).first()
            if src_fc
            else None
        )
        tgt_fc = (
            db.query(FrameworkControl).filter(FrameworkControl.id == r.target_control_id).first()
        )
        tgt_fw = (
            db.query(Framework).filter(Framework.id == tgt_fc.framework_id).first()
            if tgt_fc
            else None
        )
        out.append(
            {
                "id": r.id,
                "source_control_id": r.source_control_id,
                "target_control_id": r.target_control_id,
                "source_key": src_fc.control_key if src_fc else None,
                "source_framework": src_fw.name if src_fw else None,
                "target_key": tgt_fc.control_key if tgt_fc else None,
                "target_framework": tgt_fw.name if tgt_fw else None,
            }
        )
    return out


@router.post("/confirm", response_model=dict)
def confirm_mapping(
    body: ConfirmMappingBody,
    request: Request,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Confirm a question-to-control mapping. Requires admin.

    The reviewer id and timestamp come from the server. A body reviewer id is ignored.
    An active override is left in place.
    """

    def writer():
        return _apply_decision(
            db,
            session,
            workspace_id=session["workspace_id"],
            question=body.question,
            control_ids=body.control_ids,
            state="confirmed",
            rationale=body.rationale,
            source_control_id=body.source_control_id,
        )

    return _run_mutation(db, request, session, "confirm", body.question, writer)


@router.post("/override", response_model=dict)
def override_mapping(
    body: OverrideMappingBody,
    request: Request,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Override a question-to-control mapping. Requires admin and a rationale.

    The reviewer id and timestamp come from the server. A body reviewer id is ignored.
    """

    def writer():
        return _apply_decision(
            db,
            session,
            workspace_id=session["workspace_id"],
            question=body.question,
            control_ids=body.control_ids,
            state="overridden",
            rationale=body.rationale,
            source_control_id=body.source_control_id,
        )

    return _run_mutation(db, request, session, "override", body.question, writer)


@router.post("/rollback", response_model=dict)
def rollback_mapping(
    body: RollbackMappingBody,
    request: Request,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Restore the previous mapping version. Requires admin.

    The reviewer id and timestamp are the authenticated user and the server clock.
    """

    def writer():
        return _apply_rollback(
            db,
            session,
            workspace_id=session["workspace_id"],
            question=body.question,
        )

    return _run_mutation(db, request, session, "rollback", body.question, writer)


@router.get("/suggest", response_model=dict)
def mapping_suggest(
    question: str = Query(..., min_length=1),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Return the winning mapping for a question. Read-only.

    An override beats a confirmation, which beats a stored or live proposal.
    """
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    question_hash = _question_hash(question)
    row = _load(db, ws, question_hash) if question_hash else None
    if row is not None:
        state = row.state or "overridden"
        ids = _ids(row.override_control_ids)
        if state == "overridden":
            reason = "Human override takes precedence over confirmation and proposal."
        elif state == "confirmed":
            reason = "Human confirmation takes precedence over a proposal."
        else:
            reason = "Stored proposal."
        return {
            "control_ids": ids,
            "confidence": 1.0 if state != "proposed" else 0.5,
            "has_override": state == "overridden",
            "reason": reason,
            "state": state,
            "version": row.version,
            "precedence": PRECEDENCE.get(state, 0),
            "rationale": row.rationale,
            "reviewed_by_user_id": row.reviewed_by_user_id,
            "reviewed_at": _iso(row.reviewed_at),
        }
    ids, match_confidence = question_to_controls(question or "", ws, db)
    return {
        "control_ids": ids,
        "confidence": match_confidence,
        "has_override": False,
        "reason": "Proposal from workspace keywords." if ids else "No matching controls found.",
        "state": "proposed",
        "version": None,
        "precedence": PRECEDENCE["proposed"],
        "rationale": None,
        "reviewed_by_user_id": None,
        "reviewed_at": None,
    }
