"""AI Mapping & Governance service — centralized CRUD, retrieval adjustments, and governance logic."""

import logging
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ai_mapping import (
    AIGovernanceSettings,
    ControlEvidenceMapping,
    EvidenceTagMapping,
    FrameworkControlMapping,
    QuestionMappingPreference,
)

logger = logging.getLogger(__name__)

MAX_BOOST_CAP = 0.15


# ---------------------------------------------------------------------------
# Governance settings
# ---------------------------------------------------------------------------

def get_governance_settings(db: Session, workspace_id: int) -> dict:
    row = db.query(AIGovernanceSettings).filter(AIGovernanceSettings.workspace_id == workspace_id).first()
    if not row:
        return _default_governance()
    return _gov_to_dict(row)


def upsert_governance_settings(db: Session, workspace_id: int, data: dict) -> dict:
    row = db.query(AIGovernanceSettings).filter(AIGovernanceSettings.workspace_id == workspace_id).first()
    if not row:
        row = AIGovernanceSettings(workspace_id=workspace_id)
        db.add(row)
    allowed = {
        "require_approved_mappings", "require_approved_ai_tags",
        "minimum_ai_mapping_confidence", "minimum_ai_tag_confidence",
        "manual_mapping_boost", "approved_mapping_boost", "approved_tag_boost",
        "control_match_boost", "framework_match_boost",
        "allow_ai_unapproved_for_retrieval", "allow_manual_overrides",
    }
    for k, v in data.items():
        if k in allowed:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return _gov_to_dict(row)


def _default_governance() -> dict:
    return {
        "require_approved_mappings": False,
        "require_approved_ai_tags": False,
        "minimum_ai_mapping_confidence": None,
        "minimum_ai_tag_confidence": None,
        "manual_mapping_boost": 0.05,
        "approved_mapping_boost": 0.04,
        "approved_tag_boost": 0.03,
        "control_match_boost": 0.04,
        "framework_match_boost": 0.03,
        "allow_ai_unapproved_for_retrieval": True,
        "allow_manual_overrides": True,
    }


def _gov_to_dict(row: AIGovernanceSettings) -> dict:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "require_approved_mappings": row.require_approved_mappings,
        "require_approved_ai_tags": row.require_approved_ai_tags,
        "minimum_ai_mapping_confidence": row.minimum_ai_mapping_confidence,
        "minimum_ai_tag_confidence": row.minimum_ai_tag_confidence,
        "manual_mapping_boost": row.manual_mapping_boost,
        "approved_mapping_boost": row.approved_mapping_boost,
        "approved_tag_boost": row.approved_tag_boost,
        "control_match_boost": row.control_match_boost,
        "framework_match_boost": row.framework_match_boost,
        "allow_ai_unapproved_for_retrieval": row.allow_ai_unapproved_for_retrieval,
        "allow_manual_overrides": row.allow_manual_overrides,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Generic CRUD helpers
# ---------------------------------------------------------------------------

def _safe_create(db: Session, obj) -> Any:
    try:
        db.add(obj)
        db.flush()
        return obj
    except IntegrityError:
        db.rollback()
        return None


def _row_to_dict(row, extra_fields: dict | None = None) -> dict:
    d: dict[str, Any] = {}
    for c in row.__table__.columns:
        val = getattr(row, c.name, None)
        if hasattr(val, "isoformat"):
            val = val.isoformat()
        d[c.name] = val
    if extra_fields:
        d.update(extra_fields)
    return d


# ---------------------------------------------------------------------------
# Framework ↔ Control mappings
# ---------------------------------------------------------------------------

def list_framework_control_mappings(db: Session, workspace_id: int, framework_key: str | None = None) -> list[dict]:
    q = db.query(FrameworkControlMapping).filter(FrameworkControlMapping.workspace_id == workspace_id)
    if framework_key:
        q = q.filter(FrameworkControlMapping.framework_key == framework_key)
    return [_row_to_dict(r) for r in q.order_by(FrameworkControlMapping.framework_key, FrameworkControlMapping.id).all()]


