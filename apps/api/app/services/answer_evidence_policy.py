"""Answer-generation evidence gating and source priority (enterprise).

Does not change mapping logic; consumes existing retrieval + control-linked evidence as inputs.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# Canonical placeholder when we do not run the LLM or the model declines to assert.
INSUFFICIENT_EVIDENCE_TEXT = "Insufficient evidence."

# --- Pre-LLM gating (semantic top score in [0,1], higher = stronger match) ---
# Only gate true noise (random vectors ~0.1-0.2); let LLM decide borderline cases.
MIN_TOP_UNIVERSAL_NOISE_FLOOR = 0.18

# Without control mapping: let moderate-relevance evidence through to LLM.
# Kept low so short/thin documents with relevant content still reach the model.
MIN_TOP_WITHOUT_CONTROL = 0.28
MIN_TOP_LOW_TIER_WITHOUT_CONTROL = 0.36

# With control mapping: similar but slightly looser (control signal adds confidence).
MIN_TOP_WITH_CONTROL = 0.26
MIN_TOP_WITH_CONTROL_LOW_TIER_ONLY = 0.34

# Export / review: cell text when answer is not customer-ready.
EXPORT_NOT_READY_PLACEHOLDER = "[Need more evidence — not ready to share]"


def normalize_answer_for_insufficient_check(text: str | None) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t


def is_placeholder_insufficient(text: str | None) -> bool:
    """True when the answer text is the insufficient placeholder (any common variant)."""
    t = normalize_answer_for_insufficient_check(text)
    if not t:
        return True
    if t in ("insufficient evidence", "insufficient evidence."):
        return True
    if t.startswith("insufficient evidence") and len(t) < 80:
        return True
    return False


# Phrases in the *opening* of an answer that indicate the model is declining to assert
# (long-form "insufficient" narratives and common compliance hedges).
_INSUFFICIENT_HEAD_WINDOW = 360

_HEDGE_INSUFFICIENT_NEEDLES: tuple[str, ...] = (
    "the provided documentation does not specify",
    "the provided documentation does not explicitly",
    "the documentation does not specify whether",
    "the documentation does not explicitly",
    "the evidence does not explicitly state",
    "the evidence does not specify whether",
    "the evidence does not explicitly",
    "does not explicitly state whether",
    "does not specify whether the",
    "does not explicitly address whether",
    "provided documentation does not explicitly state",
)


def is_insufficient_answer_text(text: str | None) -> bool:
    """True for placeholders, long 'Insufficient evidence...' narratives, and strong decline-to-assert hedges."""
    if is_placeholder_insufficient(text):
        return True
    t = normalize_answer_for_insufficient_check(text)
    if not t:
        return True
    if t.startswith("insufficient evidence"):
        return True
    head = t[:_INSUFFICIENT_HEAD_WINDOW]
    if any(n in head for n in _HEDGE_INSUFFICIENT_NEEDLES):
        return True
    return False


def classify_answer_status_from_text(text: str | None) -> str:
    """Map model output to a persisted answer status (draft vs insufficient_evidence)."""
    if is_insufficient_answer_text(text):
        return "insufficient_evidence"
    return "draft"


def answer_text_for_export(*, text: str | None, status: str | None, citations_json: str | None = None) -> str:
    """Customer-facing export cell with citation footnotes. Never ship insufficient rows."""
    st = status or ""
    if st == "insufficient_evidence":
        return EXPORT_NOT_READY_PLACEHOLDER
    if is_insufficient_answer_text(text):
        return EXPORT_NOT_READY_PLACEHOLDER
    answer = (text or "").strip()
    if not answer:
        return answer
    footnotes = _format_citation_footnotes(citations_json)
    if footnotes:
        answer = f"{answer}\n\n{footnotes}"
    return answer


def _format_citation_footnotes(citations_json: str | None) -> str:
    """Format citations as numbered footnotes for export traceability."""
    if not citations_json:
        return ""
    try:
        import json
        cits = json.loads(citations_json)
        if not isinstance(cits, list) or not cits:
            return ""
    except Exception:
        return ""
    lines: list[str] = []
    for i, cit in enumerate(cits, 1):
        filename = cit.get("filename") or ""
        snippet = (cit.get("snippet") or "")[:120]
        if filename:
            lines.append(f"[{i}] {filename}: {snippet}{'...' if len(cit.get('snippet', '')) > 120 else ''}")
        elif snippet:
            lines.append(f"[{i}] {snippet}{'...' if len(cit.get('snippet', '')) > 120 else ''}")
    if not lines:
        return ""
    return "Sources:\n" + "\n".join(lines)


def is_real_draft_status(status: str | None, text: str | None) -> bool:
    """A row counts as a real AI/human draft, not a system placeholder."""
    if status == "insufficient_evidence":
        return False
    if is_insufficient_answer_text(text):
        return False
    return bool((text or "").strip())


_STRONG_FRAMEWORK_LABELS: frozenset[str] | None = None


def _get_strong_framework_labels() -> frozenset[str]:
    """Lazily build the set of recognized framework labels for tier-0 detection."""
    global _STRONG_FRAMEWORK_LABELS
    if _STRONG_FRAMEWORK_LABELS is None:
        from app.services.framework_metadata import FRAMEWORKS, NAMING
        labels: set[str] = set()
        for key in FRAMEWORKS:
            labels.add(key.lower())
            if key in NAMING:
                labels.add(NAMING[key].lower())
        labels.update({
            "soc 2", "soc2", "iso 27001", "iso27001", "iso/iec 27001",
            "hipaa", "fedramp", "nist csf 2.0", "nist sp 800-53",
            "nist sp 800-171", "sig", "caiq", "csa caiq",
            "shared assessments sig", "pci dss",
        })
        _STRONG_FRAMEWORK_LABELS = frozenset(labels)
    return _STRONG_FRAMEWORK_LABELS


def document_tier_from_filename_and_frameworks(filename: str | None, frameworks_json: str | None) -> int:
    """Lower is stronger for sorting (0 = authoritative / program, 3 = export-like / reference)."""
    fn = (filename or "").lower()
    low_signal = (
        "export",
        "questionnaire",
        "vendor response",
        "response.xlsx",
        "filled",
        "template",
        "submission",
        "answers_only",
    )
    if any(x in fn for x in low_signal):
        return 3
    try:
        fj = json.loads(frameworks_json or "[]")
        if isinstance(fj, list) and fj and fj != ["Other"] and fj != ["Unknown"]:
            strong_labels = _get_strong_framework_labels()
            strong = any(str(x).lower() in strong_labels for x in fj)
            if strong:
                return 0
            if fj:
                return 1
    except Exception:
        pass
    return 2


def subject_requires_direct_evidence(subject_key: str) -> bool:
    """True when the subject should only be answered with explicit, directly relevant evidence."""
    from app.services.framework_metadata import SUBJECTS
    subj = SUBJECTS.get(subject_key)
    if subj:
        return subj.direct_evidence_required
    return False


def prioritize_evidence_for_answer(db: Session, evidence: list[dict], doc_tier_cache: dict[int, int] | None = None) -> list[dict]:
    """Order: control-linked first, then lower document tier, then higher score."""
    from app.models import Document

    if not evidence:
        return []
    doc_ids: set[int] = set()
    for e in evidence:
        meta = e.get("metadata")
        if isinstance(meta, dict):
            did = meta.get("document_id")
            if did is not None:
                try:
                    doc_ids.add(int(did))
                except (TypeError, ValueError):
                    pass
    docs: dict[int, Document] = {}
    if doc_ids:
        if doc_tier_cache is not None:
            missing_ids = [did for did in doc_ids if did not in doc_tier_cache]
            if missing_ids:
                for d in db.query(Document).filter(Document.id.in_(missing_ids)).all():
                    docs[d.id] = d
        else:
            for d in db.query(Document).filter(Document.id.in_(doc_ids)).all():
                docs[d.id] = d

    def sort_key(e: dict) -> tuple:
        src = e.get("evidence_source") or "retrieval"
        ctrl = 0 if src == "control_link" else 1
        meta = e.get("metadata") if isinstance(e.get("metadata"), dict) else {}
        did = meta.get("document_id") if isinstance(meta, dict) else None
        did_int = int(did) if did is not None else None
        if did_int is not None and doc_tier_cache is not None and did_int in doc_tier_cache:
            tier = doc_tier_cache[did_int]
        else:
            doc = docs.get(did_int) if did_int is not None else None
            tier = document_tier_from_filename_and_frameworks(
                doc.filename if doc else None,
                doc.frameworks_json if doc else None,
            ) if doc else 2
        sc = -float(e.get("score") or 0)
        return (ctrl, tier, sc)

    return sorted(evidence, key=sort_key)


def evidence_top_score(evidence: list[dict]) -> float:
    if not evidence:
        return 0.0
    return max(float(e.get("score") or 0) for e in evidence)


def preload_document_tiers(db: "Session", document_ids: list[int]) -> dict[int, int]:
    """Batch-load document tiers in one query. Returns {doc_id: tier}."""
    if not document_ids:
        return {}
    from app.models import Document
    docs = db.query(Document.id, Document.filename, Document.frameworks_json).filter(
        Document.id.in_(document_ids)
    ).all()
    return {
        d.id: document_tier_from_filename_and_frameworks(d.filename, d.frameworks_json)
        for d in docs
    }


def only_low_tier_evidence(
    db: "Session",
    evidence: list[dict],
    doc_tier_cache: dict[int, int] | None = None,
) -> bool:
    """True if all chunks resolve to tier-3 (export-like) documents."""
    from app.models import Document

    if not evidence:
        return True
    tiers = []
    for e in evidence[:12]:
        meta = e.get("metadata") if isinstance(e.get("metadata"), dict) else {}
        did = meta.get("document_id")
        if did is None:
            tiers.append(2)
            continue
        did_int = int(did)
        if doc_tier_cache is not None and did_int in doc_tier_cache:
            tiers.append(doc_tier_cache[did_int])
            continue
        doc = db.query(Document).filter(Document.id == did_int).first()
        if not doc:
            tiers.append(2)
            continue
        tier = document_tier_from_filename_and_frameworks(doc.filename, doc.frameworks_json)
        if doc_tier_cache is not None:
            doc_tier_cache[did_int] = tier
        tiers.append(tier)
    if not tiers:
        return False
    return all(t >= 3 for t in tiers)


def should_skip_llm(
    db: "Session",
    evidence: list[dict],
    has_control_mapping: bool,
    doc_tier_cache: dict[int, int] | None = None,
) -> tuple[bool, str]:
    """Fast gate before OpenAI: skip weak retrieval so bulk runs do not burn 1 LLM call per row."""
    if not evidence:
        return True, "no_evidence"
    top = evidence_top_score(evidence)
    low_tier = only_low_tier_evidence(db, evidence, doc_tier_cache=doc_tier_cache)

    if top < MIN_TOP_UNIVERSAL_NOISE_FLOOR:
        return True, "retrieval_noise_floor"

    if has_control_mapping:
        if low_tier:
            if top < MIN_TOP_WITH_CONTROL_LOW_TIER_ONLY:
                return True, "weak_control_path_low_tier"
        else:
            if top < MIN_TOP_WITH_CONTROL:
                return True, "weak_control_path"
        return False, ""

    if low_tier:
        if top < MIN_TOP_LOW_TIER_WITHOUT_CONTROL:
            return True, "weak_retrieval_low_tier_docs"
    else:
        if top < MIN_TOP_WITHOUT_CONTROL:
            return True, "weak_retrieval_no_control"
    return False, ""
