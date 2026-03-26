"""Questionnaire API (QNR-01, QNR-02, QNR-13, AI-05)."""

import json
import os
import re
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.schemas import BulkDeleteBody, MetadataUpdateBody
from app.core.audit import audit_log
from app.core.config import get_settings
from app.core.auth_deps import require_can_edit, require_can_review, require_session
from app.core.database import get_db
from app.models import Answer, Document, ExportRecord, Framework, FrameworkControl, Job, JobStatus, Question, Questionnaire, WorkspaceControl
from app.models.ai_mapping import QuestionMappingPreference
from app.services.compliance_hooks import (
    get_mapping_timing_snapshot,
    match_keywords_for_mapping_row,
    mapping_timing_enabled,
    reset_mapping_timing,
)
from app.services.mapping_llm_rerank import get_rerank_perf_snapshot, reset_rerank_perf_stats
from app.services.file_service import FileService
from app.services.questionnaire_mapping_evidence import (
    batch_supporting_evidence_for_workspace_controls,
    suggest_documents_for_mapping_review,
)
from app.services.questionnaire_answer_evidence import validate_answer_evidence_document_ids
from app.services.registry_metadata import (
    FRAMEWORK_LABELS,
    SUBJECT_AREA_LABELS,
    build_display_id,
    normalize_labels,
    parse_json_list,
    to_json,
)
from app.services.registry_lifecycle import (
    build_delete_preview,
    restore_record,
    soft_delete_record,
    update_metadata_json_fields,
)
from app.services.storage import get_storage, StorageClient
from app.services.mapping_llm_classify import classify_and_persist as classify_question_signal, _preload_existing_signals, _classify_one_thread_safe, _PARALLEL_WORKERS
from app.services.workspace_usage import record_mapping_calls

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/questionnaires", tags=["questionnaires"])


def _answer_evidence_payload(db: Session, workspace_id: int, qnr: Questionnaire) -> dict:
    """IDs + filenames for answer-evidence scoping (AI may only use these documents when drafting answers)."""
    raw_ids: list = []
    if getattr(qnr, "answer_evidence_document_ids_json", None):
        try:
            raw_ids = json.loads(qnr.answer_evidence_document_ids_json)
        except Exception:
            raw_ids = []
    if not isinstance(raw_ids, list):
        raw_ids = []
    validated = validate_answer_evidence_document_ids(db, workspace_id, qnr.id, raw_ids)
    docs_out: list[dict] = []
    for did in validated:
        d = db.query(Document).filter(Document.id == did).first()
        if d:
            docs_out.append({"id": d.id, "filename": d.filename})
    return {
        "answer_evidence_document_ids": validated,
        "answer_evidence_documents": docs_out,
    }


def get_file_service(storage: StorageClient = Depends(get_storage)) -> FileService:
    return FileService(storage)


@router.post("/upload")
def upload_questionnaire(
    workspace_id: int = Form(...),
    file: UploadFile = ...,
    frameworks: str = Form(""),
    subject_areas: str = Form(""),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
    file_svc: FileService = Depends(get_file_service),
):
    """Upload questionnaire file (QNR-01). Enqueues parse job (QNR-13)."""
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    key, filename = file_svc.upload_raw(workspace_id, file)

    fw_list = [f.strip() for f in frameworks.split(",") if f.strip()] or ["Other"]
    sa_list = [s.strip() for s in subject_areas.split(",") if s.strip()] or ["Other"]

    qnr = Questionnaire(
        workspace_id=workspace_id,
        storage_key=key,
        filename=filename,
        frameworks_json=json.dumps(fw_list),
        subject_areas_json=json.dumps(sa_list),
        status="uploaded",
    )
    db.add(qnr)
    db.flush()
    qnr.display_id = build_display_id("questionnaire", qnr.id)
    db.commit()
    db.refresh(qnr)
    job = Job(
        workspace_id=workspace_id,
        kind="parse_questionnaire",
        status=JobStatus.QUEUED.value,
        payload=json.dumps({"questionnaire_id": qnr.id, "storage_key": key}),
    )
    db.add(job)
    db.commit()
    audit_log("questionnaire.upload", email=session.get("email"), workspace_id=workspace_id, resource_type="questionnaire", resource_id=qnr.id, details={"filename": qnr.filename})
    return {"id": qnr.id, "display_id": qnr.display_id, "filename": qnr.filename, "status": qnr.status, "job_id": job.id}


