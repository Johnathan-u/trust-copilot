"""Tag service: catalog, CRUD, LLM auto-tagging helpers."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Sequence

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.tag import DocumentTag, Tag, TAG_CATEGORIES, TAG_SOURCES

logger = logging.getLogger(__name__)

# ── Predefined system tag catalog ───────────────────────────────────────────

SYSTEM_TAGS: list[dict] = [
    # Frameworks
    {"category": "framework", "key": "soc2", "label": "SOC 2"},
    {"category": "framework", "key": "hipaa", "label": "HIPAA"},
    {"category": "framework", "key": "iso27001", "label": "ISO 27001"},
    {"category": "framework", "key": "nist_csf_2_0", "label": "NIST CSF 2.0"},
    {"category": "framework", "key": "nist_sp_800_53", "label": "NIST SP 800-53"},
    {"category": "framework", "key": "nist_sp_800_171", "label": "NIST SP 800-171"},
    {"category": "framework", "key": "nist", "label": "NIST"},
    {"category": "framework", "key": "sig", "label": "SIG"},
    {"category": "framework", "key": "caiq", "label": "CAIQ"},
    {"category": "framework", "key": "hitrust", "label": "HITRUST"},
    {"category": "framework", "key": "pci_dss", "label": "PCI DSS"},
    {"category": "framework", "key": "gdpr", "label": "GDPR"},
    # Topics (aligned with framework_metadata SUBJECTS)
    {"category": "topic", "key": "access_control", "label": "Access Control"},
    {"category": "topic", "key": "application_security", "label": "Application Security"},
    {"category": "topic", "key": "asset_inventory", "label": "Asset Inventory"},
    {"category": "topic", "key": "audit_assurance", "label": "Audit & Assurance"},
    {"category": "topic", "key": "availability_resilience", "label": "Availability & Resilience"},
    {"category": "topic", "key": "backup_restore", "label": "Backup & Restore"},
    {"category": "topic", "key": "breach_notification", "label": "Breach Notification"},
    {"category": "topic", "key": "business_continuity", "label": "Business Continuity"},
    {"category": "topic", "key": "change_management", "label": "Change Management"},
    {"category": "topic", "key": "cloud_security", "label": "Cloud Security"},
    {"category": "topic", "key": "confidentiality_data_protection", "label": "Confidentiality & Data Protection"},
    {"category": "topic", "key": "configuration_management", "label": "Configuration Management"},
    {"category": "topic", "key": "cryptography", "label": "Cryptography"},
    {"category": "topic", "key": "data_classification", "label": "Data Classification"},
    {"category": "topic", "key": "data_protection", "label": "Data Protection"},
    {"category": "topic", "key": "data_retention_disposal", "label": "Data Retention & Disposal"},
    {"category": "topic", "key": "encryption", "label": "Encryption"},
    {"category": "topic", "key": "endpoint_security", "label": "Endpoint Security"},
    {"category": "topic", "key": "governance_risk_compliance", "label": "Governance & Risk Compliance"},
    {"category": "topic", "key": "hr_security", "label": "HR Security"},
    {"category": "topic", "key": "identity_authentication", "label": "Identity & Authentication"},
    {"category": "topic", "key": "incident_response", "label": "Incident Response"},
    {"category": "topic", "key": "integrity_monitoring", "label": "Integrity Monitoring"},
    {"category": "topic", "key": "logging", "label": "Logging"},
    {"category": "topic", "key": "logging_monitoring", "label": "Logging & Monitoring"},
    {"category": "topic", "key": "network_security", "label": "Network Security"},
    {"category": "topic", "key": "physical_security", "label": "Physical Security"},
    {"category": "topic", "key": "privacy_data_governance", "label": "Privacy & Data Governance"},
    {"category": "topic", "key": "privileged_access", "label": "Privileged Access"},
    {"category": "topic", "key": "risk_management", "label": "Risk Management"},
    {"category": "topic", "key": "secure_sdlc", "label": "Secure SDLC"},
    {"category": "topic", "key": "supply_chain_risk", "label": "Supply Chain Risk"},
    {"category": "topic", "key": "vendor_management", "label": "Vendor Management"},
    {"category": "topic", "key": "vendor_risk", "label": "Vendor Risk"},
    {"category": "topic", "key": "workforce_security_training", "label": "Workforce Security & Training"},
    {"category": "topic", "key": "ai_governance", "label": "AI Governance"},
    # Document types
    {"category": "document_type", "key": "policy", "label": "Policy"},
    {"category": "document_type", "key": "procedure", "label": "Procedure"},
    {"category": "document_type", "key": "report", "label": "Report"},
    {"category": "document_type", "key": "screenshot", "label": "Screenshot"},
    {"category": "document_type", "key": "training_record", "label": "Training Record"},
    {"category": "document_type", "key": "certificate", "label": "Certificate"},
]


def ensure_system_tags(db: Session) -> None:
    """Insert any missing system tags (idempotent, concurrency-safe).

    Uses INSERT ... ON CONFLICT DO NOTHING via per-tag try/except to handle
    concurrent startup across multiple app instances without duplicate errors.
    """
    from sqlalchemy.exc import IntegrityError
    inserted = 0
    for t in SYSTEM_TAGS:
        existing = (
            db.query(Tag)
            .filter(Tag.workspace_id.is_(None), Tag.category == t["category"], Tag.key == t["key"])
            .first()
        )
        if existing:
            continue
        try:
            db.add(Tag(workspace_id=None, category=t["category"], key=t["key"], label=t["label"], is_system=True))
            db.flush()
            inserted += 1
        except IntegrityError:
            db.rollback()
    db.commit()
    if inserted:
        logger.info("ensure_system_tags: inserted %d new system tags", inserted)
    else:
        logger.debug("ensure_system_tags: all %d system tags already present", len(SYSTEM_TAGS))


def resolve_tag(db: Session, category: str, key: str, workspace_id: int | None = None) -> Tag | None:
    """Look up a tag by category+key.  Checks workspace-scoped first, then global system tags."""
    if workspace_id is not None:
        tag = db.query(Tag).filter(Tag.workspace_id == workspace_id, Tag.category == category, Tag.key == key).first()
        if tag:
            return tag
    return db.query(Tag).filter(Tag.workspace_id.is_(None), Tag.category == category, Tag.key == key).first()


def get_or_create_tag(db: Session, category: str, key: str, label: str, workspace_id: int | None = None) -> Tag:
    """Return existing tag or create a new one."""
    tag = resolve_tag(db, category, key, workspace_id)
    if tag:
        return tag
    tag = Tag(workspace_id=workspace_id, category=category, key=key, label=label, is_system=False)
    db.add(tag)
    db.flush()
    return tag


# ── Assignment helpers ──────────────────────────────────────────────────────

def assign_tag(
    db: Session,
    document_id: int,
    tag_id: int,
    workspace_id: int,
    source: str = "manual",
    confidence: float | None = None,
    approved: bool = True,
    user_id: int | None = None,
) -> DocumentTag:
    """Assign a tag to a document (upsert on duplicate)."""
    existing = (
        db.query(DocumentTag)
        .filter(DocumentTag.document_id == document_id, DocumentTag.tag_id == tag_id)
        .first()
    )
    if existing:
        existing.source = source
        existing.confidence = confidence
        existing.approved = approved
        if user_id:
            existing.created_by_user_id = user_id
        db.flush()
        return existing
    dt = DocumentTag(
        workspace_id=workspace_id,
        document_id=document_id,
        tag_id=tag_id,
        source=source,
        confidence=confidence,
        approved=approved,
        created_by_user_id=user_id,
    )
    db.add(dt)
    db.flush()
    return dt


def remove_tag(db: Session, document_id: int, tag_id: int, workspace_id: int) -> bool:
    """Remove a tag assignment. Returns True if deleted."""
    dt = (
        db.query(DocumentTag)
        .filter(
            DocumentTag.document_id == document_id,
            DocumentTag.tag_id == tag_id,
            DocumentTag.workspace_id == workspace_id,
        )
        .first()
    )
    if not dt:
        return False
    db.delete(dt)
    db.flush()
    return True


def approve_tag(db: Session, document_tag_id: int, workspace_id: int, approved: bool = True) -> DocumentTag | None:
    """Approve or reject an AI-suggested tag."""
    dt = (
        db.query(DocumentTag)
        .filter(DocumentTag.id == document_tag_id, DocumentTag.workspace_id == workspace_id)
        .first()
    )
    if not dt:
        return None
    dt.approved = approved
    db.flush()
    return dt


def list_tags_for_document(db: Session, document_id: int, workspace_id: int) -> list[dict]:
    """Return all tag assignments for a document as dicts."""
    rows = (
        db.query(DocumentTag, Tag)
        .join(Tag, DocumentTag.tag_id == Tag.id)
        .filter(DocumentTag.document_id == document_id, DocumentTag.workspace_id == workspace_id)
        .all()
    )
    return [_tag_assignment_dict(dt, tag) for dt, tag in rows]


def list_tags_for_documents(db: Session, document_ids: list[int], workspace_id: int) -> dict[int, list[dict]]:
    """Batch-load tags for multiple documents.  Returns {document_id: [tag_dict, ...]}."""
    if not document_ids:
        return {}
    rows = (
        db.query(DocumentTag, Tag)
        .join(Tag, DocumentTag.tag_id == Tag.id)
        .filter(DocumentTag.document_id.in_(document_ids), DocumentTag.workspace_id == workspace_id)
        .all()
    )
    result: dict[int, list[dict]] = {did: [] for did in document_ids}
    for dt, tag in rows:
        result.setdefault(dt.document_id, []).append(_tag_assignment_dict(dt, tag))
    return result


def list_available_tags(db: Session, workspace_id: int) -> list[dict]:
    """Return all tags visible to a workspace (system + workspace-scoped)."""
    rows = (
        db.query(Tag)
        .filter((Tag.workspace_id.is_(None)) | (Tag.workspace_id == workspace_id))
        .order_by(Tag.category, Tag.key)
        .all()
    )
    return [
        {
            "id": t.id,
            "category": t.category,
            "key": t.key,
            "label": t.label,
            "is_system": t.is_system,
        }
        for t in rows
    ]


def _tag_assignment_dict(dt: DocumentTag, tag: Tag) -> dict:
    return {
        "id": dt.id,
        "tag_id": tag.id,
        "category": tag.category,
        "key": tag.key,
        "label": tag.label,
        "source": dt.source,
        "confidence": dt.confidence,
        "approved": dt.approved,
    }


# ── LLM auto-tagger (deterministic-first, LLM tiebreak) ─────────────────────

_ALLOWED_FRAMEWORK_KEYS = [t["key"] for t in SYSTEM_TAGS if t["category"] == "framework"]
_ALLOWED_TOPIC_KEYS = [t["key"] for t in SYSTEM_TAGS if t["category"] == "topic"]
_ALLOWED_DOCTYPE_KEYS = [t["key"] for t in SYSTEM_TAGS if t["category"] == "document_type"]

# Mapping from deterministic classifier framework keys to tag keys
_FRAMEWORK_KEY_TO_TAG: dict[str, str] = {
    "SOC2": "soc2", "HIPAA": "hipaa", "ISO27001": "iso27001",
    "NIST_CSF_2_0": "nist_csf_2_0", "NIST_SP_800_53_REV5": "nist_sp_800_53",
    "NIST_SP_800_171_REV3": "nist_sp_800_171", "SIG": "sig", "CAIQ": "caiq",
}

_DOC_TIEBREAK_PROMPT = (
    "You are a compliance document classifier with high-precision requirements.\n\n"
    "The document has been pre-scored by a deterministic classifier. "
    "Your job is to confirm or override the top framework candidates.\n\n"
    "CRITICAL RULES:\n"
    "- Never assign a framework solely from generic security vocabulary "
    "(access control, logging, encryption, incident response, backup, least privilege).\n"
    "- Require explicit framework markers (title, preamble, control IDs, report structure).\n"
    "- If unsure, return 'unknown' as the framework.\n\n"
    "Return a single JSON object (no markdown fences):\n"
    "{\n"
    '  "framework": "<framework_key or unknown>",\n'
    '  "topics": ["<topic_key>", ...],\n'
    '  "document_types": ["<doctype_key>", ...],\n'
    '  "confidence": <0.0-1.0>\n'
    "}\n\n"
    f"ALLOWED topic keys: {json.dumps(_ALLOWED_TOPIC_KEYS)}\n"
    f"ALLOWED document_type keys: {json.dumps(_ALLOWED_DOCTYPE_KEYS)}\n"
)

_DOC_CLASSIFY_RETRIES = 1


def _classify_document_deterministic(text: str, filename: str) -> tuple[list[dict], bool]:
    """Phase 1: deterministic multi-channel scoring. Returns (results, needs_llm)."""
    from app.services.framework_classifier import classify_document

    result = classify_document(text, filename)
    suggestions: list[dict] = []

    if result.framework in _FRAMEWORK_KEY_TO_TAG:
        tag_key = _FRAMEWORK_KEY_TO_TAG[result.framework]
        suggestions.append({
            "category": "framework", "key": tag_key, "confidence": result.confidence,
        })

    for subj_key in result.subjects[:8]:
        if subj_key in set(_ALLOWED_TOPIC_KEYS):
            suggestions.append({
                "category": "topic", "key": subj_key, "confidence": result.confidence * 0.9,
            })

    return suggestions, result.needs_llm_tiebreak


def _classify_document_llm_tiebreak(
    text: str, filename: str, candidates: list[str],
) -> list[dict] | None:
    """Phase 2: LLM tiebreak with constrained prompt. Only called for non-HIGH confidence."""
    if not (text or "").strip() and not (filename or "").strip():
        return []
    settings = get_settings()
    if not settings.openai_api_key:
        return None

    from app.services.mapping_llm_classify import _get_client

    client = _get_client(settings.openai_api_key)
    model = settings.mapping_classification_model

    candidate_str = ", ".join(candidates) if candidates else "unknown"
    prompt = (
        _DOC_TIEBREAK_PROMPT
        + f"\nPre-scored framework candidates: [{candidate_str}]\n"
        + f"ALLOWED framework keys (pick one): {json.dumps(_ALLOWED_FRAMEWORK_KEYS + ['unknown'])}\n"
    )
    user_content = f"Filename: {filename}\n\nContent (first 6000 chars):\n{text[:6000]}"

    for attempt in range(_DOC_CLASSIFY_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.1,
                max_tokens=200,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content if resp.choices else None
            if not raw:
                continue
            obj = json.loads(raw.strip())
            if not isinstance(obj, dict):
                continue

            fw_set = set(_ALLOWED_FRAMEWORK_KEYS)
            topic_set = set(_ALLOWED_TOPIC_KEYS)
            doc_set = set(_ALLOWED_DOCTYPE_KEYS)
            conf = 0.85
            try:
                conf = max(0.0, min(1.0, float(obj.get("confidence", 0.85))))
            except (TypeError, ValueError):
                pass

            results: list[dict] = []
            fw_val = obj.get("framework")
            if isinstance(fw_val, str) and fw_val in fw_set:
                results.append({"category": "framework", "key": fw_val, "confidence": conf})
            for k in (obj.get("topics") or []):
                if k in topic_set:
                    results.append({"category": "topic", "key": k, "confidence": conf * 0.9})
            for k in (obj.get("document_types") or []):
                if k in doc_set:
                    results.append({"category": "document_type", "key": k, "confidence": conf * 0.9})
            return results
        except Exception as exc:
            logger.warning("classify_document_llm_tiebreak: attempt %d failed: %s", attempt, exc)
            if attempt < _DOC_CLASSIFY_RETRIES:
                time.sleep(0.3)
    return None


def classify_text(text: str, filename: str = "") -> list[dict]:
    """Classify document: deterministic first, LLM tiebreak only when needed."""
    det_results, needs_llm = _classify_document_deterministic(text, filename)

    if not needs_llm and det_results:
        return det_results

    candidates = [r["key"] for r in det_results if r["category"] == "framework"]
    llm_results = _classify_document_llm_tiebreak(text, filename, candidates)
    if llm_results is not None:
        det_topics = [r for r in det_results if r["category"] == "topic"]
        llm_fw = [r for r in llm_results if r["category"] == "framework"]
        llm_topics = [r for r in llm_results if r["category"] == "topic"]
        llm_doctypes = [r for r in llm_results if r["category"] == "document_type"]
        merged = llm_fw + (llm_topics if llm_topics else det_topics) + llm_doctypes
        return merged if merged else det_results

    logger.warning("classify_text: LLM tiebreak failed, using deterministic results only")
    return det_results


def auto_tag_document(db: Session, document_id: int, workspace_id: int, filename: str, chunk_texts: list[str]) -> int:
    """Classify a document via LLM and persist tags + update JSON fields. Returns tag count."""
    combined_text = "\n".join(chunk_texts[:20])
    suggestions = classify_text(combined_text, filename)
    count = 0
    framework_labels: list[str] = []
    topic_labels: list[str] = []
    for s in suggestions:
        tag = resolve_tag(db, s["category"], s["key"])
        if not tag:
            tag = get_or_create_tag(db, s["category"], s["key"], s["key"].replace("_", " ").title(), workspace_id)
        assign_tag(
            db,
            document_id=document_id,
            tag_id=tag.id,
            workspace_id=workspace_id,
            source="ai",
            confidence=s["confidence"],
            approved=False,
        )
        if s["category"] == "framework":
            framework_labels.append(tag.label)
        elif s["category"] == "topic":
            topic_labels.append(tag.label)
        count += 1

    # Update the JSON fields on the document so tier/display reflect LLM tags
    if framework_labels or topic_labels:
        from app.models import Document
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc:
            if framework_labels:
                doc.frameworks_json = json.dumps(framework_labels)
            if topic_labels:
                doc.subject_areas_json = json.dumps(topic_labels)

    return count