def create_framework_control_mapping(
    db: Session, workspace_id: int, framework_key: str, control_id: int,
    source: str = "manual", confidence: float | None = None, approved: bool = True,
    user_id: int | None = None,
) -> dict | None:
    obj = FrameworkControlMapping(
        workspace_id=workspace_id, framework_key=framework_key, control_id=control_id,
        source=source, confidence=confidence, approved=approved, created_by_user_id=user_id,
    )
    result = _safe_create(db, obj)
    if result:
        db.commit()
        return _row_to_dict(result)
    return None


def delete_framework_control_mapping(db: Session, mapping_id: int, workspace_id: int) -> bool:
    row = db.query(FrameworkControlMapping).filter(
        FrameworkControlMapping.id == mapping_id,
        FrameworkControlMapping.workspace_id == workspace_id,
    ).first()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def approve_framework_control_mapping(db: Session, mapping_id: int, workspace_id: int, approved: bool) -> dict | None:
    row = db.query(FrameworkControlMapping).filter(
        FrameworkControlMapping.id == mapping_id,
        FrameworkControlMapping.workspace_id == workspace_id,
    ).first()
    if not row:
        return None
    row.approved = approved
    db.commit()
    db.refresh(row)
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# Control ↔ Evidence mappings
# ---------------------------------------------------------------------------

def list_control_evidence_mappings(db: Session, workspace_id: int, control_id: int | None = None) -> list[dict]:
    q = db.query(ControlEvidenceMapping).filter(ControlEvidenceMapping.workspace_id == workspace_id)
    if control_id is not None:
        q = q.filter(ControlEvidenceMapping.control_id == control_id)
    return [_row_to_dict(r) for r in q.order_by(ControlEvidenceMapping.id).all()]


def create_control_evidence_mapping(
    db: Session, workspace_id: int, control_id: int, evidence_id: int,
    source: str = "manual", confidence: float | None = None, approved: bool = True,
    override_priority: int | None = None, user_id: int | None = None,
) -> dict | None:
    obj = ControlEvidenceMapping(
        workspace_id=workspace_id, control_id=control_id, evidence_id=evidence_id,
        source=source, confidence=confidence, approved=approved,
        override_priority=override_priority, created_by_user_id=user_id,
    )
    result = _safe_create(db, obj)
    if result:
        db.commit()
        return _row_to_dict(result)
    return None


def delete_control_evidence_mapping(db: Session, mapping_id: int, workspace_id: int) -> bool:
    row = db.query(ControlEvidenceMapping).filter(
        ControlEvidenceMapping.id == mapping_id,
        ControlEvidenceMapping.workspace_id == workspace_id,
    ).first()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def approve_control_evidence_mapping(db: Session, mapping_id: int, workspace_id: int, approved: bool) -> dict | None:
    row = db.query(ControlEvidenceMapping).filter(
        ControlEvidenceMapping.id == mapping_id,
        ControlEvidenceMapping.workspace_id == workspace_id,
    ).first()
    if not row:
        return None
    row.approved = approved
    db.commit()
    db.refresh(row)
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# Evidence ↔ Tag mappings
# ---------------------------------------------------------------------------

def list_evidence_tag_mappings(db: Session, workspace_id: int, evidence_id: int | None = None) -> list[dict]:
    q = db.query(EvidenceTagMapping).filter(EvidenceTagMapping.workspace_id == workspace_id)
    if evidence_id is not None:
        q = q.filter(EvidenceTagMapping.evidence_id == evidence_id)
    return [_row_to_dict(r) for r in q.order_by(EvidenceTagMapping.id).all()]


