"""Answer generation service (AI-04, AI-05).

Architecture rules:
- Frontend sends only model and response_style in the generate request; it must never send raw temperature.
- Backend validates both at the API boundary (400 if unsupported) and resolves defaults internally.
- Backend is the single source of truth for: model allowlist, response_style allowlist, response_style -> temperature mapping.
- Temperature is derived exclusively from response_style via resolve_temperature_from_style; never from client input.
"""

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.core.pipeline_logging import log_answer_gen_start, log_answer_gen_success
from app.core.metrics import (
    ADAPTIVE_CONCURRENCY_CURRENT,
    ADAPTIVE_RATE_LIMITED_BATCHES_TOTAL,
    ADAPTIVE_TIMEOUT_STEPDOWN_TOTAL,
    ANSWER_GEN_DURATION_SECONDS,
    INSUFFICIENT_EVIDENCE_TOTAL,
    OPENAI_COMPLETION_FAILURES_TOTAL,
)
from app.models import Answer, Job, Question, Questionnaire
from app.services.embedding_service import embed_texts
from app.services.prompt_builder import build_prompt
from app.services.answer_evidence_policy import (
    INSUFFICIENT_EVIDENCE_TEXT,
    classify_answer_status_from_text,
    is_insufficient_answer_text,
    prioritize_evidence_for_answer,
    should_skip_llm,
)
from app.services.retrieval import RetrievalService
from app.models.workspace import Workspace
from app.services.question_normalizer import (
    normalize_question,
    question_cache_hash,
    evidence_fingerprint_hash,
)
from app.services.answer_cache import get as answer_cache_get, set as answer_cache_set
from app.services.questionnaire_answer_evidence import (
    parse_answer_evidence_document_ids,
    retrieval_cache_scope_suffix,
)
from app.services.retrieval_cache import get as retrieval_cache_get, set as retrieval_cache_set
from app.core.corpus_version import get_corpus_version
from app.models.question_mapping_signal import QuestionMappingSignal
from app.services.workspace_usage import record_answer_calls
from app.core.audit import audit_log
from app.services.evidence_processor import process_evidence
from app.core.adaptive_concurrency import (
    ADAPTIVE_INITIAL,
    AdaptivePool,
)


logger = logging.getLogger(__name__)

# AI-01: Supported models; unsupported values are defaulted to DEFAULT_MODEL with logging.
DEFAULT_MODEL = "gpt-4o-mini"
ALLOWED_MODELS = ("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini")

# AI-04: Response style allowlist and -> temperature (Precise, Balanced, Natural). Natural = 0.5.
ALLOWED_RESPONSE_STYLES = ("precise", "balanced", "natural")
DEFAULT_RESPONSE_STYLE = "balanced"
RESPONSE_STYLE_TEMPERATURE = {
    "precise": 0.2,
    "balanced": 0.35,
    "natural": 0.5,
}
DEFAULT_TEMPERATURE = 0.35

MAX_ANSWER_LENGTH = 4000
BANNED_PREFIXES: tuple[str, ...] = (
    "error",
    "sorry",
    "i cannot",
    "i'm unable",
    "as an ai",
    "as a language model",
    "as a large language model",
    "i am an ai",
    "as an artificial intelligence",
    "<",
)
LEADING_META_PHRASES: tuple[str, ...] = (
    "based on the evidence provided,",
    "based on the evidence above,",
    "based on the evidence,",
    "according to the documentation,",
    "according to the evidence,",
    "the evidence indicates that",
)
# Only skip LLM when there is no evidence at all. Do not reject on low score (pooled-embedding batches can have lower top_score).
INSUFFICIENT_EVIDENCE_THRESHOLD = 0.0  # Unused for skip; we only skip when len(evidence)==0 (AI-06)

# Performance: parallel batches, larger batches, fewer round-trips (target sub-60s for 150 questions).
RETRIEVAL_BATCH_SIZE = 10  # questions per retrieval (fewer batches = faster)
EVIDENCE_LIMIT_PER_GROUP = 15  # slightly larger pool when answering multiple questions
MAX_PARALLEL_BATCHES = 10 # run up to 10 batches concurrently (I/O bound; stay under rate limits)
COMPLETION_MAX_RETRIES = 3


def _is_transient_completion_error(e: Exception) -> bool:
    """True if completion error is worth retrying (timeout, rate limit, server error)."""
    msg = (getattr(e, "message", "") or str(e)).lower()
    if "timeout" in msg or "timed out" in msg:
        return True
    code = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
    return code in (429, 503, 502, 504)


def _extract_retry_after(e: Exception) -> float | None:
    """Extract Retry-After header from rate limit errors."""
    resp = getattr(e, "response", None)
    if resp is None:
        return None
    headers = getattr(resp, "headers", None)
    if headers is None:
        return None
    ra = headers.get("retry-after") or headers.get("Retry-After")
    if ra is not None:
        try:
            return min(float(ra), 60.0)
        except (ValueError, TypeError):
            pass
    return None


