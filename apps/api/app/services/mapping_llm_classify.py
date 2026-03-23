"""Structured LLM classification for mapping pipeline (enterprise).

For each question, extracts framework hints and subject/topic labels via a single
structured JSON LLM call. Results are persisted in `question_mapping_signals` and
used downstream by `question_to_controls` for better mapping quality.

Performance: parallel LLM calls with shared client, batch signal preload for idempotency.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.question_mapping_signal import QuestionMappingSignal
from app.services.registry_metadata import FRAMEWORK_LABELS, SUBJECT_AREA_LABELS

logger = logging.getLogger(__name__)

_PROMPT_VERSION = "v2"

_SYSTEM_PROMPT = (
    "You are a high-precision compliance classification engine. Given a security/compliance "
    "questionnaire question, identify which compliance frameworks and subject categories it pertains to.\n\n"
    "Return a single JSON object (no markdown fences):\n"
    "{\n"
    '  "frameworks": ["<framework_label>", ...],\n'
    '  "subjects": ["<subject_label>", ...],\n'
    '  "confidence": <0.0-1.0>\n'
    "}\n\n"
    f"ALLOWED framework labels (pick zero or more): {json.dumps(FRAMEWORK_LABELS)}\n"
    f"ALLOWED subject labels (pick one or more): {json.dumps(SUBJECT_AREA_LABELS)}\n\n"
    "CRITICAL RULES:\n"
    "- Never assign a framework solely from generic security vocabulary like access control, "
    "logging, encryption, incident response, backup, or least privilege.\n"
    "- Require explicit framework markers (e.g. 'SOC 2', 'HIPAA', 'ISO 27001', control IDs, "
    "Trust Services Criteria, PHI/ePHI, ISMS, Annex A) to assign a framework.\n"
    "- If the question uses generic security language without explicit framework markers, "
    "return an empty frameworks list.\n"
    "- Treat 'NIST' as a family — prefer specific subtypes (NIST CSF 2.0, NIST SP 800-53, "
    "NIST SP 800-171) when evidence supports it.\n"
    "- If uncertain about framework, return an empty frameworks list rather than guessing.\n"
    "- Always return at least one subject label (use 'Other' as fallback).\n"
    "- confidence reflects how certain you are about the classification (0.0-1.0).\n"
)

_MAX_RETRIES = 1
_RETRY_DELAY = 0.3
_PARALLEL_WORKERS = 6

_shared_client = None
_shared_client_key: str | None = None


def _get_client(api_key: str):
    """Reuse a single OpenAI client across calls (connection pooling)."""
    global _shared_client, _shared_client_key
    if _shared_client is not None and _shared_client_key == api_key:
        return _shared_client
    import openai
    _shared_client = openai.OpenAI(api_key=api_key, timeout=30.0)
    _shared_client_key = api_key
    return _shared_client


def _question_hash(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()[:32]


def _strip_json_fence(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def parse_classification_response(content: str | None) -> dict[str, Any] | None:
    """Parse model JSON output, validate against allowed labels, return cleaned dict or None."""
    if not content:
        return None
    text = _strip_json_fence(str(content))
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("mapping_llm_classify: JSON parse failed: %s", text[:200])
        return None
    if not isinstance(obj, dict):
        return None

    fw_set = set(FRAMEWORK_LABELS)
    subj_set = set(SUBJECT_AREA_LABELS)
    frameworks = [f for f in (obj.get("frameworks") or []) if isinstance(f, str) and f in fw_set]
    subjects = [s for s in (obj.get("subjects") or []) if isinstance(s, str) and s in subj_set]
    if not subjects:
        subjects = ["Other"]
    conf = 0.5
    try:
        conf = max(0.0, min(1.0, float(obj.get("confidence", 0.5))))
    except (TypeError, ValueError):
        pass

    return {"frameworks": frameworks, "subjects": subjects, "confidence": conf}


def _deterministic_preclassify(
    question_text: str, questionnaire_framework: str | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    """Run deterministic classifier before LLM. Returns (result_dict, skip_llm)."""
    from app.services.framework_classifier import classify_question as det_classify
    from app.services.framework_metadata import NAMING, SUBJECTS

    result = det_classify(question_text, questionnaire_framework)

    frameworks: list[str] = []
    if result.framework in NAMING:
        label = NAMING[result.framework]
        if label in set(FRAMEWORK_LABELS):
            frameworks.append(label)

    subjects: list[str] = []
    for sk in result.subjects:
        subj = SUBJECTS.get(sk)
        if subj and subj.display_label in set(SUBJECT_AREA_LABELS):
            subjects.append(subj.display_label)
    if not subjects:
        subjects = ["Other"]

    parsed = {
        "frameworks": frameworks,
        "subjects": subjects,
        "confidence": result.confidence,
        "confidence_level": result.confidence_level,
    }

    skip_llm = result.confidence_level == "high"
    return parsed, skip_llm


def classify_question_with_llm(
    question_text: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Call LLM for structured classification. Returns (parsed_result, raw_json_str) or (None, None)."""
    settings = get_settings()
    key = api_key or settings.openai_api_key
    if not key:
        return None, None
    mdl = model or settings.mapping_classification_model
    client = _get_client(key)

    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=mdl,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": question_text},
                ],
                temperature=0.1,
                max_tokens=200,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content if resp.choices else None
            parsed = parse_classification_response(raw)
            if parsed is not None:
                return parsed, raw
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY)
                continue
            return None, raw
        except Exception as exc:
            logger.warning("mapping_llm_classify: LLM call failed attempt %d: %s", attempt, exc)
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY)
                continue
            return None, None


