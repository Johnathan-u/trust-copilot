"""Phase 4 tests: adaptive concurrency (step down on 429, step up slowly, bounds, no oscillation, partial persistence)."""

import itertools
from unittest.mock import MagicMock, patch

import pytest

from app.core.adaptive_concurrency import (
    ADAPTIVE_INITIAL,
    ADAPTIVE_MAX_WORKERS,
    ADAPTIVE_MIN_WORKERS,
    AdaptivePool,
    SUCCESSES_BEFORE_STEP_UP,
)

FAKE_EMB = [0.1] * 1536
FAKE_EVIDENCE = [{"id": 1, "text": "Evidence.", "metadata": {}, "score": 0.8}]


def test_step_down_on_429():
    """On 429, concurrency steps down to min."""
    pool = AdaptivePool(initial=ADAPTIVE_INITIAL)
    assert pool.max_workers == ADAPTIVE_INITIAL
    pool.release(success=False, was_rate_limited=True, was_timeout=False, was_transient=False)
    assert pool.max_workers == ADAPTIVE_INITIAL - 1
    for _ in range(ADAPTIVE_INITIAL - ADAPTIVE_MIN_WORKERS - 1):
        pool.release(success=False, was_rate_limited=True, was_timeout=False, was_transient=False)
    assert pool.max_workers == ADAPTIVE_MIN_WORKERS


def test_step_down_on_timeout():
    """On timeout, concurrency steps down."""
    pool = AdaptivePool(initial=ADAPTIVE_INITIAL)
    pool.release(success=False, was_rate_limited=False, was_timeout=True, was_transient=False)
    assert pool.max_workers == ADAPTIVE_INITIAL - 1


def test_slow_step_up_after_successes():
    """Step up only after SUCCESSES_BEFORE_STEP_UP consecutive successes."""
    pool = AdaptivePool(initial=ADAPTIVE_MIN_WORKERS)
    for _ in range(SUCCESSES_BEFORE_STEP_UP - 1):
        pool.release(success=True, was_rate_limited=False, was_timeout=False, was_transient=False)
    assert pool.max_workers == ADAPTIVE_MIN_WORKERS
    pool.release(success=True, was_rate_limited=False, was_timeout=False, was_transient=False)
    assert pool.max_workers == ADAPTIVE_MIN_WORKERS + 1


def test_bounded_max():
    """Concurrency never exceeds max (6)."""
    pool = AdaptivePool(initial=ADAPTIVE_MAX_WORKERS)
    for _ in range(SUCCESSES_BEFORE_STEP_UP * 4):
        pool.release(success=True, was_rate_limited=False, was_timeout=False, was_transient=False)
    assert pool.max_workers == ADAPTIVE_MAX_WORKERS


def test_bounded_min():
    """Concurrency never goes below min (2)."""
    pool = AdaptivePool(initial=ADAPTIVE_MIN_WORKERS)
    for _ in range(10):
        pool.release(success=False, was_rate_limited=True, was_timeout=False, was_transient=False)
    assert pool.max_workers == ADAPTIVE_MIN_WORKERS


def test_no_oscillation_one_noisy_batch():
    """One failure in a string of successes: success counter resets; we don't thrash up/down."""
    pool = AdaptivePool(initial=3)
    for _ in range(SUCCESSES_BEFORE_STEP_UP):
        pool.release(success=True, was_rate_limited=False, was_timeout=False, was_transient=False)
    assert pool.max_workers == 4
    pool.release(success=False, was_rate_limited=True, was_timeout=False, was_transient=False)
    assert pool.max_workers == 3
    for _ in range(SUCCESSES_BEFORE_STEP_UP - 1):
        pool.release(success=True, was_rate_limited=False, was_timeout=False, was_transient=False)
    assert pool.max_workers == 3
    pool.release(success=True, was_rate_limited=False, was_timeout=False, was_transient=False)
    assert pool.max_workers == 4


def test_classify_exception_429():
    """classify_exception identifies 429."""
    class E429(Exception):
        status_code = 429
    pool = AdaptivePool(initial=3)
    rl, to, tr = pool.classify_exception(E429())
    assert rl is True and to is False and tr is False


def test_classify_exception_timeout():
    """classify_exception identifies timeout."""
    pool = AdaptivePool(initial=3)
    rl, to, tr = pool.classify_exception(TimeoutError("timed out"))
    assert rl is False and to is True and tr is False


def test_should_backoff_after_429():
    """should_backoff returns True shortly after a 429."""
    import time
    pool = AdaptivePool(initial=3)
    assert pool.should_backoff() is False
    pool.release(success=False, was_rate_limited=True, was_timeout=False, was_transient=False)
    assert pool.should_backoff() is True


def test_partial_persistence_with_adaptive_enabled():
    """With USE_ADAPTIVE_CONCURRENCY=True, partial persistence and progress remain correct (wave-based)."""
    import json
    from app.services.answer_generation import generate_answers_for_questionnaire
    qnr = MagicMock(id=1, workspace_id=1)
    questions = [MagicMock(id=i + 1, text=f"Q{i+1}?") for i in range(3)]
    ws = MagicMock(ai_completion_model=None, ai_temperature=None)
    aq = MagicMock()
    aq.filter.return_value.first.return_value = None
    db = MagicMock()
    db.query.side_effect = itertools.cycle(
        [MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=qnr)))),
         MagicMock(filter=MagicMock(return_value=MagicMock(all=MagicMock(return_value=questions)))),
         MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=ws))))]
        + [aq] * 20
    )
    db.commit = MagicMock()
    db.add = MagicMock()
    job = MagicMock()
    job.result = None
    with (
        patch("app.core.config.get_settings") as mock_settings,
        patch("app.services.answer_generation.embed_texts", return_value=[FAKE_EMB] * 3),
        patch("app.services.answer_generation.get_corpus_version", return_value=""),
        patch("app.services.answer_generation.retrieval_cache_get", return_value=None),
        patch("app.services.answer_generation.answer_cache_get", return_value=None),
        patch("app.services.answer_generation.RetrievalService") as MockRetrieval,
        patch("openai.OpenAI") as MockOpenAI,
    ):
        mock_settings.return_value.openai_api_key = "key"
        mock_settings.return_value.completion_model = "gpt-4o-mini"
        mock_settings.return_value.openai_temperature = 0.35
        mock_settings.return_value.use_adaptive_concurrency = True
        MockRetrieval.return_value.search.return_value = FAKE_EVIDENCE
        mock_r = MagicMock()
        mock_r.choices = [MagicMock()]
        mock_r.choices[0].message.content = "Answer 1: A.\n\nAnswer 2: B.\n\nAnswer 3: C."
        MockOpenAI.return_value.chat.completions.create.return_value = mock_r
        count = generate_answers_for_questionnaire(db, 1, 1, job=job)
    assert count == 3
    data = json.loads(job.result)
    assert data["generated"] == 3 and data["total"] == 3