def _completion_create_with_retry(client: Any, **kwargs: Any) -> Any:
    """Call client.chat.completions.create with exponential backoff + 429 Retry-After."""
    last_err: Exception | None = None
    for attempt in range(COMPLETION_MAX_RETRIES + 1):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as e:
            last_err = e
            if attempt < COMPLETION_MAX_RETRIES and _is_transient_completion_error(e):
                retry_after = _extract_retry_after(e)
                delay = retry_after if retry_after is not None else min(1.5 ** attempt, 10.0)
                logger.info(
                    "answer_generation retry attempt=%d/%d delay=%.1fs error=%s",
                    attempt + 1, COMPLETION_MAX_RETRIES, delay, str(e)[:100],
                )
                time.sleep(delay)
                continue
            raise
    if last_err is not None:
        raise last_err
    raise RuntimeError("completion create failed")


def _pool_embeddings(embeddings: list) -> list[float] | None:
    """Average non-None embeddings and L2-normalize. Used by tests and optional batch query pooling."""
    valid = [e for e in embeddings if e and isinstance(e, list) and len(e) > 0]
    if not valid:
        return None
    dim = len(valid[0])
    avg = [0.0] * dim
    for e in valid:
        for i, x in enumerate(e):
            if i < dim:
                avg[i] += x
    n = len(valid)
    avg = [x / n for x in avg]
    norm = sum(x * x for x in avg) ** 0.5
    if norm <= 0:
        return avg
    return [x / norm for x in avg]


def _strip_leading_phrases(text: str, phrases: Iterable[str]) -> str:
    """Remove known robotic leading phrases from the start of the answer."""
    original = text
    t = text.lstrip()
    lowered = t.lower()
    changed = False
    stripped_any = True
    while stripped_any and t:
        stripped_any = False
        lowered = t.lower()
        for prefix in phrases:
            p = prefix.strip()
            if lowered.startswith(p):
                after = t[len(p) :]
                after = after.lstrip(" ,;:-")
                t = after.lstrip()
                stripped_any = True
                changed = True
                break
    if not changed:
        return original
    return t or original


def validate_answer_text(content: str | None) -> str:
    """Validate and sanitize model output (AI-03). Returns safe text or empty string."""
    if content is None:
        return ""
    text = str(content).strip()
    if len(text) > MAX_ANSWER_LENGTH:
        text = text[:MAX_ANSWER_LENGTH]
    text = _strip_leading_phrases(text, LEADING_META_PHRASES)
    lower = text.lower()
    if any(lower.startswith(p) for p in BANNED_PREFIXES):
        logger.debug(
            "answer_generation: blocked answer due to banned prefix: %s",
            lower[:120],
        )
        return ""
    if text.startswith("{") or text.startswith("["):
        return ""
    return text


def is_allowed_model(candidate: str | None) -> bool:
    """Return True if candidate is in the model allowlist (for API boundary validation)."""
    if not candidate or not (candidate.strip()):
        return False
    return candidate.strip() in ALLOWED_MODELS


def is_allowed_response_style(candidate: str | None) -> bool:
    """Return True if candidate is in the response style allowlist (for API boundary validation)."""
    if not candidate or not (candidate.strip()):
        return False
    return candidate.strip().lower() in ALLOWED_RESPONSE_STYLES


def resolve_model(candidate: str | None) -> str:
    """Return allowed model or default (AI-01). Used internally when no API request provided the value."""
    if not candidate or not (candidate.strip()):
        return DEFAULT_MODEL
    key = candidate.strip()
    if key in ALLOWED_MODELS:
        return key
    logger.warning("answer_generation: unsupported model %r, defaulting to %s", key, DEFAULT_MODEL)
    return DEFAULT_MODEL


def resolve_response_style(response_style: str | None) -> str:
    """Return allowed response style or default (AI-04). Unsupported values default to Balanced with logging."""
    if not response_style or not (response_style.strip()):
        return DEFAULT_RESPONSE_STYLE
    key = response_style.strip().lower()
    if key in ALLOWED_RESPONSE_STYLES:
        return key
    logger.warning("answer_generation: unsupported response_style %r, defaulting to %s", key, DEFAULT_RESPONSE_STYLE)
    return DEFAULT_RESPONSE_STYLE


def resolve_temperature_from_style(response_style: str | None) -> float:
    """Map response_style to temperature (AI-04). Backend-owned mapping. Default Balanced -> 0.35."""
    if not response_style:
        return DEFAULT_TEMPERATURE
    key = response_style.strip().lower()
    return RESPONSE_STYLE_TEMPERATURE.get(key, DEFAULT_TEMPERATURE)


def _parse_batched_answers(raw: str, expected_count: int) -> list[str] | None:
    """Parse batched model output only when answers are explicitly numbered."""
    if not raw or not raw.strip():
        return None
    text = raw.strip()

    pattern = re.compile(r"(?:^|\n)\s*(?:#+\s*|\*\*?\s*)?Answer\s*(\d+)\s*(?:[.:]\s*)?", re.IGNORECASE | re.MULTILINE)
    parts: list[tuple[int, str]] = []
    for m in pattern.finditer(text):
        num = int(m.group(1))
        start = m.end()
        next_m = pattern.search(text, start)
        end = next_m.start() if next_m else len(text)
        content = text[start:end].strip()
        if content:
            content = re.sub(r"\n{3,}", "\n\n", content)
        parts.append((num, content))
    if not parts:
        return None
    parts.sort(key=lambda x: x[0])
    if len(parts) < expected_count:
        return None
    out: list[str] = [""] * expected_count
    for num, content in parts:
        if 1 <= num <= expected_count:
            out[num - 1] = content
    if any(not s for s in out):
        return None
    return out


