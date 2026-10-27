"""TC-02-BUG-015: evidence gaps are really generated after answer generation.

Before the fix, answer generation imported a ``generate_gaps_for_questionnaire`` that did
not exist and a broad ``except`` swallowed the ImportError, so no gap was ever written.
These tests run on the side PostgreSQL test database with synthetic rows only. Retrieval,
embeddings and the OpenAI client are fakes; no network and no real key are used.

Imports of the code under test stay inside the tests so the file still collects on a base
without the fix and each assertion fails on its own.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models import Answer, Job, JobStatus, Question, Questionnaire
from app.models.evidence_gap import EvidenceGap
from app.models.question_mapping_signal import QuestionMappingSignal

WS_ID = 1
CANARY = "ZZ-GAP-CANARY-TC02BUG015-SHOULD-NOT-LEAK"


@pytest.fixture
def qnr(db_session: Session):
    """A synthetic questionnaire in workspace 1 with three questions; removed afterwards."""
    q = Questionnaire(
        workspace_id=WS_ID, filename=f"bug015-{uuid.uuid4().hex[:8]}.xlsx", status="parsed"
    )
    db_session.add(q)
    db_session.flush()
    for text in (
        "Describe the synthetic access review cadence for Zorblat systems.",
        "Describe the synthetic key rotation schedule for Zorblat vaults.",
        "Describe the synthetic tabletop exercise program for Zorblat.",
    ):
        db_session.add(Question(questionnaire_id=q.id, text=text))
    db_session.commit()
    db_session.refresh(q)
    try:
        yield q
    finally:
        db_session.rollback()
        qids = [r.id for r in db_session.query(Question.id).filter_by(questionnaire_id=q.id)]
        db_session.query(EvidenceGap).filter(EvidenceGap.questionnaire_id == q.id).delete(
            synchronize_session=False
        )
        if qids:
            db_session.query(QuestionMappingSignal).filter(
                QuestionMappingSignal.question_id.in_(qids)
            ).delete(synchronize_session=False)
            db_session.query(Answer).filter(Answer.question_id.in_(qids)).delete(
                synchronize_session=False
            )
        db_session.query(Job).filter(Job.payload.contains(f'"questionnaire_id": {q.id},')).delete(
            synchronize_session=False
        )
        db_session.query(Question).filter(Question.questionnaire_id == q.id).delete(
            synchronize_session=False
        )
        db_session.query(Questionnaire).filter(Questionnaire.id == q.id).delete(
            synchronize_session=False
        )
        db_session.commit()


def _questions(db: Session, qnr_id: int) -> list[Question]:
    return db.query(Question).filter_by(questionnaire_id=qnr_id).order_by(Question.id).all()


def _gaps(db: Session, qnr_id: int) -> list[EvidenceGap]:
    db.expire_all()
    return (
        db.query(EvidenceGap)
        .filter(EvidenceGap.questionnaire_id == qnr_id)
        .order_by(EvidenceGap.question_id)
        .all()
    )


def _job(db: Session, qnr_id: int) -> Job:
    job = Job(
        workspace_id=WS_ID,
        kind="generate_answers",
        status=JobStatus.RUNNING.value,
        payload=json.dumps({"questionnaire_id": qnr_id, "workspace_id": WS_ID}),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _generate_without_evidence(db: Session, qnr_id: int, job: Job | None = None) -> MagicMock:
    """Run the real pipeline with fake embeddings and empty retrieval (no model call)."""
    from app.services import answer_generation as ag
    from app.services.retrieval import RetrievalService

    client = MagicMock()
    with (
        patch.object(
            ag, "embed_texts", side_effect=lambda texts, **_k: [[0.0] * 1536] * len(texts)
        ),
        patch.object(ag, "get_corpus_version", return_value="bug015"),
        patch.object(ag, "answer_cache_get", return_value=None),
        patch.object(ag, "retrieval_cache_get", return_value=None),
        patch.object(RetrievalService, "_semantic_search", return_value=[]),
        patch.object(RetrievalService, "_keyword_search", return_value=[]),
        patch("openai.OpenAI", return_value=client),
    ):
        ag.generate_answers_for_questionnaire(db, qnr_id, WS_ID, job=job)
    return client


def test_answer_generation_binds_the_real_gap_generator():
    """The generator exists and answer_generation imports it at module load (no lazy import)."""
    from app.services import answer_generation as ag
    from app.services import evidence_gap_service

    assert callable(getattr(evidence_gap_service, "generate_gaps_for_questionnaire", None))
    assert (
        ag.generate_gaps_for_questionnaire is evidence_gap_service.generate_gaps_for_questionnaire
    )


def test_generation_writes_one_open_gap_per_insufficient_answer(
    db_session: Session, qnr, synthetic_openai_key
):
    db = db_session
    job = _job(db, qnr.id)
    client = _generate_without_evidence(db, qnr.id, job=job)
    assert not client.chat.completions.create.called  # no evidence -> no paid call

    questions = _questions(db, qnr.id)
    answers = {
        a.question_id: a
        for a in db.query(Answer).filter(Answer.question_id.in_([q.id for q in questions]))
    }
    assert {a.status for a in answers.values()} == {"insufficient_evidence"}

    gaps = _gaps(db, qnr.id)
    assert [g.question_id for g in gaps] == [q.id for q in questions]
    for gap in gaps:
        assert gap.workspace_id == WS_ID
        assert gap.status == "open"
        assert gap.gap_type == "missing_evidence"
        assert gap.answer_id == answers[gap.question_id].id
        assert gap.reason and "Zorblat" not in gap.reason  # no question/answer text copied
        assert gap.proposed_policy_addition is None  # nothing model-written is invented

    db.refresh(job)
    stats = json.loads(job.result)["stats"]
    assert stats["gaps_generated"] == len(questions)
    assert "gap_generation" not in stats
    assert job.error_code is None and job.error is None

    # A rerun does not duplicate gaps.
    _generate_without_evidence(db, qnr.id)
    assert len(_gaps(db, qnr.id)) == len(questions)


def test_generator_skips_model_failures_and_existing_gaps(db_session: Session, qnr):
    from app.services.evidence_gap_service import generate_gaps_for_questionnaire

    db = db_session
    q1, q2, q3 = _questions(db, qnr.id)
    db.add_all(
        [
            Answer(
                question_id=q1.id,
                text="Insufficient evidence.",
                status="insufficient_evidence",
                outcome_code="no_evidence",
                insufficient_reason="no_citations",
                primary_categories_json=json.dumps({"subjects": ["Access Control"]}),
            ),
            # A provider failure is retried as a generation failure, not reported as a gap.
            Answer(
                question_id=q2.id,
                text="Insufficient evidence.",
                status="insufficient_evidence",
                outcome_code="model_timeout",
                insufficient_reason="llm_error",
            ),
            Answer(question_id=q3.id, text="Synthetic grounded draft.", status="draft"),
        ]
    )
    db.commit()

    first = generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    assert first == {"generated": 1, "total_insufficient": 1}
    (gap,) = _gaps(db, qnr.id)
    assert gap.question_id == q1.id
    assert gap.suggested_evidence_doc_title == "Access Control Policy"
    assert "no_citations" in gap.reason

    gap.status = "dismissed"
    db.commit()
    again = generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    assert again == {"generated": 0, "total_insufficient": 1}
    assert [g.status for g in _gaps(db, qnr.id)] == ["dismissed"]

    # Workspace scoping: another workspace id never sees this questionnaire.
    assert generate_gaps_for_questionnaire(db, 987654321, qnr.id) == {
        "generated": 0,
        "total_insufficient": 0,
    }


@pytest.mark.parametrize(
    "exc",
    [
        ImportError(f"cannot import name 'generate_gaps_for_questionnaire' {CANARY}"),
        RuntimeError(f"synthetic gap failure {CANARY}"),
    ],
    ids=["import_error", "runtime_error"],
)
def test_gap_failure_is_not_swallowed_under_tests(
    db_session: Session, qnr, synthetic_openai_key, exc
):
    from app.services import answer_generation as ag

    with patch.object(ag, "generate_gaps_for_questionnaire", side_effect=exc):
        with pytest.raises(type(exc)):
            _generate_without_evidence(db_session, qnr.id)


def test_gap_failure_marks_job_with_safe_code_in_production(
    db_session: Session, qnr, synthetic_openai_key, monkeypatch, caplog
):
    from app.services import answer_generation as ag

    db = db_session
    job = _job(db, qnr.id)
    monkeypatch.setattr(ag, "_gap_failures_raise", lambda: False)
    boom = ImportError(f"cannot import name 'generate_gaps_for_questionnaire' {CANARY}")
    with (
        caplog.at_level(logging.ERROR, logger=ag.logger.name),
        patch.object(ag, "generate_gaps_for_questionnaire", side_effect=boom),
    ):
        _generate_without_evidence(db, qnr.id, job=job)

    db.refresh(job)
    assert job.error_code == "evidence_gaps_failed"
    assert job.error == ag.GAP_GENERATION_FAILED_MESSAGE
    assert CANARY not in (job.error or "") and CANARY not in (job.result or "")
    stats = json.loads(job.result)["stats"]
    assert stats["gap_generation"] == "failed"
    assert stats["gap_generation_error_code"] == "evidence_gaps_failed"
    assert stats["gaps_generated"] == 0
    # Answers are kept; the failure is logged at ERROR with the exception for operators.
    assert (
        db.query(Answer)
        .filter(Answer.question_id.in_([q.id for q in _questions(db, qnr.id)]))
        .count()
        == 3
    )
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("evidence_gaps_failed" in r.getMessage() and r.exc_info for r in errors)


def test_generator_skips_llm_error_placeholders(db_session: Session, qnr):
    """TC-10-002 leaves insufficient_reason=llm_error rows for the retry. Those are not gaps."""
    from app.services.evidence_gap_service import generate_gaps_for_questionnaire

    db = db_session
    q1, q2, q3 = _questions(db, qnr.id)
    db.add_all(
        [
            Answer(
                question_id=q1.id,
                text="Insufficient evidence.",
                status="insufficient_evidence",
                outcome_code="no_evidence",
                insufficient_reason="llm_error",
            ),
            Answer(
                question_id=q2.id,
                text="Insufficient evidence.",
                status="insufficient_evidence",
                outcome_code=None,
                insufficient_reason="llm_error",
            ),
            Answer(
                question_id=q3.id,
                text="Insufficient evidence.",
                status="insufficient_evidence",
                outcome_code="no_evidence",
                insufficient_reason="no_citations",
            ),
        ]
    )
    db.commit()

    result = generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    assert result == {"generated": 1, "total_insufficient": 1}
    (gap,) = _gaps(db, qnr.id)
    assert gap.question_id == q3.id


def test_concurrent_generators_insert_one_gap_per_question(db_session: Session, qnr):
    """Two overlapping runs must not duplicate gaps. Without the advisory lock this fails.

    Each trial starts both calls together and pauses inside commit so the second call reaches
    the existing-gap read before the first commit. The lock makes the second call wait.
    """
    from sqlalchemy.orm import Session as SASession

    from app.core.database import SessionLocal
    from app.services.evidence_gap_service import generate_gaps_for_questionnaire

    db = db_session
    qnr_id = qnr.id
    questions = _questions(db, qnr_id)
    for question in questions:
        db.add(
            Answer(
                question_id=question.id,
                text="Insufficient evidence.",
                status="insufficient_evidence",
                outcome_code="no_evidence",
                insufficient_reason="no_citations",
            )
        )
    db.commit()

    original_commit = SASession.commit

    def _commit_after_pause(self):
        time.sleep(0.2)
        return original_commit(self)

    for trial in range(4):
        db.query(EvidenceGap).filter(EvidenceGap.questionnaire_id == qnr_id).delete(
            synchronize_session=False
        )
        db.commit()
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def _run() -> None:
            session = SessionLocal()
            try:
                barrier.wait(timeout=5)
                generate_gaps_for_questionnaire(session, WS_ID, qnr_id)
            except BaseException as exc:  # reported below; a leaked thread must not hide it
                errors.append(exc)
            finally:
                session.close()

        with patch.object(SASession, "commit", _commit_after_pause):
            threads = [threading.Thread(target=_run, name=f"gap-gen-{trial}-{i}") for i in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
        assert errors == []
        assert not any(thread.is_alive() for thread in threads)
        gaps = _gaps(db, qnr_id)
        assert [g.question_id for g in gaps] == [
            q.id for q in questions
        ], f"trial {trial} wrote {len(gaps)} gaps for {len(questions)} questions"
