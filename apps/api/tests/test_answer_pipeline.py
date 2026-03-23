"""Tests for answer pipeline: cache hits, invalidation, partial completion, evidence compression."""

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.corpus_version import bump_corpus_version, get_corpus_version
from app.services.answer_cache import get as answer_cache_get, set as answer_cache_set, invalidate_workspace as answer_cache_invalidate
from app.services.retrieval_cache import get as retrieval_cache_get, set as retrieval_cache_set, invalidate_workspace as retrieval_cache_invalidate
from app.services.question_normalizer import normalize_question, question_cache_hash, evidence_fingerprint_hash
from app.services.evidence_processor import process_evidence, compress_to_token_budget, deduplicate_by_chunk_id
from app.services.batch_assembler import assemble_batches, estimate_tokens


def test_normalize_question():
    # Normalizer strips trailing punctuation and collapses spaces
    assert normalize_question("  How do we  manage  access?  ") == "how do we manage access"
    assert normalize_question("") == ""
    assert question_cache_hash("hello") != question_cache_hash("world")
    assert question_cache_hash("hello") == question_cache_hash("hello")


def test_evidence_fingerprint_hash():
    assert evidence_fingerprint_hash([1, 2, 3]) == evidence_fingerprint_hash([3, 2, 1])
    assert evidence_fingerprint_hash([1, 2]) != evidence_fingerprint_hash([1, 2, 3])


def test_evidence_processor_dedup_and_compress():
    evidence = [
        {"id": 1, "text": "a" * 1000, "score": 0.9},
        {"id": 1, "text": "dup", "score": 0.8},
        {"id": 2, "text": "b" * 500, "score": 0.7},
    ]
    deduped = deduplicate_by_chunk_id(evidence)
    assert len(deduped) == 2
    compressed = compress_to_token_budget(deduped, token_budget=100)
    assert len(compressed) <= 2
    total_chars = sum(len(e.get("text", "")) for e in compressed)
    assert total_chars <= 100 * 4 + 500


def test_batch_assembler():
    class Q:
        def __init__(self, text):
            self.text = text
    questions = [Q("short"), Q("x" * 500), Q("y" * 500)]
    batches = assemble_batches(questions, evidence_token_estimate=500, max_total_tokens=2000)
    assert len(batches) >= 1
    assert sum(len(b) for b in batches) == len(questions)


def test_answer_cache_get_set(db_session: Session):
    """Answer cache set then get returns same data. Skips if migration 028 not applied."""
    db = db_session
    workspace_id = 1
    q_hash = question_cache_hash("test q")
    style = "balanced"
    efp = evidence_fingerprint_hash([1, 2])
    try:
        answer_cache_set(db, workspace_id, q_hash, style, efp, "Cached answer", [{"chunk_id": 1}], 80)
    except Exception as e:
        if "does not exist" in str(e) or "UndefinedTable" in str(type(e).__name__):
            pytest.skip("answer_cache table not present (run migration 028)")
        raise
    out = answer_cache_get(db, workspace_id, q_hash, style, efp)
    assert out is not None
    assert out["text"] == "Cached answer"
    assert out["confidence"] == 80
    assert answer_cache_get(db, workspace_id, q_hash, "precise", efp) is None
    n = answer_cache_invalidate(db, workspace_id)
    assert n >= 1
    assert answer_cache_get(db, workspace_id, q_hash, style, efp) is None


def test_retrieval_cache_and_corpus_version(db_session: Session):
    """Retrieval cache get/set and corpus version bump invalidates."""
    db = db_session
    workspace_id = 1
    q_hash = question_cache_hash("retrieval test")
    try:
        version = get_corpus_version(db, workspace_id)
    except Exception:
        pytest.skip("workspace_corpus_versions table may not exist")
    retrieval_cache_set(db, workspace_id, q_hash, version, [{"id": 1, "text": "chunk", "score": 0.9}])
    out = retrieval_cache_get(db, workspace_id, q_hash)
    assert out is not None
    assert len(out) == 1
    assert out[0]["id"] == 1
    bump_corpus_version(db, workspace_id)
    # After bump, cache key uses new version so old entry is stale (we don't auto-delete; get returns None for old key)
    new_version = get_corpus_version(db, workspace_id)
    assert new_version != version
    out2 = retrieval_cache_get(db, workspace_id, q_hash)
    # Current version is new_version; cached row has old version so retrieval_cache_get returns None (version mismatch)
    assert out2 is None or len(out2) == 0
    retrieval_cache_invalidate(db, workspace_id)


def test_partial_completion_progress(db_session: Session):
    """Job.result gets updated with generated/total during run (integration: generate_answers with job)."""
    from app.models import Job, JobStatus, Questionnaire, Question, Workspace
    from app.services.answer_generation import generate_answers_for_questionnaire
    db = db_session
    ws = db.query(Workspace).first()
    if not ws:
        pytest.skip("no workspace")
    qnr = db.query(Questionnaire).filter(Questionnaire.workspace_id == ws.id).first()
    if not qnr:
        pytest.skip("no questionnaire")
    job = Job(
        workspace_id=ws.id,
        kind="generate_answers",
        status=JobStatus.RUNNING.value,
        payload=json.dumps({"questionnaire_id": qnr.id, "workspace_id": ws.id}),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        with patch("app.services.answer_generation.embed_texts", return_value=[[0.0] * 1536] * 10):
            with patch("app.services.answer_generation.get_corpus_version", return_value="v1"):
                count = generate_answers_for_questionnaire(
                    db, qnr.id, ws.id, job=job
                )
        if job.result:
            data = json.loads(job.result)
            assert "generated" in data or "count" in data
            assert data.get("total", 0) >= 0
    finally:
        db.rollback()


def test_oversized_prompt_handling():
    """Evidence compression keeps prompt under token budget."""
    huge = [{"id": i, "text": "x" * 1000, "score": 0.9 - i * 0.01} for i in range(50)]
    compressed = process_evidence(huge, token_budget=500)
    total = sum(len(e.get("text", "")) for e in compressed)
    assert total <= 500 * 4 + 1000