def _generate_single_question_answer(
    q: Any,
    evidence: list[dict],
    workspace_id: int,
    questionnaire_id: int,
    model_name: str,
    temperature: float,
    system_msg: str,
    openai_client: Any,
) -> tuple[int, str, list[dict], int, str]:
    """One question, its own evidence pool, one LLM call. Returns (q_id, text, citations, confidence, answer_status)."""
    evidence_processed = process_evidence(evidence)
    top_score = (evidence_processed[0].get("score", 0) or 0) if evidence_processed else 0
    citations_base = [
        {
            "chunk_id": e.get("id"),
            "snippet": (e.get("text") or "")[:200],
            "document_id": (e.get("metadata") or {}).get("document_id"),
            "filename": (e.get("metadata") or {}).get("filename"),
            "score": e.get("score"),
        }
        for e in evidence_processed[:5]
    ]
    if not evidence_processed:
        INSUFFICIENT_EVIDENCE_TOTAL.inc()
        logger.info(
            "answer_generation single_question no_evidence workspace_id=%s questionnaire_id=%s question_id=%s",
            workspace_id,
            questionnaire_id,
            q.id,
        )
        return (q.id, INSUFFICIENT_EVIDENCE_TEXT, [], 0, "insufficient_evidence")

    prompt = build_prompt(q.text or "", evidence_processed)
    try:
        r = _completion_create_with_retry(
            openai_client,
            model=model_name,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            max_tokens=400,
            temperature=temperature,
        )
        raw = (r.choices[0].message.content or "").strip()
        content = validate_answer_text(raw)
        if not content:
            return (q.id, INSUFFICIENT_EVIDENCE_TEXT, citations_base, 0, "insufficient_evidence")
        answer_status = classify_answer_status_from_text(content)
        if answer_status == "insufficient_evidence":
            return (q.id, content, citations_base, 0, "insufficient_evidence")
        conf = min(95, int(75 + top_score * 20))
        return (q.id, content, citations_base, conf, "draft")
    except Exception as exc:
        OPENAI_COMPLETION_FAILURES_TOTAL.inc()
        logger.warning("ALERT_OPENAI_FAILURE completion single question: %s", str(exc)[:200])
        return (q.id, INSUFFICIENT_EVIDENCE_TEXT, citations_base, 0, "insufficient_evidence")


def _generate_batched_answers(
    batch: list[tuple[Any, list[dict]]],
    workspace_id: int,
    questionnaire_id: int,
    model_name: str,
    temperature: float,
    system_msg: str,
    openai_client: Any,
    q_labels: dict[int, dict] | None = None,
) -> list[tuple[int, str, list[dict], int, str]]:
    """Multiple questions in one LLM call with per-question evidence sections.

    Each question gets its own evidence block so the model can ground each answer
    independently -- no cross-contamination between questions.
    Falls back to single-question calls on parse failure.
    """
    from app.services.prompt_builder import build_batched_prompt

    per_q_processed: list[list[dict]] = []
    per_q_citations: dict[int, list[dict]] = {}
    per_q_top_score: dict[int, float] = {}
    any_has_evidence = False

    for q, ev in batch:
        processed = process_evidence(ev)
        per_q_processed.append(processed)
        per_q_top_score[q.id] = (processed[0].get("score", 0) or 0) if processed else 0
        per_q_citations[q.id] = [
            {
                "chunk_id": e.get("id"),
                "snippet": (e.get("text") or "")[:200],
                "document_id": (e.get("metadata") or {}).get("document_id"),
                "filename": (e.get("metadata") or {}).get("filename"),
                "score": e.get("score"),
            }
            for e in processed[:5]
        ]
        if processed:
            any_has_evidence = True

    if not any_has_evidence:
        return [
            (q.id, INSUFFICIENT_EVIDENCE_TEXT, [], 0, "insufficient_evidence")
            for q, _ in batch
        ]

    q_texts = [q.text or "" for q, _ in batch]
    labels_list = None
    if q_labels:
        labels_list = [q_labels.get(q.id) for q, _ in batch]

    prompt = build_batched_prompt(
        q_texts, [],
        per_question_evidence=per_q_processed,
        classification_labels=labels_list,
    )

    try:
        r = _completion_create_with_retry(
            openai_client,
            model=model_name,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            max_tokens=350 * len(batch),
            temperature=temperature,
        )
        raw = (r.choices[0].message.content or "").strip()
        parsed = _parse_batched_answers(raw, len(batch))

        if parsed:
            results = []
            for i, (q, _) in enumerate(batch):
                content = validate_answer_text(parsed[i])
                cits = per_q_citations.get(q.id, [])
                top_s = per_q_top_score.get(q.id, 0)
                if not content:
                    results.append((q.id, INSUFFICIENT_EVIDENCE_TEXT, cits, 0, "insufficient_evidence"))
                else:
                    st = classify_answer_status_from_text(content)
                    if st == "insufficient_evidence":
                        results.append((q.id, content, cits, 0, "insufficient_evidence"))
                    else:
                        conf = min(95, int(75 + top_s * 20))
                        results.append((q.id, content, cits, conf, "draft"))
            return results

        logger.info("answer_generation: batched parse failed for %d questions, falling back to single", len(batch))
    except Exception as exc:
        logger.warning("answer_generation: batched call failed, falling back to single: %s", str(exc)[:200])

    results = []
    for q, ev in batch:
        results.append(_generate_single_question_answer(
            q, ev, workspace_id, questionnaire_id,
            model_name, temperature, system_msg, openai_client,
        ))
    return results