def create_evidence_tag_mapping(
    db: Session, workspace_id: int, evidence_id: int, tag_id: int,
    source: str = "manual", confidence: float | None = None, approved: bool = True,
    user_id: int | None = None,
) -> dict | None:
    obj = EvidenceTagMapping(
        workspace_id=workspace_id, evidence_id=evidence_id, tag_id=tag_id,
        source=source, confidence=confidence, approved=approved, created_by_user_id=user_id,
    )
    result = _safe_create(db, obj)
    if result:
        db.commit()
        return _row_to_dict(result)
    return None


def delete_evidence_tag_mapping(db: Session, mapping_id: int, workspace_id: int) -> bool:
    row = db.query(EvidenceTagMapping).filter(
        EvidenceTagMapping.id == mapping_id,
        EvidenceTagMapping.workspace_id == workspace_id,
    ).first()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def approve_evidence_tag_mapping(db: Session, mapping_id: int, workspace_id: int, approved: bool) -> dict | None:
    row = db.query(EvidenceTagMapping).filter(
        EvidenceTagMapping.id == mapping_id,
        EvidenceTagMapping.workspace_id == workspace_id,
    ).first()
    if not row:
        return None
    row.approved = approved
    db.commit()
    db.refresh(row)
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# Question mapping preferences
# ---------------------------------------------------------------------------

def list_question_preferences(db: Session, workspace_id: int, questionnaire_id: int | None = None) -> list[dict]:
    q = db.query(QuestionMappingPreference).filter(QuestionMappingPreference.workspace_id == workspace_id)
    if questionnaire_id is not None:
        q = q.filter(QuestionMappingPreference.questionnaire_id == questionnaire_id)
    return [_row_to_dict(r) for r in q.order_by(QuestionMappingPreference.id).all()]


def create_question_preference(
    db: Session, workspace_id: int, *,
    questionnaire_id: int | None = None, question_id: int | None = None,
    normalized_question_text: str | None = None,
    preferred_control_id: int | None = None, preferred_tag_id: int | None = None,
    preferred_framework_key: str | None = None, weight: float | None = None,
    source: str = "manual", confidence: float | None = None, approved: bool = True,
    user_id: int | None = None,
) -> dict | None:
    obj = QuestionMappingPreference(
        workspace_id=workspace_id, questionnaire_id=questionnaire_id,
        question_id=question_id, normalized_question_text=normalized_question_text,
        preferred_control_id=preferred_control_id, preferred_tag_id=preferred_tag_id,
        preferred_framework_key=preferred_framework_key, weight=weight,
        source=source, confidence=confidence, approved=approved,
        created_by_user_id=user_id,
    )
    result = _safe_create(db, obj)
    if result:
        db.commit()
        return _row_to_dict(result)
    return None


def delete_question_preference(db: Session, pref_id: int, workspace_id: int) -> bool:
    row = db.query(QuestionMappingPreference).filter(
        QuestionMappingPreference.id == pref_id,
        QuestionMappingPreference.workspace_id == workspace_id,
    ).first()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def approve_question_preference(db: Session, pref_id: int, workspace_id: int, approved: bool) -> dict | None:
    row = db.query(QuestionMappingPreference).filter(
        QuestionMappingPreference.id == pref_id,
        QuestionMappingPreference.workspace_id == workspace_id,
    ).first()
    if not row:
        return None
    row.approved = approved
    db.commit()
    db.refresh(row)
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# Retrieval boost calculation
# ---------------------------------------------------------------------------

def compute_retrieval_adjustments(
    db: Session,
    workspace_id: int,
    question_text: str,
    candidate_evidence: list[dict],
    question_id: int | None = None,
) -> dict[int, float]:
    """Given candidate evidence chunks, return {evidence_id/chunk_id: additive_boost}.

    Gracefully returns empty dict if no mappings exist. Never crashes retrieval.
    """
    try:
        return _compute_adjustments_inner(db, workspace_id, question_text, candidate_evidence, question_id)
    except Exception:
        logger.warning("compute_retrieval_adjustments failed, returning empty adjustments", exc_info=True)
        return {}