def _preload_existing_signals(
    db: Session,
    question_ids: list[int],
    workspace_id: int,
    prompt_version: str,
) -> dict[int, QuestionMappingSignal]:
    """Batch-load existing signals in one query instead of N queries."""
    if not question_ids:
        return {}
    rows = (
        db.query(QuestionMappingSignal)
        .filter(
            QuestionMappingSignal.question_id.in_(question_ids),
            QuestionMappingSignal.workspace_id == workspace_id,
            QuestionMappingSignal.prompt_version == prompt_version,
        )
        .all()
    )
    by_qid: dict[int, QuestionMappingSignal] = {}
    for r in rows:
        if r.question_id not in by_qid:
            by_qid[r.question_id] = r
    return by_qid


def classify_and_persist(
    db: Session,
    question_id: int,
    question_text: str,
    workspace_id: int,
    questionnaire_id: int | None = None,
    *,
    model: str | None = None,
    api_key: str | None = None,
    force: bool = False,
    _preloaded: dict[int, QuestionMappingSignal] | None = None,
    questionnaire_framework: str | None = None,
) -> QuestionMappingSignal | None:
    """Classify a single question and persist the signal row.

    Uses deterministic pre-classification to skip the LLM for HIGH confidence,
    and to provide priors for the LLM prompt on MEDIUM/LOW confidence.
    """
    settings = get_settings()
    prompt_ver = settings.mapping_classification_prompt_version

    if not force:
        if _preloaded is not None and question_id in _preloaded:
            return _preloaded[question_id]
        existing = (
            db.query(QuestionMappingSignal)
            .filter(
                QuestionMappingSignal.question_id == question_id,
                QuestionMappingSignal.workspace_id == workspace_id,
                QuestionMappingSignal.prompt_version == prompt_ver,
            )
            .first()
        )
        if existing:
            return existing

    det_parsed, skip_llm = _deterministic_preclassify(question_text, questionnaire_framework)

    if skip_llm and det_parsed:
        parsed = det_parsed
        raw = json.dumps({"source": "deterministic", **det_parsed})
        quality = "deterministic_high"
    else:
        parsed_llm, raw = classify_question_with_llm(question_text, model=model, api_key=api_key)
        if parsed_llm is not None:
            parsed = parsed_llm
            quality = "llm_structured"
        elif det_parsed:
            parsed = det_parsed
            raw = json.dumps({"source": "deterministic_fallback", **det_parsed})
            quality = "deterministic_fallback"
        else:
            parsed = None
            quality = "heuristic_fallback"

    mdl = model or settings.mapping_classification_model

    signal = QuestionMappingSignal(
        question_id=question_id,
        workspace_id=workspace_id,
        questionnaire_id=questionnaire_id,
        framework_labels_json=json.dumps(parsed["frameworks"]) if parsed else None,
        subject_labels_json=json.dumps(parsed["subjects"]) if parsed else None,
        raw_llm_json=raw,
        model=mdl,
        prompt_version=prompt_ver,
        mapping_quality=quality,
        created_at=datetime.now(timezone.utc),
    )
    db.add(signal)
    return signal