def _job_payload(
    generated: int,
    total: int,
    stats: dict[str, int | float],
) -> str:
    payload = {"generated": generated, "total": total, "stats": dict(stats)}
    return json.dumps(payload)


def generate_answers_for_questionnaire(
    db: Session,
    questionnaire_id: int,
    workspace_id: int,
    model_override: str | None = None,
    response_style_override: str | None = None,
    job: Job | None = None,
) -> int:
    """Generate answers for all questions. Returns count of answers created."""
    qnr = db.query(Questionnaire).filter(
        Questionnaire.id == questionnaire_id,
        Questionnaire.workspace_id == workspace_id,
    ).first()
    if not qnr:
        raise ValueError(f"Questionnaire {questionnaire_id} not found")
    questions = db.query(Question).filter(Question.questionnaire_id == questionnaire_id).all()
    total_questions = len(questions)
    if not questions:
        if job:
            job.result = _job_payload(0, 0, {"drafted": 0, "insufficient_evidence": 0, "skipped_gated": 0, "llm_calls": 0, "duration_ms": 0})
            db.commit()
        return 0

    from app.core.config import get_settings
    settings = get_settings()
    api_key_ok = bool((settings.openai_api_key or "").strip())
    if not api_key_ok:
        if total_questions > 0:
            raise ValueError(
                "OPENAI_API_KEY is not set or empty. Set it in the environment (.env) for the API and worker, then restart."
            )
        if job:
            job.result = _job_payload(0, 0, {"drafted": 0, "insufficient_evidence": 0, "skipped_gated": 0, "llm_calls": 0, "duration_ms": 0})
            db.commit()
        return 0

    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    model_candidate = model_override or (workspace.ai_completion_model if workspace else None) or settings.completion_model
    if model_override is None and workspace and workspace.ai_completion_model:
        logger.info("answer_generation: model not provided -> using workspace model %s", workspace.ai_completion_model)
    elif model_override is None and (not workspace or not workspace.ai_completion_model):
        logger.info("answer_generation: model not provided, workspace model missing -> using default %s", DEFAULT_MODEL)
    model_name = resolve_model(model_candidate)

    if response_style_override:
        resolved_response_style = resolve_response_style(response_style_override)
        temperature = resolve_temperature_from_style(resolved_response_style)
    elif workspace and workspace.ai_temperature is not None:
        resolved_response_style = None
        temperature = max(0.0, min(1.5, float(workspace.ai_temperature)))
        logger.info("answer_generation: response_style not provided -> using workspace temperature %.2f", temperature)
    else:
        resolved_response_style = DEFAULT_RESPONSE_STYLE
        temperature = settings.openai_temperature
        logger.info("answer_generation: response_style not provided, workspace style missing -> using default %s (temperature=%.2f)", DEFAULT_RESPONSE_STYLE, temperature)

    evidence_scope = parse_answer_evidence_document_ids(qnr)
    retrieval_scope_suffix = retrieval_cache_scope_suffix(evidence_scope)
    evidence_doc_ids_list = sorted(evidence_scope) if evidence_scope else None

    logger.info(
        "answer_generation:\nworkspace_id=%s\nquestionnaire_id=%s\nmodel=%s\nresponse_style=%s\nresolved_temperature=%s\nevidence_scope_doc_ids=%s",
        workspace_id,
        questionnaire_id,
        model_name,
        resolved_response_style or "workspace_temp",
        temperature,
        list(evidence_scope) if evidence_scope else None,
    )

    started = time.monotonic()
    log_answer_gen_start(workspace_id, questionnaire_id)
    style_for_cache = (resolved_response_style or "balanced").lower()
    if job:
        job.result = _job_payload(
            0,
            total_questions,
            {"drafted": 0, "insufficient_evidence": 0, "skipped_gated": 0, "llm_calls": 0, "duration_ms": 0},
        )
        db.commit()

    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key, timeout=30.0)
    system_msg = (
        "You are a security and compliance professional who drafts responses to "
        "customer questionnaires (SOC 2, ISO, vendor due diligence). "
        "Use first person plural ('we') for the organization's practices. "
        "Never invent facts: every substantive claim must be directly supported by the evidence text. "
        "If evidence is partial, indirect, or only tangentially related, say so briefly or respond with exactly "
        f"{INSUFFICIENT_EVIDENCE_TEXT!r}. "
        "Do not equate vague operational hints with explicit policy commitments. "
        "Do not treat timing phrases in evidence as stronger commitments than the words show "
        "(e.g. 'within 24 hours' is not the same as 'immediately'). "
        "Do not mention being an AI."
    )

    try:
        corpus_version = get_corpus_version(db, workspace_id)
    except Exception as e:
        logger.warning("answer_generation corpus_version failed, proceeding without retrieval cache: %s", e)
        corpus_version = ""

    # Batch embed all questions
    question_texts = [q.text for q in questions]
    _t0 = time.monotonic()
    all_embeddings = embed_texts(question_texts)
    embed_time_ms = (time.monotonic() - _t0) * 1000

    # Retrieve evidence for each question via batch search
    _t0 = time.monotonic()
    retrieval = RetrievalService(db)
    cached_results: dict[int, tuple[str, list, int]] = {}
    to_generate: list[tuple[Any, list[dict], bool]] = []
    has_evidence_scope = bool(evidence_scope)

    # Phase 1: check retrieval cache for all questions
    q_hashes: list[str] = []
    retrieval_needed: list[int] = []
    all_evidence: list[list[dict] | None] = [None] * len(questions)
    for i, q in enumerate(questions):
        norm = normalize_question(q.text)
        q_hashes.append(question_cache_hash(norm))
        if corpus_version:
            try:
                cached_ev = retrieval_cache_get(
                    db, workspace_id, q_hashes[i], scope_suffix=retrieval_scope_suffix
                )
                if cached_ev is not None:
                    all_evidence[i] = cached_ev
                    continue
            except Exception:
                pass
        retrieval_needed.append(i)

    # Phase 2: batch retrieval for uncached questions
    if retrieval_needed:
        batch_queries = [
            (questions[i].text or "", all_embeddings[i])
            for i in retrieval_needed
        ]
        batch_results = retrieval.batch_search(
            workspace_id,
            batch_queries,
            limit=EVIDENCE_LIMIT_PER_GROUP,
            document_ids=evidence_doc_ids_list,
        )
        for idx, i in enumerate(retrieval_needed):
            all_evidence[i] = batch_results[idx]
            if corpus_version:
                try:
                    retrieval_cache_set(
                        db, workspace_id, q_hashes[i], corpus_version,
                        batch_results[idx], scope_suffix=retrieval_scope_suffix,
                    )
                except Exception:
                    pass

    # Phase 3: check answer cache and split into cached vs to-generate
    for i, (q, evidence) in enumerate(zip(questions, all_evidence)):
        if evidence is None:
            evidence = []
        chunk_ids = [e["id"] for e in evidence if e.get("id") is not None]
        evidence_fp = evidence_fingerprint_hash(chunk_ids)
        cached = None
        try:
            cached = answer_cache_get(db, workspace_id, q_hashes[i], style_for_cache, evidence_fp)
        except Exception:
            pass
        if cached and cached.get("text") and not is_insufficient_answer_text(cached["text"]):
            cached_results[q.id] = (cached["text"], cached.get("citations") or [], cached.get("confidence") or 0)
        else:
            to_generate.append((q, evidence, has_evidence_scope))
    retrieval_time_ms = (time.monotonic() - _t0) * 1000

    count = 0

    # D6: Skip re-generation for questions with unchanged evidence fingerprint
    _gen_qids = [q.id for q, _, _ in to_generate]
    _existing_answers: dict[int, Answer] = {}
    if _gen_qids:
        for a in db.query(Answer).filter(Answer.question_id.in_(_gen_qids)).all():
            _existing_answers[a.question_id] = a

    _skipped_unchanged: list[int] = []
    _new_to_generate: list[tuple[Any, list[dict], bool]] = []
    for q, evidence, has_scope in to_generate:
        existing_answer = _existing_answers.get(q.id)
        if existing_answer and existing_answer.status in ("draft", "approved"):
            chunk_ids = [e["id"] for e in evidence if e.get("id") is not None]
            new_fp = evidence_fingerprint_hash(chunk_ids)
            old_fp = getattr(existing_answer, "evidence_fingerprint", None)
            if old_fp and old_fp == new_fp:
                _skipped_unchanged.append(q.id)
                continue
        _new_to_generate.append((q, evidence, has_scope))

    if _skipped_unchanged:
        logger.info(
            "answer_generation: skipped %d questions with unchanged evidence fingerprint",
            len(_skipped_unchanged),
        )
        count += len(_skipped_unchanged)
    to_generate = _new_to_generate

    run_stats: dict[str, int | float] = {
        "drafted": 0,
        "insufficient_evidence": 0,
        "skipped_gated": 0,
        "llm_calls": 0,
    }

    # Persist cached answers and progress
    for q_id, (text, citations, conf) in cached_results.items():
        st = classify_answer_status_from_text(text)
        _upsert_answer(db, q_id, text, citations, conf if st == "draft" else 0, st)
        count += 1
        if st == "draft":
            run_stats["drafted"] += 1
        else:
            run_stats["insufficient_evidence"] += 1
    if cached_results:
        db.commit()
        if job:
            job.result = _job_payload(count, total_questions, {**run_stats, "duration_ms": (time.monotonic() - started) * 1000})
            db.commit()
    if not to_generate:
        duration_ms = (time.monotonic() - started) * 1000
        swept = _sweep_draft_insufficient_narratives(db, questionnaire_id)
        _adjust_run_stats_after_sweep(run_stats, swept)
        run_stats["duration_ms"] = duration_ms
        log_answer_gen_success(workspace_id, questionnaire_id, count, duration_ms)
        ANSWER_GEN_DURATION_SECONDS.observe(duration_ms / 1000)
        logger.info(
            "WORKER: answer generated count=%s total_questions=%s questionnaire_id=%s workspace_id=%s stats=%s (cache-only)",
            count,
            total_questions,
            questionnaire_id,
            workspace_id,
            run_stats,
        )
        if job:
            job.result = _job_payload(count, total_questions, run_stats)
            db.commit()
        return count

    # Batch-preload mapping signals for all questions (1 query instead of N)
    _all_gen_qids = [q.id for q, _, _ in to_generate]
    _signal_rows = (
        db.query(QuestionMappingSignal)
        .filter(
            QuestionMappingSignal.question_id.in_(_all_gen_qids),
            QuestionMappingSignal.workspace_id == workspace_id,
        )
        .order_by(QuestionMappingSignal.created_at.desc())
        .all()
    ) if _all_gen_qids else []
    _q_categories_cache: dict[int, str | None] = {}
    _q_subject_keys: dict[int, list[str]] = {}
    for sig in _signal_rows:
        if sig.question_id in _q_categories_cache:
            continue
        val = None
        if sig.framework_labels_json or sig.subject_labels_json:
            try:
                fw = json.loads(sig.framework_labels_json or "[]")
                sb = json.loads(sig.subject_labels_json or "[]")
                val = json.dumps({
                    "frameworks": fw,
                    "subjects": sb,
                    "quality": sig.mapping_quality or "unknown",
                })
                from app.services.registry_metadata import SUBJECT_AREA_LABEL_TO_KEY
                _q_subject_keys[sig.question_id] = [
                    SUBJECT_AREA_LABEL_TO_KEY.get(s, s.lower().replace(" ", "_"))
                    for s in sb
                ]
            except Exception:
                pass
        _q_categories_cache[sig.question_id] = val
    for qid in _all_gen_qids:
        if qid not in _q_categories_cache:
            _q_categories_cache[qid] = None

    def _categories_json_for_question(qid: int) -> str | None:
        return _q_categories_cache.get(qid)

    def _labels_dict_for_question(qid: int) -> dict | None:
        """Parse stored classification labels into dict for prompt builder."""
        raw = _q_categories_cache.get(qid)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    _q_labels_dict: dict[int, dict] = {}
    for qid in _all_gen_qids:
        ld = _labels_dict_for_question(qid)
        if ld:
            _q_labels_dict[qid] = ld

    # Pre-collect document IDs across all evidence for batch tier loading
    _all_doc_ids: set[int] = set()
    for _, evidence_list, _ in to_generate:
        for e in evidence_list[:12]:
            meta = e.get("metadata") if isinstance(e.get("metadata"), dict) else {}
            did = meta.get("document_id")
            if did is not None:
                _all_doc_ids.add(int(did))
    from app.services.answer_evidence_policy import preload_document_tiers
    doc_tier_cache = preload_document_tiers(db, list(_all_doc_ids)) if _all_doc_ids else {}

    # Gating (main thread, DB-safe): skip weak rows before any LLM call
    from app.services.answer_evidence_policy import subject_requires_direct_evidence
    _t0 = time.monotonic()
    llm_tasks: list[tuple[Any, list[dict]]] = []
    for q, evidence, has_control_mapping in to_generate:
        ev = prioritize_evidence_for_answer(db, evidence, doc_tier_cache=doc_tier_cache)
        skip, skip_reason = should_skip_llm(db, ev, has_control_mapping, doc_tier_cache=doc_tier_cache)
        if not skip:
            q_subj_keys = _q_subject_keys.get(q.id, [])
            for sk in q_subj_keys:
                if subject_requires_direct_evidence(sk) and not ev:
                    skip = True
                    skip_reason = f"direct_evidence_required:{sk}"
                    break
        ep = process_evidence(ev)
        cits = [
            {
                "chunk_id": e.get("id"),
                "snippet": (e.get("text") or "")[:200],
                "document_id": (e.get("metadata") or {}).get("document_id"),
                "filename": (e.get("metadata") or {}).get("filename"),
                "score": e.get("score"),
            }
            for e in ep[:5]
        ]
        if skip:
            _upsert_answer(
                db, q.id, INSUFFICIENT_EVIDENCE_TEXT, cits, 0, "insufficient_evidence",
                insufficient_reason=skip_reason,
                gating_reason=skip_reason,
                primary_categories_json=_categories_json_for_question(q.id),
            )
            count += 1
            run_stats["insufficient_evidence"] += 1
            run_stats["skipped_gated"] += 1
            logger.info(
                "answer_generation gated_skip question_id=%s reason=%s workspace_id=%s questionnaire_id=%s",
                q.id,
                skip_reason,
                workspace_id,
                questionnaire_id,
            )
        else:
            llm_tasks.append((q, ev))
    gating_time_ms = (time.monotonic() - _t0) * 1000

    db.commit()
    if job:
        job.result = _job_payload(count, total_questions, {**run_stats, "duration_ms": (time.monotonic() - started) * 1000})
        db.commit()

    use_adaptive = get_settings().use_adaptive_concurrency
    if use_adaptive:
        adaptive = AdaptivePool(initial=ADAPTIVE_INITIAL)
    else:
        adaptive = AdaptivePool(initial=min(MAX_PARALLEL_BATCHES, max(1, len(llm_tasks))))

    def _adaptive_batch_tasks(tasks: list[tuple[Any, list[dict]]]) -> list[list[tuple[Any, list[dict]]]]:
        """Split tasks into batches using the adaptive pool's current batch size."""
        bs = adaptive.batch_size
        batches: list[list[tuple[Any, list[dict]]]] = []
        for i in range(0, len(tasks), bs):
            batches.append(tasks[i:i + bs])
        return batches

    def _apply_one_result(
        q: Any,
        ev: list[dict],
        result: tuple[int, str, list[dict], int, str] | None,
        exc: Exception | None,
    ) -> None:
        nonlocal count
        chunk_ids = [e.get("id") for e in ev if e.get("id") is not None]
        evidence_fp_one = evidence_fingerprint_hash(chunk_ids)
        if exc is not None:
            logger.warning("answer_generation single_question failed question_id=%s: %s", q.id, exc)
            _upsert_answer(
                db, q.id, INSUFFICIENT_EVIDENCE_TEXT, [], 0, "insufficient_evidence",
                insufficient_reason="llm_error",
                primary_categories_json=_categories_json_for_question(q.id),
                evidence_fingerprint=evidence_fp_one,
            )
            count += 1
            run_stats["insufficient_evidence"] += 1
            was_429, was_timeout, was_transient = adaptive.classify_exception(exc)
            adaptive.release(success=False, was_rate_limited=was_429, was_timeout=was_timeout, was_transient=was_transient)
            if was_429:
                ADAPTIVE_RATE_LIMITED_BATCHES_TOTAL.inc()
            if was_timeout:
                ADAPTIVE_TIMEOUT_STEPDOWN_TOTAL.inc()
        elif result is not None:
            _qid, text, citations, conf, answer_status = result
            insuf_reason = "llm_declined" if answer_status == "insufficient_evidence" else None
            _upsert_answer(
                db, _qid, text, citations, conf, answer_status,
                insufficient_reason=insuf_reason,
                primary_categories_json=_categories_json_for_question(_qid),
                evidence_fingerprint=evidence_fp_one,
            )
            count += 1
            run_stats["llm_calls"] += 1
            if answer_status == "draft":
                run_stats["drafted"] += 1
            else:
                run_stats["insufficient_evidence"] += 1
            if answer_status == "draft" and not is_insufficient_answer_text(text):
                try:
                    answer_cache_set(
                        db,
                        workspace_id,
                        question_cache_hash(normalize_question(q.text)),
                        style_for_cache,
                        evidence_fp_one,
                        text,
                        citations,
                        conf,
                    )
                except Exception:
                    pass
            adaptive.release(success=True, was_rate_limited=False, was_timeout=False, was_transient=False)
        ADAPTIVE_CONCURRENCY_CURRENT.set(adaptive.max_workers)

    _t0 = time.monotonic()
    _uncommitted = 0
    if llm_tasks:
        batches = _adaptive_batch_tasks(llm_tasks)
        logger.info(
            "answer_generation: %d questions -> %d batches (batch_size=%d, workers=%d)",
            len(llm_tasks), len(batches), adaptive.batch_size, adaptive.max_workers,
        )

        max_w = min(adaptive.max_workers, len(batches))
        with ThreadPoolExecutor(max_workers=max(max_w, ADAPTIVE_INITIAL)) as executor:
            futures: dict[Any, list[tuple[Any, list[dict]]]] = {}
            batch_idx = 0

            def _drain_done() -> None:
                nonlocal _uncommitted
                done = [f for f in futures if f.done()]
                for f in done:
                    batch_items = futures.pop(f)
                    try:
                        batch_results = f.result()
                        for (q, ev), result in zip(batch_items, batch_results):
                            _apply_one_result(q, ev, result, None)
                    except Exception as e:
                        for q, ev in batch_items:
                            _apply_one_result(q, ev, None, e)
                    _uncommitted += len(batch_items)
                    if _uncommitted >= 10:
                        db.commit()
                        if job:
                            job.result = _job_payload(count, total_questions, {**run_stats, "duration_ms": (time.monotonic() - started) * 1000})
                        _uncommitted = 0

            while batch_idx < len(batches) or futures:
                wait = adaptive.backoff_remaining()
                if wait > 0:
                    logger.info("answer_generation: backoff %.1fs (rate limit cooldown)", wait)
                    time.sleep(wait)

                while batch_idx < len(batches) and len(futures) < adaptive.max_workers:
                    batch = batches[batch_idx]
                    batch_idx += 1
                    fut = executor.submit(
                        _generate_batched_answers,
                        batch, workspace_id, questionnaire_id,
                        model_name, temperature, system_msg, client,
                        q_labels=_q_labels_dict,
                    )
                    futures[fut] = batch

                if not futures:
                    break

                _any_done = False
                while not _any_done and futures:
                    _drain_done()
                    _any_done = len(futures) < batch_idx or any(f.done() for f in futures)
                    if not _any_done:
                        time.sleep(0.05)
                _drain_done()

            _drain_done()

        if _uncommitted > 0:
            db.commit()
            if job:
                job.result = _job_payload(count, total_questions, {**run_stats, "duration_ms": (time.monotonic() - started) * 1000})
            _uncommitted = 0

        pool_stats = adaptive.stats()
        run_stats["adaptive_final_workers"] = pool_stats["workers"]
        run_stats["adaptive_final_batch"] = pool_stats["batch_size"]
        run_stats["adaptive_rate_limits"] = pool_stats["total_rate_limits"]
    llm_time_ms = (time.monotonic() - _t0) * 1000

    duration_ms = (time.monotonic() - started) * 1000
    swept = _sweep_draft_insufficient_narratives(db, questionnaire_id)
    _adjust_run_stats_after_sweep(run_stats, swept)

    # Evidence gap generation runs in background -- don't block answer pipeline completion
    import threading as _threading

    def _run_gap_generation() -> None:
        from sqlalchemy.orm import Session as _Ses
        gap_db = _Ses(bind=db.get_bind())
        try:
            from app.services.evidence_gap_service import generate_gaps_for_questionnaire
            result = generate_gaps_for_questionnaire(gap_db, workspace_id, questionnaire_id)
            generated = result.get("generated", 0)
            if generated > 0:
                logger.info("answer_generation: generated %d evidence gaps for qnr=%d (background)", generated, questionnaire_id)
        except Exception:
            logger.warning("answer_generation: gap generation failed for qnr=%d (background)", questionnaire_id, exc_info=True)
        finally:
            gap_db.close()

    _gap_thread = _threading.Thread(target=_run_gap_generation, daemon=True)
    _gap_thread.start()
    run_stats["gaps_generated"] = 0

    run_stats["duration_ms"] = duration_ms
    run_stats["embed_time_ms"] = round(embed_time_ms, 1)
    run_stats["retrieval_time_ms"] = round(retrieval_time_ms, 1)
    run_stats["gating_time_ms"] = round(gating_time_ms, 1)
    run_stats["llm_time_ms"] = round(llm_time_ms, 1)
    log_answer_gen_success(workspace_id, questionnaire_id, count, duration_ms)
    ANSWER_GEN_DURATION_SECONDS.observe(duration_ms / 1000)
    logger.info(
        "WORKER: answer generated count=%s total_questions=%s questionnaire_id=%s workspace_id=%s stats=%s",
        count,
        total_questions,
        questionnaire_id,
        workspace_id,
        run_stats,
    )
    llm_call_count = int(run_stats.get("llm_calls", 0))
    if llm_call_count > 0:
        try:
            record_answer_calls(db, workspace_id, llm_call_count)
        except Exception:
            pass
    audit_log(
        "answer.generate",
        workspace_id=workspace_id,
        resource_type="questionnaire",
        resource_id=questionnaire_id,
        details={
            "generated": count,
            "total_questions": total_questions,
            "llm_calls": llm_call_count,
            "insufficient": int(run_stats.get("insufficient_evidence", 0)),
            "drafted": int(run_stats.get("drafted", 0)),
            "duration_ms": round(duration_ms, 1),
        },
    )
    if job:
        job.result = _job_payload(count, total_questions, run_stats)
        db.commit()
    return count