def _compute_adjustments_inner(
    db: Session,
    workspace_id: int,
    question_text: str,
    candidate_evidence: list[dict],
    question_id: int | None,
) -> dict[int, float]:
    gov = get_governance_settings(db, workspace_id)

    prefs = db.query(QuestionMappingPreference).filter(
        QuestionMappingPreference.workspace_id == workspace_id,
    )
    if question_id:
        prefs = prefs.filter(QuestionMappingPreference.question_id == question_id)
    pref_rows = prefs.all()

    if not pref_rows:
        return {}

    preferred_control_ids: set[int] = set()
    preferred_framework_keys: set[str] = set()
    preferred_tag_ids: set[int] = set()

    for p in pref_rows:
        if not _passes_governance(p, gov):
            continue
        if p.preferred_control_id:
            preferred_control_ids.add(p.preferred_control_id)
        if p.preferred_framework_key:
            preferred_framework_keys.add(p.preferred_framework_key)
        if p.preferred_tag_id:
            preferred_tag_ids.add(p.preferred_tag_id)

    if not preferred_control_ids and not preferred_framework_keys and not preferred_tag_ids:
        return {}

    evidence_ids = [e.get("id") for e in candidate_evidence if e.get("id") is not None]
    if not evidence_ids:
        return {}

    ce_mappings = db.query(ControlEvidenceMapping).filter(
        ControlEvidenceMapping.workspace_id == workspace_id,
        ControlEvidenceMapping.evidence_id.in_(evidence_ids),
    ).all()

    fc_mappings = db.query(FrameworkControlMapping).filter(
        FrameworkControlMapping.workspace_id == workspace_id,
    ).all() if preferred_framework_keys else []

    et_mappings = db.query(EvidenceTagMapping).filter(
        EvidenceTagMapping.workspace_id == workspace_id,
        EvidenceTagMapping.evidence_id.in_(evidence_ids),
    ).all() if preferred_tag_ids else []

    ev_to_controls: dict[int, set[int]] = {}
    for m in ce_mappings:
        if not _passes_governance(m, gov):
            continue
        ev_to_controls.setdefault(m.evidence_id, set()).add(m.control_id)

    fw_controls: set[int] = set()
    for m in fc_mappings:
        if not _passes_governance(m, gov):
            continue
        if m.framework_key in preferred_framework_keys:
            fw_controls.add(m.control_id)

    ev_to_tags: dict[int, set[int]] = {}
    for m in et_mappings:
        if not _passes_governance(m, gov):
            continue
        ev_to_tags.setdefault(m.evidence_id, set()).add(m.tag_id)

    adjustments: dict[int, float] = {}
    for eid in evidence_ids:
        boost = 0.0
        ctrl_ids = ev_to_controls.get(eid, set())
        if ctrl_ids & preferred_control_ids:
            boost += gov.get("control_match_boost", 0.04)
        if ctrl_ids & fw_controls:
            boost += gov.get("framework_match_boost", 0.03)
        tag_ids = ev_to_tags.get(eid, set())
        if tag_ids & preferred_tag_ids:
            boost += gov.get("approved_tag_boost", 0.03)
        for m in ce_mappings:
            if m.evidence_id == eid and m.source == "manual" and _passes_governance(m, gov):
                boost += gov.get("manual_mapping_boost", 0.05)
                break
        if boost > 0:
            adjustments[eid] = min(boost, MAX_BOOST_CAP)

    return adjustments


def _passes_governance(mapping, gov: dict) -> bool:
    if gov.get("require_approved_mappings") and not mapping.approved:
        return False
    if not gov.get("allow_ai_unapproved_for_retrieval", True):
        if mapping.source == "ai" and not mapping.approved:
            return False
    min_conf = gov.get("minimum_ai_mapping_confidence")
    if min_conf and mapping.source == "ai" and mapping.confidence is not None:
        if mapping.confidence < min_conf:
            return False
    return True


