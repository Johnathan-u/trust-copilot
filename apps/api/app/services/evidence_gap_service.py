"""Evidence gap analysis: generates structured gap objects for insufficient-evidence answers.

When the pipeline marks a question as insufficient_evidence, this service analyzes WHY
and proposes the exact policy language needed to close the gap.
"""

import json
import logging
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.evidence_gap import EvidenceGap, GAP_TYPES

logger = logging.getLogger(__name__)

_GAP_SYSTEM_PROMPT = (
    "You are a compliance policy advisor. A security questionnaire question could not be answered "
    "because the organization's evidence library lacks sufficient documentation.\n\n"
    "Analyze the gap and produce a JSON object (no markdown fences):\n"
    "{\n"
    '  "gap_type": "<type>",\n'
    '  "reason": "<why evidence is insufficient>",\n'
    '  "proposed_policy_addition": "<formal policy text to add>",\n'
    '  "suggested_evidence_doc_title": "<document title suggestion>",\n'
    '  "confidence": <0.0-1.0>\n'
    "}\n\n"
    f"ALLOWED gap_type values: {json.dumps(list(GAP_TYPES))}\n\n"
    "Rules:\n"
    "- proposed_policy_addition MUST sound like formal enterprise security policy language\n"
    "- It should be phrased as suggested language to ADD, not a claim the company already complies\n"
    "- Start proposed text with 'The Company shall...' or 'The Organization maintains...' style\n"
    "- Be specific enough to directly answer the questionnaire question\n"
    "- reason should explain what specific evidence is missing\n"
    "- confidence reflects how certain you are the proposed addition would close the gap\n"
)

_MAX_RETRIES = 2
_RETRY_DELAY = 1.0


def generate_gap_analysis(
    question_text: str,
    classification: dict | None = None,
    evidence_snippets: list[dict] | None = None,
    gating_reason: str | None = None,
) -> dict | None:
    """Call LLM to analyze an evidence gap. Returns parsed dict or None on failure."""
    settings = get_settings()
    if not settings.openai_api_key:
        return None

    from app.services.mapping_llm_classify import _get_client
    client = _get_client(settings.openai_api_key)
    model = settings.mapping_classification_model

    user_parts = [f"Question: {question_text}"]
    if classification:
        frameworks = classification.get("frameworks", [])
        subjects = classification.get("subjects", [])
        if frameworks:
            user_parts.append(f"Frameworks: {', '.join(frameworks)}")
        if subjects:
            user_parts.append(f"Subject areas: {', '.join(subjects)}")
    if gating_reason:
        user_parts.append(f"Gating reason: {gating_reason}")
    if evidence_snippets:
        snippets_text = "\n".join(
            f"- [{s.get('filename', 'unknown')}]: {(s.get('snippet', '') or '')[:150]}"
            for s in evidence_snippets[:5]
        )
        user_parts.append(f"Available evidence (weak/partial):\n{snippets_text}")
    else:
        user_parts.append("No relevant evidence was found in the document library.")

    user_content = "\n\n".join(user_parts)

    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _GAP_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.2,
                max_tokens=500,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content if resp.choices else None
            if not raw:
                continue
            obj = json.loads(raw.strip())
            if not isinstance(obj, dict):
                continue

            gap_type = obj.get("gap_type", "other")
            if gap_type not in GAP_TYPES:
                gap_type = "other"

            confidence = 0.5
            try:
                confidence = max(0.0, min(1.0, float(obj.get("confidence", 0.5))))
            except (TypeError, ValueError):
                pass

            return {
                "gap_type": gap_type,
                "reason": str(obj.get("reason", "")).strip() or "Evidence insufficient for this question.",
                "proposed_policy_addition": str(obj.get("proposed_policy_addition", "")).strip(),
                "suggested_evidence_doc_title": str(obj.get("suggested_evidence_doc_title", "")).strip() or None,
                "confidence": confidence,
            }
        except Exception as exc:
            logger.warning("evidence_gap_service: attempt %d failed: %s", attempt, exc)
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY)
    return None


def persist_gap(
    db: Session,
    workspace_id: int,
    questionnaire_id: int,
    question_id: int,
    gap_data: dict,
    answer_id: int | None = None,
) -> EvidenceGap:
    """Persist a gap analysis result. Upserts on (question_id) to avoid duplicates."""
    existing = db.query(EvidenceGap).filter(
        EvidenceGap.question_id == question_id,
        EvidenceGap.questionnaire_id == questionnaire_id,
        EvidenceGap.workspace_id == workspace_id,
        EvidenceGap.status == "open",
    ).first()

    if existing:
        existing.gap_type = gap_data["gap_type"]
        existing.reason = gap_data["reason"]
        existing.proposed_policy_addition = gap_data.get("proposed_policy_addition", "")
        existing.suggested_evidence_doc_title = gap_data.get("suggested_evidence_doc_title")
        existing.confidence = gap_data.get("confidence")
        existing.answer_id = answer_id
        existing.updated_at = datetime.now(timezone.utc)
        return existing

    gap = EvidenceGap(
        workspace_id=workspace_id,
        questionnaire_id=questionnaire_id,
        question_id=question_id,
        answer_id=answer_id,
        gap_type=gap_data["gap_type"],
        reason=gap_data["reason"],
        proposed_policy_addition=gap_data.get("proposed_policy_addition", ""),
        suggested_evidence_doc_title=gap_data.get("suggested_evidence_doc_title"),
        confidence=gap_data.get("confidence"),
        status="open",
    )
    db.add(gap)
    return gap