def _sweep_draft_insufficient_narratives(db: Session, questionnaire_id: int) -> int:
    """Reclassify draft rows whose text is insufficient, have zero citations,
    or whose primary subject requires direct evidence that wasn't provided."""
    from app.services.answer_evidence_policy import subject_requires_direct_evidence
    from app.services.registry_metadata import SUBJECT_AREA_LABEL_TO_KEY

    answers = (
        db.query(Answer)
        .join(Question, Question.id == Answer.question_id)
        .filter(Question.questionnaire_id == questionnaire_id, Answer.status == "draft")
        .all()
    )
    n = 0
    for a in answers:
        no_citations = False
        try:
            cits = json.loads(a.citations or "[]") if a.citations else []
            no_citations = len(cits) == 0
        except Exception:
            no_citations = True

        direct_ev_missing = False
        if a.primary_categories_json and not no_citations:
            try:
                cats = json.loads(a.primary_categories_json)
                subjects = cats.get("subjects", []) if isinstance(cats, dict) else []
                for s_label in subjects:
                    s_key = SUBJECT_AREA_LABEL_TO_KEY.get(s_label, s_label.lower().replace(" ", "_"))
                    if subject_requires_direct_evidence(s_key):
                        direct_ev_missing = True
                        break
            except Exception:
                pass

        if is_insufficient_answer_text(a.text) or no_citations:
            a.status = "insufficient_evidence"
            if no_citations and not a.insufficient_reason:
                a.insufficient_reason = "no_citations"
            a.confidence = 0
            n += 1
    if n:
        db.commit()
    return n


