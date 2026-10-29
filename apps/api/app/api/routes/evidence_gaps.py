"""Evidence gap ownership and resolution.

GET does not write. A gap closes only when the shared evidence check is clear
and the evidence backs the gap's control or question.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.routes.compliance_gaps import _classify_evidence
from app.core.auth_deps import require_can_admin, require_can_review
from app.core.database import get_db
from app.core.idempotency import claim as idempotency_claim
from app.core.idempotency import get as idempotency_get
from app.core.idempotency import release as idempotency_release
from app.core.idempotency import set as idempotency_set
from app.models import (
    CONTROL_CHECK_CLOSE_REASON,
    Answer,
    Chunk,
    ControlEvidenceLink,
    EvidenceGap,
    EvidenceItem,
    Question,
    Questionnaire,
    WorkspaceControl,
)
from app.services.evidence_gap_service import _lock_questionnaire_gap_writes
from app.services.in_app_notification_service import notify_admins

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "evidence-gap-ownership/v1"
GAP_NOT_FOUND = "Gap not found"
CONTROL_NOT_FOUND = "Control not found"
QUESTION_NOT_FOUND = "Question not found"
EVIDENCE_NOT_FOUND = "Evidence not found"
_DECIDED = {"accepted", "dismissed"}
_HIGH_STATES = {"failed", "unknown", "stale"}
_HIGH_AGE_DAYS = 14

def _strict_id(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("must be an integer")
    return value


class EnsureGapBody(BaseModel):
    gap_type: str
    control_id: int | None = None
    question_id: int | None = None
    reason: str | None = None

    @field_validator("gap_type")
    @classmethod
    def gap_type_text(cls, value: str) -> str:
        text_value = value.strip()
        if not text_value:
            raise ValueError("gap_type is required")
        return text_value

    @field_validator("control_id", "question_id", mode="before")
    @classmethod
    def strict_ids(cls, value: object) -> int | None:
        return _strict_id(value)


class DecisionBody(BaseModel):
    status: Literal["accepted", "dismissed"]


class ResolveBody(BaseModel):
    evidence_id: int

    @field_validator("evidence_id", mode="before")
    @classmethod
    def strict_evidence_id(cls, value: object) -> int:
        parsed = _strict_id(value)
        if parsed is None:
            raise ValueError("evidence_id is required")
        return parsed


router = APIRouter(prefix="/evidence-gaps", tags=["evidence-gaps"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ownership(gap: EvidenceGap, *, owner_user_id: int | None, now: datetime) -> dict:
    """Age, owner, and priority from the same inputs every time."""
    created = gap.created_at
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    stamp = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    age_days = 0 if created is None else max(0, (stamp - created).days)
    state = gap.evaluation_state or ""
    if gap.status in _DECIDED or gap.status == "resolved":
        priority = "settled"
    elif state in _HIGH_STATES or age_days >= _HIGH_AGE_DAYS:
        priority = "high"
    elif owner_user_id is None:
        priority = "medium"
    else:
        priority = "low"
    return {
        "age_days": age_days,
        "owner_user_id": owner_user_id,
        "owner_missing": owner_user_id is None,
        "priority": priority,
    }


def _aware(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _visible_evidence_ids(db: Session, workspace_id: int, raw: str | None) -> list[int]:
    try:
        parsed = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    wanted = [item for item in parsed if isinstance(item, int) and not isinstance(item, bool)]
    if not wanted:
        return []
    rows = (
        db.query(EvidenceItem.id, EvidenceItem.workspace_id)
        .filter(EvidenceItem.id.in_(wanted))
        .all()
    )
    foreign = {row.id for row in rows if row.workspace_id != workspace_id}
    return [item for item in wanted if item not in foreign]


def _owner_id(db: Session, gap: EvidenceGap, workspace_id: int) -> int | None:
    if gap.control_id is not None:
        control = (
            db.query(WorkspaceControl)
            .filter(
                WorkspaceControl.id == gap.control_id,
                WorkspaceControl.workspace_id == workspace_id,
            )
            .first()
        )
        if control is not None and control.owner_user_id is not None:
            return control.owner_user_id
    return gap.owner_user_id


def _duplicate(db: Session, gap: EvidenceGap) -> dict:
    if gap.control_id is not None:
        rows = (
            db.query(EvidenceGap)
            .filter(
                EvidenceGap.workspace_id == gap.workspace_id,
                EvidenceGap.gap_type == gap.gap_type,
                EvidenceGap.control_id == gap.control_id,
                EvidenceGap.status == "open",
            )
            .order_by(EvidenceGap.id)
            .all()
        )
        key = {"control_id": gap.control_id, "question_id": None, "gap_type": gap.gap_type}
    elif gap.question_id is not None:
        rows = (
            db.query(EvidenceGap)
            .filter(
                EvidenceGap.workspace_id == gap.workspace_id,
                EvidenceGap.gap_type == gap.gap_type,
                EvidenceGap.question_id == gap.question_id,
                EvidenceGap.status == "open",
            )
            .order_by(EvidenceGap.id)
            .all()
        )
        key = {"control_id": None, "question_id": gap.question_id, "gap_type": gap.gap_type}
    else:
        rows = []
        key = None
    ids = [row.id for row in rows]
    return {
        "key": key,
        "open_ids": ids,
        "canonical_id": ids[0] if ids else None,
        "duplicate": len(ids) > 1,
    }


def gap_payload(db: Session, gap: EvidenceGap, workspace_id: int) -> dict:
    owner = _owner_id(db, gap, workspace_id)
    facts = ownership(gap, owner_user_id=owner, now=_now())
    duplicate = _duplicate(db, gap)
    return {
        "schema_version": SCHEMA_VERSION,
        "id": gap.id,
        "workspace_id": gap.workspace_id,
        "questionnaire_id": gap.questionnaire_id,
        "question_id": gap.question_id,
        "answer_id": gap.answer_id,
        "gap_type": gap.gap_type,
        "reason": gap.reason,
        "proposed_policy_addition": gap.proposed_policy_addition,
        "suggested_evidence_doc_title": gap.suggested_evidence_doc_title,
        "confidence": gap.confidence,
        "status": gap.status,
        "created_at": _aware(gap.created_at),
        "updated_at": _aware(gap.updated_at),
        "closed_at": _aware(gap.closed_at),
        "close_reason": gap.close_reason,
        "control_id": gap.control_id,
        "evaluation_state": gap.evaluation_state,
        "rule_code": gap.rule_code,
        "evidence_ids": _visible_evidence_ids(db, workspace_id, gap.evidence_refs),
        "next_action": gap.next_action,
        **facts,
        "duplicate": duplicate,
    }


def _gap_in_workspace(db: Session, gap_id: int, workspace_id: int) -> EvidenceGap:
    row = (
        db.query(EvidenceGap)
        .filter(EvidenceGap.id == gap_id, EvidenceGap.workspace_id == workspace_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=GAP_NOT_FOUND)
    return row


def _control_in_workspace(db: Session, control_id: int, workspace_id: int) -> WorkspaceControl:
    row = (
        db.query(WorkspaceControl)
        .filter(WorkspaceControl.id == control_id, WorkspaceControl.workspace_id == workspace_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=CONTROL_NOT_FOUND)
    return row


def _question_in_workspace(db: Session, question_id: int, workspace_id: int) -> Question:
    row = (
        db.query(Question)
        .join(Questionnaire, Questionnaire.id == Question.questionnaire_id)
        .filter(Question.id == question_id, Questionnaire.workspace_id == workspace_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=QUESTION_NOT_FOUND)
    return row


def _evidence_in_workspace(db: Session, evidence_id: int, workspace_id: int) -> EvidenceItem:
    row = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_id).first()
    if row is None or row.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail=EVIDENCE_NOT_FOUND)
    return row


def _insert_open_gap(db: Session, chosen: EvidenceGap) -> None:
    with db.begin_nested():
        db.add(chosen)
        db.flush()


def _lock_control_gap_writes(db: Session, control_id: int) -> None:
    bind = db.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", None)
    if dialect != "postgresql":
        return
    db.execute(
        text("SELECT pg_advisory_xact_lock(150016, :control_id)"),
        {"control_id": int(control_id)},
    )


def _question_cites_document(db: Session, question_id: int, document_id: int | None) -> bool:
    if document_id is None:
        return False
    answers = db.query(Answer).filter(Answer.question_id == question_id).all()
    chunk_ids: list[int] = []
    for answer in answers:
        try:
            citations = json.loads(answer.citations or "[]")
        except (TypeError, ValueError):
            continue
        if not isinstance(citations, list):
            continue
        for item in citations:
            if isinstance(item, dict) and isinstance(item.get("chunk_id"), int):
                chunk_ids.append(item["chunk_id"])
    if not chunk_ids:
        return False
    found = (
        db.query(Chunk.id).filter(Chunk.id.in_(chunk_ids), Chunk.document_id == document_id).first()
    )
    return found is not None


def evidence_backs_gap(
    db: Session, gap: EvidenceGap, ev: EvidenceItem, now: datetime
) -> str | None:
    """Return None when the evidence is eligible and backs the gap. Else a rule code.

    Eligibility is ``_classify_evidence`` from the control-check route.
    """
    state, rule, shown = _classify_evidence(
        db, ev, ev.id, gap.workspace_id, now.replace(tzinfo=None)
    )
    if shown is None or state != "clear":
        return rule or "not_eligible"
    if gap.control_id is not None:
        link = (
            db.query(ControlEvidenceLink)
            .filter(
                ControlEvidenceLink.control_id == gap.control_id,
                ControlEvidenceLink.evidence_id == ev.id,
            )
            .first()
        )
        if link is None:
            return "not_linked"
        return None
    if gap.question_id is not None and _question_cites_document(
        db, gap.question_id, ev.document_id
    ):
        return None
    if gap.question_id is not None:
        return "not_linked"
    return "no_subject"


def _idempotency_key(
    request: Request | None, workspace_id: int, action: str, subject: str
) -> str | None:
    """Optional key scoped by action and gap, matching accept-suggested."""
    if request is None:
        return None
    raw = (request.headers.get("Idempotency-Key") or "").strip()
    if not raw:
        return None
    if len(raw) > 120:
        raise HTTPException(status_code=422, detail="Idempotency-Key is too long")
    return f"evidence-gaps:{workspace_id}:{action}:{subject}:{raw}"


def _claim_or_replay(db: Session, key: str | None):
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


def _settle(db: Session, key: str | None, owner: str | None, status: int, payload: dict | None):
    if not key or payload is None:
        return
    db.rollback()
    try:
        idempotency_set(db, key, status, payload, owner=owner)
    except Exception:
        logger.exception("evidence gap idempotency store failed after commit")
        db.rollback()


@router.get("")
def list_gaps(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_can_review),
):
    workspace_id = request.state.workspace_id
    rows = (
        db.query(EvidenceGap)
        .filter(EvidenceGap.workspace_id == workspace_id)
        .order_by(EvidenceGap.id)
        .all()
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "gaps": [gap_payload(db, row, workspace_id) for row in rows],
    }


@router.get("/{gap_id}")
def get_gap(
    gap_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_can_review),
):
    workspace_id = request.state.workspace_id
    return gap_payload(db, _gap_in_workspace(db, gap_id, workspace_id), workspace_id)


@router.post("")
def ensure_open_gap(
    body: EnsureGapBody,
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_can_review),
):
    """Return the one open gap for this control or question and gap type.

    A reviewer decision is not reopened. Extra open rows are explained, not deleted.
    Concurrent inserts use a transaction lock and return the existing row on conflict.
    """
    workspace_id = request.state.workspace_id
    key = _idempotency_key(request, workspace_id, "create", "new")
    cached, owner = _claim_or_replay(db, key)
    if cached is not None:
        return cached
    status_code = 200
    try:
        gap_type = body.gap_type
        control_id = body.control_id
        question_id = body.question_id
        questionnaire_id = None
        if question_id is not None:
            question = _question_in_workspace(db, question_id, workspace_id)
            questionnaire_id = question.questionnaire_id
            _lock_questionnaire_gap_writes(db, questionnaire_id)
        if control_id is not None:
            _control_in_workspace(db, control_id, workspace_id)
            _lock_control_gap_writes(db, control_id)
        if control_id is None and question_id is None:
            raise HTTPException(status_code=422, detail="control_id or question_id is required")
        query = db.query(EvidenceGap).filter(
            EvidenceGap.workspace_id == workspace_id,
            EvidenceGap.status != "resolved",
        )
        if question_id is not None and gap_type != "control_check":
            query = query.filter(
                EvidenceGap.question_id == question_id,
                EvidenceGap.gap_type != "control_check",
            )
        elif control_id is not None:
            query = query.filter(
                EvidenceGap.control_id == control_id,
                EvidenceGap.gap_type == gap_type,
            )
        else:
            query = query.filter(EvidenceGap.question_id == question_id)
        existing = query.order_by(EvidenceGap.id).all()
        decided = [row for row in existing if row.status in _DECIDED]
        open_rows = [row for row in existing if row.status == "open"]
        if open_rows:
            chosen = open_rows[0]
        elif decided:
            chosen = decided[0]
        else:
            chosen = EvidenceGap(
                workspace_id=workspace_id,
                questionnaire_id=questionnaire_id,
                gap_type=gap_type,
                status="open",
                control_id=control_id,
                question_id=question_id,
                reason=(body.reason or "").strip() or "No eligible evidence is linked.",
                evidence_refs="[]",
            )
            try:
                _insert_open_gap(db, chosen)
                status_code = 201
            except IntegrityError:
                again = query.filter(EvidenceGap.status == "open").order_by(EvidenceGap.id).first()
                if again is None:
                    raise HTTPException(status_code=409, detail="Open gap already exists") from None
                chosen = again
                status_code = 200
        if status_code == 201:
            db.commit()
            db.refresh(chosen)
        payload = gap_payload(db, chosen, workspace_id)
        payload["created"] = status_code == 201
        return JSONResponse(content=payload, status_code=status_code)
    except HTTPException:
        db.rollback()
        if key:
            idempotency_release(db, key, owner=owner)
        raise
    except Exception:
        db.rollback()
        if key:
            idempotency_release(db, key, owner=owner)
        raise
    finally:
        if key and "payload" in locals() and isinstance(payload, dict):
            _settle(db, key, owner, status_code, payload)


@router.post("/{gap_id}/decision")
def decide_gap(
    gap_id: int,
    body: DecisionBody,
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_can_admin),
):
    workspace_id = request.state.workspace_id
    key = _idempotency_key(request, workspace_id, "decision", str(gap_id))
    cached, owner = _claim_or_replay(db, key)
    if cached is not None:
        return cached
    try:
        status = body.status
        gap = _gap_in_workspace(db, gap_id, workspace_id)
        if gap.status != "open":
            raise HTTPException(status_code=409, detail="Gap is already decided")
        visible = _visible_evidence_ids(db, workspace_id, gap.evidence_refs)
        gap.evidence_refs = json.dumps(visible)
        gap.status = status
        gap.updated_at = _now()
        db.commit()
        db.refresh(gap)
        payload = gap_payload(db, gap, workspace_id)
        return payload
    except HTTPException:
        db.rollback()
        if key:
            idempotency_release(db, key, owner=owner)
        raise
    except Exception:
        db.rollback()
        if key:
            idempotency_release(db, key, owner=owner)
        raise
    finally:
        if key and "payload" in locals() and isinstance(payload, dict):
            _settle(db, key, owner, 200, payload)


@router.post("/{gap_id}/resolve")
def resolve_gap(
    gap_id: int,
    body: ResolveBody,
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_can_review),
):
    workspace_id = request.state.workspace_id
    key = _idempotency_key(request, workspace_id, "resolve", str(gap_id))
    cached, owner = _claim_or_replay(db, key)
    if cached is not None:
        return cached
    try:
        evidence_id = body.evidence_id
        gap = _gap_in_workspace(db, gap_id, workspace_id)
        if gap.status != "open":
            raise HTTPException(status_code=409, detail="Gap is not open")
        ev = _evidence_in_workspace(db, evidence_id, workspace_id)
        rule = evidence_backs_gap(db, gap, ev, _now())
        if rule is not None:
            raise HTTPException(status_code=400, detail={"rule": rule, "resolved": False})
        visible = _visible_evidence_ids(db, workspace_id, gap.evidence_refs)
        if ev.id not in visible:
            visible.append(ev.id)
        gap.evidence_refs = json.dumps(visible)
        gap.status = "resolved"
        gap.close_reason = CONTROL_CHECK_CLOSE_REASON
        gap.closed_at = _now()
        gap.updated_at = gap.closed_at
        gap.evaluation_state = "clear"
        gap.rule_code = "evidence_qualifies"
        db.commit()
        db.refresh(gap)
        payload = gap_payload(db, gap, workspace_id)
        payload["resolved"] = True
        payload["notified"] = False
        try:
            label = (gap.suggested_evidence_doc_title or gap.reason or "Evidence gap").strip()
            notify_admins(
                db,
                workspace_id,
                "Evidence gap resolved",
                f"{label} ({gap.gap_type})",
                category="success",
                link="/dashboard/compliance-gaps",
            )
            payload["notified"] = True
        except Exception:
            db.rollback()
            payload["notified"] = False
            payload["notification_error"] = "delivery_failed"
        return payload
    except HTTPException:
        db.rollback()
        if key:
            idempotency_release(db, key, owner=owner)
        raise
    except Exception:
        db.rollback()
        if key:
            idempotency_release(db, key, owner=owner)
        raise
    finally:
        if key and "payload" in locals() and isinstance(payload, dict):
            _settle(db, key, owner, 200, payload)
