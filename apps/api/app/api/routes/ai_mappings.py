"""AI Mapping admin API — framework/control/evidence/tag/question mappings and governance."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import persist_audit
from app.core.auth_deps import require_can_admin, require_can_review
from app.core.database import get_db
from app.services import ai_mapping_service as svc
from app.services.pipeline_stats import get_workspace_ai_pipeline_stats
from app.services.answer_stats import get_questionnaire_answer_stats, get_workspace_gap_analytics
from app.services.workspace_usage import get_usage as get_workspace_usage

router = APIRouter(prefix="/ai-mappings", tags=["ai-mappings"])
gov_router = APIRouter(prefix="/ai-governance", tags=["ai-governance"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class FrameworkControlBody(BaseModel):
    framework_key: str
    control_id: int
    source: str = "manual"
    confidence: float | None = None
    approved: bool = True


class ControlEvidenceBody(BaseModel):
    control_id: int
    evidence_id: int
    source: str = "manual"
    confidence: float | None = None
    approved: bool = True
    override_priority: int | None = None


class EvidenceTagBody(BaseModel):
    evidence_id: int
    tag_id: int
    source: str = "manual"
    confidence: float | None = None
    approved: bool = True


class QuestionPrefBody(BaseModel):
    questionnaire_id: int | None = None
    question_id: int | None = None
    normalized_question_text: str | None = None
    preferred_control_id: int | None = None
    preferred_tag_id: int | None = None
    preferred_framework_key: str | None = None
    weight: float | None = None
    source: str = "manual"
    confidence: float | None = None
    approved: bool = True


class ApproveBody(BaseModel):
    approved: bool


class GovernanceBody(BaseModel):
    require_approved_mappings: bool | None = None
    require_approved_ai_tags: bool | None = None
    minimum_ai_mapping_confidence: float | None = None
    minimum_ai_tag_confidence: float | None = None
    manual_mapping_boost: float | None = None
    approved_mapping_boost: float | None = None
    approved_tag_boost: float | None = None
    control_match_boost: float | None = None
    framework_match_boost: float | None = None
    allow_ai_unapproved_for_retrieval: bool | None = None
    allow_manual_overrides: bool | None = None


# ---------------------------------------------------------------------------
# Framework ↔ Controls
# ---------------------------------------------------------------------------

@router.get("/framework-controls")
def list_framework_controls(
    framework_key: str | None = Query(None),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    return svc.list_framework_control_mappings(db, ws, framework_key)


@router.post("/framework-controls")
def create_framework_control(
    body: FrameworkControlBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    result = svc.create_framework_control_mapping(
        db, ws, body.framework_key, body.control_id,
        source=body.source, confidence=body.confidence, approved=body.approved,
        user_id=session.get("user_id"),
    )
    if not result:
        raise HTTPException(status_code=400, detail="Mapping already exists")
    persist_audit(db, "ai_mapping.framework_control.created", user_id=session.get("user_id"),
                  email=session.get("email"), workspace_id=ws,
                  resource_type="framework_control_mapping", resource_id=result["id"])
    return result


@router.delete("/framework-controls/{mapping_id}")
def delete_framework_control(
    mapping_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    if not svc.delete_framework_control_mapping(db, mapping_id, ws):
        raise HTTPException(status_code=404, detail="Not found")
    persist_audit(db, "ai_mapping.framework_control.deleted", user_id=session.get("user_id"),
                  email=session.get("email"), workspace_id=ws,
                  resource_type="framework_control_mapping", resource_id=mapping_id)
    return {"ok": True}


@router.patch("/framework-controls/{mapping_id}/approve")
def approve_framework_control(
    mapping_id: int,
    body: ApproveBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    result = svc.approve_framework_control_mapping(db, mapping_id, ws, body.approved)
    if not result:
        raise HTTPException(status_code=404, detail="Not found")
    action = "approved" if body.approved else "rejected"
    persist_audit(db, f"ai_mapping.framework_control.{action}", user_id=session.get("user_id"),
                  email=session.get("email"), workspace_id=ws,
                  resource_type="framework_control_mapping", resource_id=mapping_id)
    return result


# ---------------------------------------------------------------------------
# Control ↔ Evidence
# ---------------------------------------------------------------------------

@router.get("/control-evidence")
def list_control_evidence(
    control_id: int | None = Query(None),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    return svc.list_control_evidence_mappings(db, ws, control_id)


@router.post("/control-evidence")
def create_control_evidence(
    body: ControlEvidenceBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    result = svc.create_control_evidence_mapping(
        db, ws, body.control_id, body.evidence_id,
        source=body.source, confidence=body.confidence, approved=body.approved,
        override_priority=body.override_priority, user_id=session.get("user_id"),
    )
    if not result:
        raise HTTPException(status_code=400, detail="Mapping already exists")
    persist_audit(db, "ai_mapping.control_evidence.created", user_id=session.get("user_id"),
                  email=session.get("email"), workspace_id=ws,
                  resource_type="control_evidence_mapping", resource_id=result["id"])
    return result


@router.delete("/control-evidence/{mapping_id}")
def delete_control_evidence(
    mapping_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    if not svc.delete_control_evidence_mapping(db, mapping_id, ws):
        raise HTTPException(status_code=404, detail="Not found")
    persist_audit(db, "ai_mapping.control_evidence.deleted", user_id=session.get("user_id"),
                  email=session.get("email"), workspace_id=ws,
                  resource_type="control_evidence_mapping", resource_id=mapping_id)
    return {"ok": True}


@router.patch("/control-evidence/{mapping_id}/approve")
def approve_control_evidence(
    mapping_id: int,
    body: ApproveBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    result = svc.approve_control_evidence_mapping(db, mapping_id, ws, body.approved)
    if not result:
        raise HTTPException(status_code=404, detail="Not found")
    action = "approved" if body.approved else "rejected"
    persist_audit(db, f"ai_mapping.control_evidence.{action}", user_id=session.get("user_id"),
                  email=session.get("email"), workspace_id=ws,
                  resource_type="control_evidence_mapping", resource_id=mapping_id)
    return result


# ---------------------------------------------------------------------------
# Evidence ↔ Tags
# ---------------------------------------------------------------------------

@router.get("/evidence-tags")
def list_evidence_tags(
    evidence_id: int | None = Query(None),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    return svc.list_evidence_tag_mappings(db, ws, evidence_id)


@router.post("/evidence-tags")
def create_evidence_tag(
    body: EvidenceTagBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    result = svc.create_evidence_tag_mapping(
        db, ws, body.evidence_id, body.tag_id,
        source=body.source, confidence=body.confidence, approved=body.approved,
        user_id=session.get("user_id"),
    )
    if not result:
        raise HTTPException(status_code=400, detail="Mapping already exists")
    persist_audit(db, "ai_mapping.evidence_tag.created", user_id=session.get("user_id"),
                  email=session.get("email"), workspace_id=ws,
                  resource_type="evidence_tag_mapping", resource_id=result["id"])
    return result


@router.delete("/evidence-tags/{mapping_id}")
def delete_evidence_tag(
    mapping_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    if not svc.delete_evidence_tag_mapping(db, mapping_id, ws):
        raise HTTPException(status_code=404, detail="Not found")
    persist_audit(db, "ai_mapping.evidence_tag.deleted", user_id=session.get("user_id"),
                  email=session.get("email"), workspace_id=ws,
                  resource_type="evidence_tag_mapping", resource_id=mapping_id)
    return {"ok": True}


@router.patch("/evidence-tags/{mapping_id}/approve")
def approve_evidence_tag(
    mapping_id: int,
    body: ApproveBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    result = svc.approve_evidence_tag_mapping(db, mapping_id, ws, body.approved)
    if not result:
        raise HTTPException(status_code=404, detail="Not found")
    action = "approved" if body.approved else "rejected"
    persist_audit(db, f"ai_mapping.evidence_tag.{action}", user_id=session.get("user_id"),
                  email=session.get("email"), workspace_id=ws,
                  resource_type="evidence_tag_mapping", resource_id=mapping_id)
    return result


# ---------------------------------------------------------------------------
# Question preferences
# ---------------------------------------------------------------------------

@router.get("/question-preferences")
def list_question_prefs(
    questionnaire_id: int | None = Query(None),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    return svc.list_question_preferences(db, ws, questionnaire_id)


@router.post("/question-preferences")
def create_question_pref(
    body: QuestionPrefBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    result = svc.create_question_preference(
        db, ws,
        questionnaire_id=body.questionnaire_id, question_id=body.question_id,
        normalized_question_text=body.normalized_question_text,
        preferred_control_id=body.preferred_control_id,
        preferred_tag_id=body.preferred_tag_id,
        preferred_framework_key=body.preferred_framework_key,
        weight=body.weight, source=body.source, confidence=body.confidence,
        approved=body.approved, user_id=session.get("user_id"),
    )
    if not result:
        raise HTTPException(status_code=400, detail="Failed to create preference")
    persist_audit(db, "ai_mapping.question_pref.created", user_id=session.get("user_id"),
                  email=session.get("email"), workspace_id=ws,
                  resource_type="question_mapping_preference", resource_id=result["id"])
    return result


@router.delete("/question-preferences/{pref_id}")
def delete_question_pref(
    pref_id: int,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    if not svc.delete_question_preference(db, pref_id, ws):
        raise HTTPException(status_code=404, detail="Not found")
    persist_audit(db, "ai_mapping.question_pref.deleted", user_id=session.get("user_id"),
                  email=session.get("email"), workspace_id=ws,
                  resource_type="question_mapping_preference", resource_id=pref_id)
    return {"ok": True}


@router.patch("/question-preferences/{pref_id}/approve")
def approve_question_pref(
    pref_id: int,
    body: ApproveBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    result = svc.approve_question_preference(db, pref_id, ws, body.approved)
    if not result:
        raise HTTPException(status_code=404, detail="Not found")
    action = "approved" if body.approved else "rejected"
    persist_audit(db, f"ai_mapping.question_pref.{action}", user_id=session.get("user_id"),
                  email=session.get("email"), workspace_id=ws,
                  resource_type="question_mapping_preference", resource_id=pref_id)
    return result


# ---------------------------------------------------------------------------
# AI suggestions (generate mappings from existing data)
# ---------------------------------------------------------------------------

@router.post("/suggest/framework-controls")
def suggest_framework_controls(
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    created = svc.suggest_framework_control_mappings(db, ws)
    persist_audit(db, "ai_mapping.suggest.framework_controls", user_id=session.get("user_id"),
                  email=session.get("email"), workspace_id=ws,
                  details={"created": len(created)})
    return {"created": len(created), "mappings": created}


@router.post("/suggest/control-evidence")
def suggest_control_evidence(
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    created = svc.suggest_control_evidence_mappings(db, ws)
    persist_audit(db, "ai_mapping.suggest.control_evidence", user_id=session.get("user_id"),
                  email=session.get("email"), workspace_id=ws,
                  details={"created": len(created)})
    return {"created": len(created), "mappings": created}


@router.post("/suggest/evidence-tags")
def suggest_evidence_tags(
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    created = svc.suggest_evidence_tag_mappings(db, ws)
    persist_audit(db, "ai_mapping.suggest.evidence_tags", user_id=session.get("user_id"),
                  email=session.get("email"), workspace_id=ws,
                  details={"created": len(created)})
    return {"created": len(created), "mappings": created}


# ---------------------------------------------------------------------------
# Pipeline statistics (admin — workspace-scoped)
# ---------------------------------------------------------------------------


@gov_router.get("/pipeline-stats")
def pipeline_stats(
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Questionnaires, mappings, evidence coverage, and blindspot-style counts for this workspace."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    return get_workspace_ai_pipeline_stats(db, ws)


# ---------------------------------------------------------------------------
# Answer stats per questionnaire (admin/reviewer)
# ---------------------------------------------------------------------------


@gov_router.get("/questionnaire-answer-stats/{qnr_id}")
def questionnaire_answer_stats(
    qnr_id: int,
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Answer outcome breakdown for one questionnaire: draft, insufficient, skipped, by category."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    return get_questionnaire_answer_stats(db, ws, qnr_id)


# ---------------------------------------------------------------------------
# Gap analytics — category-level aggregation (admin)
# ---------------------------------------------------------------------------


@gov_router.get("/gap-analytics")
def gap_analytics(
    group_by: str = Query("subject", pattern="^(subject|framework)$"),
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Aggregate insufficient answers by subject or framework category for chart display."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    return get_workspace_gap_analytics(db, ws, group_by=group_by)


# ---------------------------------------------------------------------------
# Workspace AI usage (admin)
# ---------------------------------------------------------------------------


@gov_router.get("/usage")
def workspace_usage(
    period: str | None = Query(None),
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Current period AI usage counters for this workspace."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    return get_workspace_usage(db, ws, period)


# ---------------------------------------------------------------------------
# Governance settings
# ---------------------------------------------------------------------------

@gov_router.get("/settings")
def get_governance(
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    return svc.get_governance_settings(db, ws)


@gov_router.patch("/settings")
def update_governance(
    body: GovernanceBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    data = body.model_dump(exclude_none=True)
    result = svc.upsert_governance_settings(db, ws, data)
    persist_audit(db, "ai_governance.settings.updated", user_id=session.get("user_id"),
                  email=session.get("email"), workspace_id=ws,
                  details=data)
    return result