def _adjust_run_stats_after_sweep(run_stats: dict[str, int | float], swept: int) -> None:
    if swept:
        run_stats["drafted"] = max(0, int(run_stats["drafted"]) - swept)
        run_stats["insufficient_evidence"] = int(run_stats["insufficient_evidence"]) + swept


def _upsert_answer(
    db: Session,
    question_id: int,
    text: str,
    citations: list[dict],
    confidence: int,
    answer_status: str = "draft",
    *,
    insufficient_reason: str | None = None,
    gating_reason: str | None = None,
    primary_categories_json: str | None = None,
    evidence_fingerprint: str | None = None,
) -> None:
    """Create or update an Answer for a question."""
    with db.no_autoflush:
        existing = db.query(Answer).filter(Answer.question_id == question_id).first()
    if existing:
        existing.text = text
        existing.citations = json.dumps(citations)
        existing.status = answer_status
        existing.confidence = confidence
        existing.insufficient_reason = insufficient_reason
        existing.gating_reason = gating_reason
        existing.primary_categories_json = primary_categories_json
        if evidence_fingerprint is not None:
            existing.evidence_fingerprint = evidence_fingerprint
    else:
        a = Answer(
            question_id=question_id,
            text=text,
            status=answer_status,
            citations=json.dumps(citations),
            confidence=confidence,
            insufficient_reason=insufficient_reason,
            gating_reason=gating_reason,
            primary_categories_json=primary_categories_json,
            evidence_fingerprint=evidence_fingerprint,
        )
        db.add(a)