# ---------------------------------------------------------------------------
# AI suggestion helpers
# ---------------------------------------------------------------------------

def suggest_framework_control_mappings(db: Session, workspace_id: int) -> list[dict]:
    """Infer framework ↔ control mappings from existing workspace controls metadata."""
    from app.models import WorkspaceControl, FrameworkControl
    wcs = db.query(WorkspaceControl).filter(WorkspaceControl.workspace_id == workspace_id).all()
    created = []
    for wc in wcs:
        fc = db.query(FrameworkControl).filter(FrameworkControl.id == wc.framework_control_id).first()
        if not fc:
            continue
        from app.models import Framework
        fw = db.query(Framework).filter(Framework.id == fc.framework_id).first()
        if not fw:
            continue
        fw_key = fw.name
        existing = db.query(FrameworkControlMapping).filter(
            FrameworkControlMapping.workspace_id == workspace_id,
            FrameworkControlMapping.framework_key == fw_key,
            FrameworkControlMapping.control_id == wc.id,
        ).first()
        if existing:
            continue
        obj = FrameworkControlMapping(
            workspace_id=workspace_id, framework_key=fw_key, control_id=wc.id,
            source="ai", confidence=0.8, approved=False,
        )
        _safe_create(db, obj)
        created.append(_row_to_dict(obj))
    if created:
        db.commit()
    return created


def suggest_control_evidence_mappings(db: Session, workspace_id: int) -> list[dict]:
    """Infer control ↔ evidence from existing ControlEvidenceLink rows."""
    from app.models import ControlEvidenceLink, EvidenceItem, WorkspaceControl
    links = db.query(ControlEvidenceLink).join(
        EvidenceItem, ControlEvidenceLink.evidence_id == EvidenceItem.id
    ).filter(EvidenceItem.workspace_id == workspace_id).all()
    created = []
    for link in links:
        existing = db.query(ControlEvidenceMapping).filter(
            ControlEvidenceMapping.workspace_id == workspace_id,
            ControlEvidenceMapping.control_id == link.control_id,
            ControlEvidenceMapping.evidence_id == link.evidence_id,
        ).first()
        if existing:
            continue
        conf = link.confidence_score if link.confidence_score else 0.7
        obj = ControlEvidenceMapping(
            workspace_id=workspace_id, control_id=link.control_id, evidence_id=link.evidence_id,
            source="ai", confidence=conf, approved=bool(link.verified),
        )
        _safe_create(db, obj)
        created.append(_row_to_dict(obj))
    if created:
        db.commit()
    return created


def suggest_evidence_tag_mappings(db: Session, workspace_id: int) -> list[dict]:
    """Infer evidence ↔ tag from existing DocumentTag rows."""
    from app.models import DocumentTag, EvidenceItem
    evidence = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == workspace_id).all()
    created = []
    for ev in evidence:
        if not ev.document_id:
            continue
        doc_tags = db.query(DocumentTag).filter(
            DocumentTag.document_id == ev.document_id,
            DocumentTag.workspace_id == workspace_id,
        ).all()
        for dt in doc_tags:
            existing = db.query(EvidenceTagMapping).filter(
                EvidenceTagMapping.workspace_id == workspace_id,
                EvidenceTagMapping.evidence_id == ev.id,
                EvidenceTagMapping.tag_id == dt.tag_id,
            ).first()
            if existing:
                continue
            obj = EvidenceTagMapping(
                workspace_id=workspace_id, evidence_id=ev.id, tag_id=dt.tag_id,
                source="ai", confidence=dt.confidence or 0.7, approved=dt.approved,
            )
            _safe_create(db, obj)
            created.append(_row_to_dict(obj))
    if created:
        db.commit()
    return created