def _classify_one_thread_safe(
    question_id: int,
    question_text: str,
    model: str,
    api_key: str,
    questionnaire_framework: str | None = None,
) -> tuple[int, dict[str, Any] | None, str | None, str]:
    """Thread-safe classification (no DB access).

    Returns (question_id, parsed, raw, quality).
    Runs deterministic pre-classification first; skips LLM for HIGH confidence.
    """
    det_parsed, skip_llm = _deterministic_preclassify(question_text, questionnaire_framework)

    if skip_llm and det_parsed:
        raw = json.dumps({"source": "deterministic", **det_parsed})
        return question_id, det_parsed, raw, "deterministic_high"

    parsed, raw = classify_question_with_llm(question_text, model=model, api_key=api_key)
    if parsed is not None:
        return question_id, parsed, raw, "llm_structured"
    if det_parsed:
        raw = json.dumps({"source": "deterministic_fallback", **det_parsed})
        return question_id, det_parsed, raw, "deterministic_fallback"
    return question_id, None, None, "heuristic_fallback"


def bulk_classify_and_persist(
    db: Session,
    questions: list[Any],
    workspace_id: int,
    questionnaire_id: int | None = None,
    *,
    force: bool = False,
    on_progress: Any | None = None,
    questionnaire_framework: str | None = None,
) -> dict[str, int]:
    """Classify a batch of questions with deterministic pre-scoring + parallel LLM calls."""
    stats = {"classified": 0, "cached": 0, "failed": 0, "total": len(questions)}
    settings = get_settings()
    api_key = settings.openai_api_key
    if not api_key:
        stats["failed"] = len(questions)
        return stats

    model = settings.mapping_classification_model
    prompt_ver = settings.mapping_classification_prompt_version

    q_list = []
    for q in questions:
        text = q.text if hasattr(q, "text") else str(q)
        qid = q.id if hasattr(q, "id") else 0
        q_list.append((qid, text))

    preloaded: dict[int, QuestionMappingSignal] = {}
    if not force:
        preloaded = _preload_existing_signals(db, [qid for qid, _ in q_list], workspace_id, prompt_ver)

    needs_classify = [(qid, text) for qid, text in q_list if force or qid not in preloaded]
    for qid in [qid for qid, _ in q_list if qid in preloaded]:
        stats["cached"] += 1

    classify_results: dict[int, tuple[dict[str, Any] | None, str | None, str]] = {}
    if needs_classify:
        workers = min(_PARALLEL_WORKERS, len(needs_classify))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _classify_one_thread_safe, qid, text, model, api_key,
                    questionnaire_framework,
                ): qid
                for qid, text in needs_classify
            }
            for future in as_completed(futures):
                qid = futures[future]
                try:
                    _, parsed, raw, quality = future.result()
                    classify_results[qid] = (parsed, raw, quality)
                except Exception as exc:
                    logger.warning("bulk_classify: question %d failed: %s", qid, exc)
                    classify_results[qid] = (None, None, "heuristic_fallback")
                done = stats["cached"] + len(classify_results)
                if on_progress and done % 5 == 0:
                    on_progress(done, len(questions))

    for qid, text in q_list:
        if qid in preloaded and not force:
            continue
        parsed, raw, quality = classify_results.get(qid, (None, None, "heuristic_fallback"))
        signal = QuestionMappingSignal(
            question_id=qid,
            workspace_id=workspace_id,
            questionnaire_id=questionnaire_id,
            framework_labels_json=json.dumps(parsed["frameworks"]) if parsed else None,
            subject_labels_json=json.dumps(parsed["subjects"]) if parsed else None,
            raw_llm_json=raw,
            model=model,
            prompt_version=prompt_ver,
            mapping_quality=quality,
            created_at=datetime.now(timezone.utc),
        )
        db.add(signal)
        if parsed:
            stats["classified"] += 1
        else:
            stats["failed"] += 1

    db.commit()
    return stats