_SEARCH_QUERY_MAX_LEN = 200


def _list_questionnaires_impl(
    workspace_id: int,
    session: dict,
    db: Session,
    search_q: str | None = None,
    framework: str | None = None,
    subject_area: str | None = None,
    status: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    archived: str | None = None,
):
    """Shared implementation for list questionnaires (QNR-02). Optional search_q filters by filename substring."""
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    query = db.query(Questionnaire).filter(Questionnaire.workspace_id == workspace_id)
    mode = (archived or "active").strip().lower()
    if mode == "active":
        query = query.filter(Questionnaire.deleted_at.is_(None))
    elif mode == "only":
        query = query.filter(Questionnaire.deleted_at.is_not(None))
    if search_q and (q_strip := search_q.strip()[: _SEARCH_QUERY_MAX_LEN]):
        like = f"%{q_strip}%"
        query = query.filter(
            Questionnaire.filename.ilike(like)
            | Questionnaire.display_id.ilike(like)
            | Questionnaire.status.ilike(like)
            | Questionnaire.frameworks_json.ilike(like)
            | Questionnaire.subject_areas_json.ilike(like)
        )
    if framework:
        query = query.filter(Questionnaire.frameworks_json.ilike(f"%{framework.strip()}%"))
    if subject_area:
        query = query.filter(Questionnaire.subject_areas_json.ilike(f"%{subject_area.strip()}%"))
    if status:
        query = query.filter(Questionnaire.status == status)
    if created_from:
        try:
            query = query.filter(Questionnaire.created_at >= datetime.fromisoformat(created_from))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid created_from datetime")
    if created_to:
        try:
            query = query.filter(Questionnaire.created_at <= datetime.fromisoformat(created_to))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid created_to datetime")

    qnrs = query.order_by(Questionnaire.created_at.desc(), Questionnaire.id.desc()).all()
    return [
        {
            "id": q.id,
            "display_id": q.display_id or build_display_id("questionnaire", q.id),
            "filename": q.filename,
            "status": q.status,
            "parse_metadata": q.parse_metadata,
            "created_at": q.created_at.isoformat() if q.created_at else None,
            "deleted_at": q.deleted_at.isoformat() if q.deleted_at else None,
            "frameworks": normalize_labels(parse_json_list(q.frameworks_json), allowed=FRAMEWORK_LABELS),
            "subject_areas": normalize_labels(parse_json_list(q.subject_areas_json), allowed=SUBJECT_AREA_LABELS),
        }
        for q in qnrs
    ]