def accept_gap(db: Session, gap_id: int, workspace_id: int) -> dict:
    """Accept a gap suggestion: create a supplemental evidence document from the proposed text.
    Returns the created document info dict."""
    gap = db.query(EvidenceGap).filter(
        EvidenceGap.id == gap_id,
        EvidenceGap.workspace_id == workspace_id,
    ).first()
    if not gap:
        raise ValueError(f"Evidence gap {gap_id} not found")
    if gap.status != "open":
        raise ValueError(f"Gap {gap_id} is already {gap.status}")

    from app.models import Document
    doc_title = gap.suggested_evidence_doc_title or f"Supplemental Policy - Q{gap.question_id}"
    doc = Document(
        workspace_id=workspace_id,
        storage_key=f"supplement/gap_{gap.id}.txt",
        filename=f"{doc_title}.txt",
        content_type="text/plain",
        frameworks_json="[]",
        user_frameworks_json="[]",
        subject_areas_json="[]",
        status="uploaded",
    )
    db.add(doc)
    db.flush()

    gap.status = "accepted"
    gap.updated_at = datetime.now(timezone.utc)
    db.commit()

    # Store the policy text as a chunk for retrieval
    try:
        from app.models import Chunk
        chunk = Chunk(
            workspace_id=workspace_id,
            document_id=doc.id,
            text=gap.proposed_policy_addition,
            chunk_index=0,
            metadata_=json.dumps({
                "document_id": doc.id,
                "filename": doc.filename,
                "source": "ai_supplement",
                "gap_id": gap.id,
            }),
        )
        db.add(chunk)
        doc.status = "indexed"
        db.commit()
    except Exception as e:
        logger.warning("accept_gap: chunk creation failed for gap %d: %s", gap_id, e)

    return {
        "gap_id": gap.id,
        "document_id": doc.id,
        "filename": doc.filename,
        "status": "accepted",
    }


def dismiss_gap(db: Session, gap_id: int, workspace_id: int) -> dict:
    """Dismiss a gap suggestion."""
    gap = db.query(EvidenceGap).filter(
        EvidenceGap.id == gap_id,
        EvidenceGap.workspace_id == workspace_id,
    ).first()
    if not gap:
        raise ValueError(f"Evidence gap {gap_id} not found")

    gap.status = "dismissed"
    gap.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"gap_id": gap.id, "status": "dismissed"}


def generate_gaps_for_questionnaire(
    db: Session,
    workspace_id: int,
    questionnaire_id: int,
) -> dict:
    """Generate gap analysis for all insufficient-evidence answers in a questionnaire."""
    from app.models import Answer, Question
    from app.models.question_mapping_signal import QuestionMappingSignal

    insufficient = (
        db.query(Answer, Question)
        .join(Question, Question.id == Answer.question_id)
        .filter(
            Question.questionnaire_id == questionnaire_id,
            Answer.status == "insufficient_evidence",
        )
        .all()
    )
    if not insufficient:
        return {"generated": 0, "total_insufficient": 0}

    # Batch-load classification signals
    q_ids = [q.id for _, q in insufficient]
    signals = (
        db.query(QuestionMappingSignal)
        .filter(
            QuestionMappingSignal.question_id.in_(q_ids),
            QuestionMappingSignal.workspace_id == workspace_id,
        )
        .all()
    )
    signal_by_qid: dict[int, dict] = {}
    for sig in signals:
        if sig.question_id not in signal_by_qid:
            try:
                signal_by_qid[sig.question_id] = {
                    "frameworks": json.loads(sig.framework_labels_json or "[]"),
                    "subjects": json.loads(sig.subject_labels_json or "[]"),
                }
            except Exception:
                pass

    generated = 0
    for answer, question in insufficient:
        # Skip if open gap already exists
        existing = db.query(EvidenceGap).filter(
            EvidenceGap.question_id == question.id,
            EvidenceGap.questionnaire_id == questionnaire_id,
            EvidenceGap.status == "open",
        ).first()
        if existing:
            continue

        classification = signal_by_qid.get(question.id)
        citations = []
        try:
            citations = json.loads(answer.citations or "[]")
        except Exception:
            pass

        gap_data = generate_gap_analysis(
            question_text=question.text or "",
            classification=classification,
            evidence_snippets=citations,
            gating_reason=answer.gating_reason,
        )
        if gap_data and gap_data.get("proposed_policy_addition"):
            persist_gap(
                db, workspace_id, questionnaire_id,
                question.id, gap_data, answer_id=answer.id,
            )
            generated += 1

    db.commit()
    return {"generated": generated, "total_insufficient": len(insufficient)}