@router.get("/")
@router.get("")
def list_questionnaires(
    workspace_id: int,
    q: str | None = Query(None, description="Filter by filename (case-insensitive substring)"),
    search: str | None = Query(None, description="Search by display id, filename, framework, subject, status"),
    framework: str | None = Query(None),
    subject_area: str | None = Query(None),
    status: str | None = Query(None),
    created_from: str | None = Query(None),
    created_to: str | None = Query(None),
    archived: str | None = Query(None, description="active|include|only"),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """List questionnaires (QNR-02). Optional q filters by filename substring. Accepts with or without trailing slash."""
    return _list_questionnaires_impl(
        workspace_id,
        session,
        db,
        search_q=search or q,
        framework=framework,
        subject_area=subject_area,
        status=status,
        created_from=created_from,
        created_to=created_to,
        archived=archived,
    )



@router.get("/{qnr_id}")
def get_questionnaire(
    qnr_id: int,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Get single questionnaire (QNR-02)."""
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    qnr = db.query(Questionnaire).filter(
        Questionnaire.id == qnr_id,
        Questionnaire.workspace_id == workspace_id,
        Questionnaire.deleted_at.is_(None),
    ).first()
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    questions = db.query(Question).filter(Question.questionnaire_id == qnr_id).all()
    qids = [q.id for q in questions]
    answers = {a.question_id: a for a in db.query(Answer).filter(Answer.question_id.in_(qids)).all()} if qids else {}
    _log.info(
        "API: questionnaire fetched questionnaire_id=%s workspace_id=%s questions=%s answers=%s",
        qnr_id,
        workspace_id,
        len(questions),
        len(answers),
    )
    return {
        "id": qnr.id,
        "display_id": qnr.display_id or build_display_id("questionnaire", qnr.id),
        "document_id": qnr.document_id,
        "filename": qnr.filename,
        "status": qnr.status,
        "parse_metadata": qnr.parse_metadata,
        "frameworks": normalize_labels(parse_json_list(qnr.frameworks_json), allowed=FRAMEWORK_LABELS),
        "subject_areas": normalize_labels(parse_json_list(qnr.subject_areas_json), allowed=SUBJECT_AREA_LABELS),
        "questions": [
            {
                "id": q.id,
                "text": q.text,
                "section": q.section,
                "answer_type": q.answer_type,
                "source_location": q.source_location,
                "answer": (
                    {
                        "id": answers[q.id].id,
                        "text": answers[q.id].text,
                        "status": answers[q.id].status,
                        "citations": answers[q.id].citations,
                    }
                    if q.id in answers else None
                ),
            }
            for q in questions
        ],
        "created_at": qnr.created_at.isoformat() if qnr.created_at else None,
        "mapping_preferred_subject_areas": _mapping_subject_areas_response(qnr),
        **_answer_evidence_payload(db, workspace_id, qnr),
    }


def _normalize_mapping_subject_areas(raw: list[str]) -> list[str]:
    """Canonical subject-area labels for AI category mapping (soft rank for control suggestions)."""
    allowed = set(SUBJECT_AREA_LABELS)
    out: list[str] = []
    for x in raw or []:
        s = str(x).strip()
        if s in allowed and s not in out:
            out.append(s)
        if len(out) >= 24:
            break
    return out


def _mapping_subject_areas_response(qnr: Questionnaire) -> list[str]:
    raw = getattr(qnr, "mapping_preferred_subject_areas_json", None)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        return _normalize_mapping_subject_areas([str(x) for x in data])
    except Exception:
        return []


class MappingPreferenceBody(BaseModel):
    mapping_preferred_subject_areas: list[str] = Field(default_factory=list)


class AnswerEvidenceBody(BaseModel):
    document_ids: list[int] = Field(default_factory=list)


@router.patch("/{qnr_id}/answer-evidence")
def update_questionnaire_answer_evidence(
    qnr_id: int,
    body: AnswerEvidenceBody,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    """Restrict draft-answer generation to specific workspace documents (truthfulness / source isolation)."""
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    qnr = db.query(Questionnaire).filter(
        Questionnaire.id == qnr_id,
        Questionnaire.workspace_id == workspace_id,
        Questionnaire.deleted_at.is_(None),
    ).first()
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    validated = validate_answer_evidence_document_ids(db, workspace_id, qnr_id, body.document_ids or [])
    qnr.answer_evidence_document_ids_json = json.dumps(validated) if validated else None
    qnr.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(qnr)
    audit_log(
        "questionnaire.answer_evidence_update",
        email=session.get("email"),
        workspace_id=workspace_id,
        resource_type="questionnaire",
        resource_id=qnr_id,
        details={"document_ids": validated},
    )
    return _answer_evidence_payload(db, workspace_id, qnr)


@router.patch("/{qnr_id}/mapping-preference")
def update_questionnaire_mapping_preference(
    qnr_id: int,
    body: MappingPreferenceBody,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    """Set subject-area preferences for AI mapping (categories align with evidence subject tags, not frameworks)."""
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    qnr = db.query(Questionnaire).filter(
        Questionnaire.id == qnr_id,
        Questionnaire.workspace_id == workspace_id,
        Questionnaire.deleted_at.is_(None),
    ).first()
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    areas = _normalize_mapping_subject_areas(body.mapping_preferred_subject_areas)
    qnr.mapping_preferred_subject_areas_json = json.dumps(areas) if areas else None
    qnr.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(qnr)
    audit_log(
        "questionnaire.mapping_preference_update",
        email=session.get("email"),
        workspace_id=workspace_id,
        resource_type="questionnaire",
        resource_id=qnr_id,
        details={"mapping_preferred_subject_areas": areas},
    )
    return {"ok": True, "mapping_preferred_subject_areas": _mapping_subject_areas_response(qnr)}


@router.post("/bulk-delete")
def bulk_delete_questionnaires(
    body: BulkDeleteBody,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    """Bulk soft-delete questionnaires. Only active (non-archived) records in workspace are processed."""
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if not body.ids:
        return {"deleted": 0, "errors": []}
    qnrs = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id.in_(body.ids),
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_(None),
        )
        .all()
    )
    for qnr in qnrs:
        soft_delete_record(qnr, session.get("user_id"))
        audit_log(
            "questionnaire.soft_delete",
            email=session.get("email"),
            workspace_id=workspace_id,
            resource_type="questionnaire",
            resource_id=qnr.id,
            details={"display_id": qnr.display_id},
        )
    db.commit()
    return {"deleted": len(qnrs), "errors": []}


@router.delete("/{qnr_id}")
def delete_questionnaire(
    qnr_id: int,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    qnr = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id == qnr_id,
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_(None),
        )
        .first()
    )
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")

    preview = build_delete_preview("questionnaire", db, workspace_id, qnr_id)
    soft_delete_record(qnr, session.get("user_id"))
    db.commit()
    audit_log(
        "questionnaire.soft_delete",
        email=session.get("email"),
        workspace_id=workspace_id,
        resource_type="questionnaire",
        resource_id=qnr_id,
        details={"display_id": qnr.display_id, "dependencies": preview.dependencies},
    )
    return {"ok": True, "id": qnr.id, "display_id": qnr.display_id or build_display_id("questionnaire", qnr.id), "dependencies": preview.dependencies}


@router.get("/{qnr_id}/delete-preview")
def delete_preview_questionnaire(
    qnr_id: int,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    qnr = db.query(Questionnaire).filter(Questionnaire.id == qnr_id, Questionnaire.workspace_id == workspace_id).first()
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    preview = build_delete_preview("questionnaire", db, workspace_id, qnr_id)
    return {
        "id": qnr.id,
        "display_id": qnr.display_id or preview.display_id,
        "can_delete": preview.can_delete,
        "recommended_action": preview.recommended_action,
        "warnings": preview.warnings,
        "dependencies": preview.dependencies,
        "unmodeled_warning": preview.unmodeled_warning,
    }


@router.post("/{qnr_id}/restore")
def restore_questionnaire(
    qnr_id: int,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    qnr = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id == qnr_id,
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_not(None),
        )
        .first()
    )
    if not qnr:
        raise HTTPException(status_code=404, detail="Archived questionnaire not found")
    restore_record(qnr)
    db.commit()
    audit_log(
        "questionnaire.restore",
        email=session.get("email"),
        workspace_id=workspace_id,
        resource_type="questionnaire",
        resource_id=qnr_id,
        details={"display_id": qnr.display_id},
    )
    return {"ok": True, "id": qnr.id, "display_id": qnr.display_id}


@router.patch("/{qnr_id}/metadata")
def update_questionnaire_metadata(
    qnr_id: int,
    body: MetadataUpdateBody,
    workspace_id: int = Query(...),
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    if session.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=403, detail="Access denied")
    qnr = (
        db.query(Questionnaire)
        .filter(
            Questionnaire.id == qnr_id,
            Questionnaire.workspace_id == workspace_id,
        )
        .first()
    )
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    update_metadata_json_fields(qnr, body.frameworks, body.subject_areas)
    db.commit()
    audit_log(
        "questionnaire.metadata_update",
        email=session.get("email"),
        workspace_id=workspace_id,
        resource_type="questionnaire",
        resource_id=qnr_id,
        details={"display_id": qnr.display_id, "frameworks": body.frameworks, "subject_areas": body.subject_areas},
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Questionnaire Mapping Endpoints
# ---------------------------------------------------------------------------

def _mapping_to_dict(m: QuestionMappingPreference) -> dict:
    return {
        "id": m.id,
        "questionnaire_id": m.questionnaire_id,
        "question_id": m.question_id,
        "normalized_question_text": m.normalized_question_text,
        "preferred_control_id": m.preferred_control_id,
        "preferred_framework_key": m.preferred_framework_key,
        "preferred_tag_id": m.preferred_tag_id,
        "source": m.source,
        "confidence": m.confidence,
        "status": getattr(m, "status", "suggested"),
        "approved": m.approved,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


@router.post("/{qnr_id}/generate-mappings")
def generate_questionnaire_mappings(
    qnr_id: int,
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    """Generate AI mapping suggestions: assigns each question to a control using subject-area category bias.

    Uses ``mapping_preferred_subject_areas`` on the questionnaire (not frameworks) to softly rank controls.
    Skips questions that already have approved or manual mappings (won't overwrite).
    Re-generates for questions with status=suggested or status=rejected.
    """
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    qnr = db.query(Questionnaire).filter(
        Questionnaire.id == qnr_id,
        Questionnaire.workspace_id == ws,
        Questionnaire.deleted_at.is_(None),
    ).first()
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")

    questions = db.query(Question).filter(
        Question.questionnaire_id == qnr_id,
    ).order_by(Question.id).all()
    if not questions:
        raise HTTPException(status_code=400, detail="No parsed questions in this questionnaire")

    if mapping_timing_enabled():
        reset_mapping_timing()
        reset_rerank_perf_stats()
        _t_gen_start = time.perf_counter()

    protected_question_ids = set()
    existing = db.query(QuestionMappingPreference).filter(
        QuestionMappingPreference.questionnaire_id == qnr_id,
        QuestionMappingPreference.workspace_id == ws,
    ).all()
    existing_by_qid: dict[int, QuestionMappingPreference] = {}
    for m in existing:
        if m.question_id is not None:
            existing_by_qid[m.question_id] = m
            if m.status in ("approved", "manual"):
                protected_question_ids.add(m.question_id)

    created = 0
    updated = 0
    skipped = 0
    classification_calls = 0
    settings = get_settings()

    eligible = [q for q in questions if q.id not in protected_question_ids]
    skipped = len(questions) - len(eligible)

    # Phase 1: parallel LLM classification (all eligible questions at once)
    signal_by_qid: dict[int, Any] = {}
    if eligible:
        prompt_ver = settings.mapping_classification_prompt_version
        q_ids = [q.id for q in eligible]
        preloaded = _preload_existing_signals(db, q_ids, ws, prompt_ver)

        needs_llm = [(q.id, q.text or "") for q in eligible if (q.text or "").strip() and q.id not in preloaded]
        for qid, sig in preloaded.items():
            signal_by_qid[qid] = sig

        if needs_llm:
            api_key = settings.openai_api_key
            model = settings.mapping_classification_model
            workers = min(_PARALLEL_WORKERS, len(needs_llm))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(_classify_one_thread_safe, qid, text, model, api_key): qid
                    for qid, text in needs_llm
                }
                for future in as_completed(futures):
                    qid = futures[future]
                    try:
                        _, parsed, raw = future.result()
                    except Exception:
                        parsed, raw = None, None
                    quality = "llm_structured" if parsed else "heuristic_fallback"
                    from app.models.question_mapping_signal import QuestionMappingSignal
                    sig = QuestionMappingSignal(
                        question_id=qid,
                        workspace_id=ws,
                        questionnaire_id=qnr_id,
                        framework_labels_json=json.dumps(parsed["frameworks"]) if parsed else None,
                        subject_labels_json=json.dumps(parsed["subjects"]) if parsed else None,
                        raw_llm_json=raw,
                        model=model,
                        prompt_version=prompt_ver,
                        mapping_quality=quality,
                        created_at=datetime.now(timezone.utc),
                    )
                    db.add(sig)
                    signal_by_qid[qid] = sig
                    if parsed:
                        classification_calls += 1

    # Phase 2: tag-based matching — match question subjects/frameworks to document tags
    # (No heuristic scoring — both questions and documents are LLM-tagged)
    from app.models.tag import DocumentTag, Tag
    doc_tags_raw = (
        db.query(DocumentTag.document_id, Tag.category, Tag.key, Tag.id)
        .join(Tag, DocumentTag.tag_id == Tag.id)
        .filter(DocumentTag.workspace_id == ws, Tag.category.in_(["framework", "topic"]))
        .all()
    )
    docs_by_tag_key: dict[str, set[int]] = {}
    tag_id_by_key: dict[str, int] = {}
    for doc_id, cat, key, tag_id in doc_tags_raw:
        docs_by_tag_key.setdefault(key, set()).add(doc_id)
        tag_id_by_key[key] = tag_id

    for q in eligible:
        sig = signal_by_qid.get(q.id)
        q_subjects: list[str] = []
        q_frameworks: list[str] = []
        if sig and getattr(sig, "mapping_quality", "") == "llm_structured":
            try:
                q_subjects = json.loads(sig.subject_labels_json or "[]")
            except Exception:
                pass
            try:
                q_frameworks = json.loads(sig.framework_labels_json or "[]")
            except Exception:
                pass

        matched_tag_id = None
        confidence = 0.0
        from app.services.registry_metadata import SUBJECT_AREA_LABEL_TO_KEY
        for subj_label in q_subjects:
            subj_key = SUBJECT_AREA_LABEL_TO_KEY.get(subj_label, subj_label.lower().replace(" ", "_"))
            if subj_key in docs_by_tag_key:
                matched_tag_id = tag_id_by_key.get(subj_key)
                confidence = 0.75
                break
        if matched_tag_id is None:
            for fw_label in q_frameworks:
                fw_key = fw_label.lower().replace(" ", "")
                if fw_key in docs_by_tag_key:
                    matched_tag_id = tag_id_by_key.get(fw_key)
                    confidence = 0.70
                    break

        if q.id in existing_by_qid:
            row = existing_by_qid[q.id]
            row.preferred_control_id = None
            row.preferred_tag_id = matched_tag_id
            row.confidence = confidence
            row.source = "ai"
            row.status = "suggested"
            row.approved = False
            row.updated_at = datetime.now(timezone.utc)
            updated += 1
        else:
            row = QuestionMappingPreference(
                workspace_id=ws,
                questionnaire_id=qnr_id,
                question_id=q.id,
                normalized_question_text=(q.text or "")[:2000],
                preferred_control_id=None,
                preferred_tag_id=matched_tag_id,
                source="ai",
                confidence=confidence,
                status="suggested",
                approved=False,
                created_by_user_id=session.get("user_id"),
            )
            db.add(row)
            created += 1

    if classification_calls > 0:
        try:
            record_mapping_calls(db, ws, classification_calls)
        except Exception:
            pass

    if mapping_timing_enabled():
        _t_commit = time.perf_counter()
    db.commit()
    _commit_ms = (time.perf_counter() - _t_commit) * 1000 if mapping_timing_enabled() else 0.0
    _total_ms = (time.perf_counter() - _t_gen_start) * 1000 if mapping_timing_enabled() else 0.0
    _log.info(
        "generate_mappings qnr=%s created=%s updated=%s skipped=%s classification_calls=%s",
        qnr_id, created, updated, skipped, classification_calls,
    )
    audit_log(
        "mapping.generate",
        email=session.get("email"),
        workspace_id=ws,
        resource_type="questionnaire",
        resource_id=qnr_id,
        details={"created": created, "updated": updated, "skipped": skipped, "classification_calls": classification_calls, "mode": settings.mapping_mode},
    )
    out: dict = {"created": created, "updated": updated, "skipped": skipped, "total_questions": len(questions), "classification_calls": classification_calls}
    if mapping_timing_enabled():
        mt = get_mapping_timing_snapshot()
        rp = get_rerank_perf_snapshot()
        n_will = int(rp["rows_will_call_llm"])
        avg_c = (rp["candidate_sum"] / n_will) if n_will else 0.0
        _log.info(
            "MAPPING_TIMING qnr=%s total_ms=%.1f commit_ms=%.1f heuristic_ms=%.1f rerank_ms=%.1f wc_lookup_ms=%.1f "
            "rows_fc_hits=%d will_rerank_rows=%d avg_candidates=%.2f llm_http_calls=%d",
            qnr_id,
            _total_ms,
            _commit_ms,
            float(mt["heuristic_ms"]),
            float(mt["rerank_ms"]),
            float(mt["wc_lookup_ms"]),
            int(mt["rows_fc_hits"]),
            n_will,
            avg_c,
            int(rp["llm_http_calls"]),
        )
        out["_mapping_timing"] = {
            "total_ms": round(_total_ms, 1),
            "commit_ms": round(_commit_ms, 1),
            "heuristic_ms": round(float(mt["heuristic_ms"]), 1),
            "rerank_ms": round(float(mt["rerank_ms"]), 1),
            "wc_lookup_ms": round(float(mt["wc_lookup_ms"]), 1),
            "rows_fc_hits": int(mt["rows_fc_hits"]),
            "will_rerank_rows": n_will,
            "avg_candidates": round(avg_c, 2),
            "llm_http_calls": int(rp["llm_http_calls"]),
        }
    return out


@router.get("/{qnr_id}/mappings")
def list_questionnaire_mappings(
    qnr_id: int,
    include_suggested_evidence: bool = Query(
        False,
        description="If true, run retrieval-based suggested evidence per row (embed + search; very slow for large questionnaires).",
    ),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """List question→control mappings for policy / gap review, joined with the question text.

    Default omits suggested_evidence computation so large questionnaires return quickly;
    use GET /mappings/{mapping_id}/suggested-evidence for one row, or pass include_suggested_evidence=true.
    """
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    qnr = db.query(Questionnaire).filter(
        Questionnaire.id == qnr_id,
        Questionnaire.workspace_id == ws,
        Questionnaire.deleted_at.is_(None),
    ).first()
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")

    mappings = (
        db.query(QuestionMappingPreference)
        .filter(
            QuestionMappingPreference.questionnaire_id == qnr_id,
            QuestionMappingPreference.workspace_id == ws,
        )
        .order_by(QuestionMappingPreference.question_id)
        .all()
    )

    questions = db.query(Question).filter(Question.questionnaire_id == qnr_id).all()
    q_map = {q.id: q for q in questions}

    ctrl_ids = [m.preferred_control_id for m in mappings]
    evidence_by_control = batch_supporting_evidence_for_workspace_controls(db, ws, ctrl_ids)

    wc_ids = sorted({int(x) for x in ctrl_ids if x is not None})
    wc_by_id: dict[int, WorkspaceControl] = {}
    fc_by_id: dict[int, FrameworkControl] = {}
    if wc_ids:
        for wc in (
            db.query(WorkspaceControl)
            .filter(WorkspaceControl.workspace_id == ws, WorkspaceControl.id.in_(wc_ids))
            .all()
        ):
            wc_by_id[wc.id] = wc
        fc_ids = {wc.framework_control_id for wc in wc_by_id.values() if wc.framework_control_id}
        if fc_ids:
            for fc in db.query(FrameworkControl).filter(FrameworkControl.id.in_(fc_ids)).all():
                fc_by_id[fc.id] = fc

    framework_names_by_id = {f.id: (f.name or "") for f in db.query(Framework).all()}

    result = []
    for m in mappings:
        d = _mapping_to_dict(m)
        q = q_map.get(m.question_id)
        qtext = q.text if q else m.normalized_question_text
        d["question_text"] = qtext
        d["question_section"] = q.section if q else None
        cid = m.preferred_control_id
        linked = evidence_by_control.get(int(cid), []) if cid is not None else []
        d["supporting_evidence"] = linked
        wc_row = wc_by_id.get(int(cid)) if cid is not None else None
        fc_row = fc_by_id.get(wc_row.framework_control_id) if wc_row and wc_row.framework_control_id else None
        fw_name = framework_names_by_id.get(fc_row.framework_id) if fc_row else None
        d["match_keywords"] = match_keywords_for_mapping_row(
            qtext or "", wc_row, fc_row, framework_name=fw_name
        )

        excl_docs = {int(x["document_id"]) for x in linked if x.get("document_id")}
        if include_suggested_evidence and cid is not None and (not linked):
            d["suggested_evidence"] = suggest_documents_for_mapping_review(
                db,
                ws,
                qtext or "",
                int(cid),
                exclude_document_ids=excl_docs,
                limit=3,
            )
        else:
            d["suggested_evidence"] = []
        result.append(d)

    # Count rows with a real control id (matches serialized mappings / UI "Mapped").
    mapped_count = sum(
        1 for d in result if d.get("preferred_control_id") is not None
    )
    return {
        "mappings": result,
        "total_questions": len(questions),
        "mapped_count": mapped_count,
        "mapping_preferred_subject_areas": _mapping_subject_areas_response(qnr),
    }


@router.get("/{qnr_id}/mappings/{mapping_id}/suggested-evidence")
def get_mapping_suggested_evidence(
    qnr_id: int,
    mapping_id: int,
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Retrieval-based document suggestions for one mapping (embed + search). Use for lazy load after list."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    qnr = db.query(Questionnaire).filter(
        Questionnaire.id == qnr_id,
        Questionnaire.workspace_id == ws,
        Questionnaire.deleted_at.is_(None),
    ).first()
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")

    m = db.query(QuestionMappingPreference).filter(
        QuestionMappingPreference.id == mapping_id,
        QuestionMappingPreference.questionnaire_id == qnr_id,
        QuestionMappingPreference.workspace_id == ws,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mapping not found")

    q = db.query(Question).filter(Question.id == m.question_id).first() if m.question_id else None
    qtext = q.text if q else m.normalized_question_text
    cid = m.preferred_control_id
    if cid is None:
        return {"suggested_evidence": []}

    linked = batch_supporting_evidence_for_workspace_controls(db, ws, [cid]).get(int(cid), [])
    excl_docs = {int(x["document_id"]) for x in linked if x.get("document_id")}
    if linked:
        return {"suggested_evidence": []}

    suggested = suggest_documents_for_mapping_review(
        db,
        ws,
        qtext or "",
        int(cid),
        exclude_document_ids=excl_docs,
        limit=3,
    )
    return {"suggested_evidence": suggested}


class MappingUpdate(BaseModel):
    status: str | None = None
    preferred_control_id: int | None = None
    preferred_framework_key: str | None = None
    preferred_tag_id: int | None = None


@router.patch("/{qnr_id}/mappings/{mapping_id}")
def update_questionnaire_mapping(
    qnr_id: int,
    mapping_id: int,
    body: MappingUpdate,
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    """Update a single mapping — approve, reject, or manually override."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    m = db.query(QuestionMappingPreference).filter(
        QuestionMappingPreference.id == mapping_id,
        QuestionMappingPreference.questionnaire_id == qnr_id,
        QuestionMappingPreference.workspace_id == ws,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mapping not found")

    valid_statuses = {"suggested", "approved", "rejected", "manual"}
    if body.status is not None:
        if body.status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {sorted(valid_statuses)}")
        m.status = body.status
        m.approved = body.status in ("approved", "manual")

    if body.preferred_control_id is not None:
        m.preferred_control_id = body.preferred_control_id or None
        if m.status == "suggested":
            m.status = "manual"
            m.source = "manual"
            m.approved = True

    if body.preferred_framework_key is not None:
        m.preferred_framework_key = body.preferred_framework_key or None

    if body.preferred_tag_id is not None:
        m.preferred_tag_id = body.preferred_tag_id or None

    m.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(m)
    return _mapping_to_dict(m)


@router.post("/{qnr_id}/mappings/{mapping_id}/regenerate")
def regenerate_single_mapping(
    qnr_id: int,
    mapping_id: int,
    session: dict = Depends(require_can_edit),
    db: Session = Depends(get_db),
):
    """Regenerate AI suggestion for a single question's mapping."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    m = db.query(QuestionMappingPreference).filter(
        QuestionMappingPreference.id == mapping_id,
        QuestionMappingPreference.questionnaire_id == qnr_id,
        QuestionMappingPreference.workspace_id == ws,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mapping not found")

    qnr = db.query(Questionnaire).filter(
        Questionnaire.id == qnr_id,
        Questionnaire.workspace_id == ws,
        Questionnaire.deleted_at.is_(None),
    ).first()
    if not qnr:
        raise HTTPException(status_code=404, detail="Questionnaire not found")

    q = db.query(Question).filter(Question.id == m.question_id).first()
    text = q.text if q else (m.normalized_question_text or "")

    signal = classify_question_signal(
        db, m.question_id, text, ws, questionnaire_id=qnr_id, force=True,
    )

    q_subjects: list[str] = []
    if signal and getattr(signal, "mapping_quality", "") == "llm_structured":
        try:
            q_subjects = json.loads(signal.subject_labels_json or "[]")
        except Exception:
            pass

    from app.models.tag import DocumentTag, Tag
    from app.services.registry_metadata import SUBJECT_AREA_LABEL_TO_KEY
    matched_tag_id = None
    confidence = 0.0
    for subj_label in q_subjects:
        subj_key = SUBJECT_AREA_LABEL_TO_KEY.get(subj_label, subj_label.lower().replace(" ", "_"))
        tag = db.query(Tag).filter(Tag.key == subj_key, Tag.category == "topic").first()
        if tag:
            has_docs = db.query(DocumentTag).filter(DocumentTag.tag_id == tag.id, DocumentTag.workspace_id == ws).first()
            if has_docs:
                matched_tag_id = tag.id
                confidence = 0.75
                break

    m.preferred_control_id = None
    m.preferred_tag_id = matched_tag_id
    m.confidence = confidence
    m.source = "ai"
    m.status = "suggested"
    m.approved = False
    m.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(m)
    return _mapping_to_dict(m)
