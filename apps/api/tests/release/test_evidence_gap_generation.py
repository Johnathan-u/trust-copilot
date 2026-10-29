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
    assert first == {"generated": 1, "total_insufficient": 1, "resolved": 0}
    (gap,) = _gaps(db, qnr.id)
    assert gap.question_id == q1.id
    assert gap.suggested_evidence_doc_title == "Access Control Policy"
    assert "no_citations" in gap.reason

    gap.status = "dismissed"
    db.commit()
    again = generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    assert again == {"generated": 0, "total_insufficient": 1, "resolved": 0}
    assert [g.status for g in _gaps(db, qnr.id)] == ["dismissed"]

    # Workspace scoping: another workspace id never sees this questionnaire.
    assert generate_gaps_for_questionnaire(db, 987654321, qnr.id) == {
        "generated": 0,
        "total_insufficient": 0,
        "resolved": 0,
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
    assert result == {"generated": 1, "total_insufficient": 1, "resolved": 0}
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


# ---------------------------------------------------------------------------------------------
# TC-02-BUG-018: regeneration closes stale open gaps (status "resolved"), never deletes them.
# Each test below fails on ce4d861, where a stale open gap stays open forever.
# ---------------------------------------------------------------------------------------------


def _insufficient(question_id: int, **kw) -> Answer:
    fields = {
        "text": "Insufficient evidence.",
        "status": "insufficient_evidence",
        "outcome_code": "no_evidence",
        "insufficient_reason": "no_citations",
    }
    fields.update(kw)
    return Answer(question_id=question_id, **fields)


def _set_answer(db: Session, question_id: int, **fields) -> None:
    db.query(Answer).filter(Answer.question_id == question_id).update(
        fields, synchronize_session=False
    )
    db.commit()


_SUFFICIENT = {
    "text": "Synthetic grounded draft.",
    "status": "draft",
    "outcome_code": None,
    "insufficient_reason": None,
}
_INSUFFICIENT = {
    "text": "Insufficient evidence.",
    "status": "insufficient_evidence",
    "outcome_code": "no_evidence",
    "insufficient_reason": "no_citations",
}


def test_regeneration_resolves_gap_when_answer_becomes_sufficient(db_session: Session, qnr):
    from app.services.evidence_gap_service import generate_gaps_for_questionnaire

    db = db_session
    q1, q2, _q3 = _questions(db, qnr.id)
    db.add_all([_insufficient(q1.id), _insufficient(q2.id)])
    db.commit()
    assert generate_gaps_for_questionnaire(db, WS_ID, qnr.id)["generated"] == 2
    (gap1, gap2) = _gaps(db, qnr.id)
    gap1_id, opened_at, opened_reason = gap1.id, gap1.updated_at, gap1.reason
    assert "no_citations" in opened_reason

    _set_answer(db, q1.id, **_SUFFICIENT)  # new evidence -> grounded draft
    result = generate_gaps_for_questionnaire(db, WS_ID, qnr.id)

    gaps = {g.id: g for g in _gaps(db, qnr.id)}
    assert len(gaps) == 2  # closed, not deleted
    closed = gaps[gap1_id]
    assert closed.status == "resolved"
    assert closed.question_id == q1.id
    # Original reason kept byte for byte. Closure is the columns, not a note on reason.
    assert closed.reason == opened_reason
    assert closed.close_reason == "answer_sufficient"
    assert closed.closed_at is not None
    closed_at = closed.closed_at
    assert closed.updated_at is not None and closed.updated_at >= opened_at
    assert gaps[gap2.id].status == "open"
    assert gaps[gap2.id].close_reason is None and gaps[gap2.id].closed_at is None
    assert result == {"generated": 0, "total_insufficient": 1, "resolved": 1}

    # Rerun is a no-op; the closure columns are not rewritten.
    again = generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    assert again == {"generated": 0, "total_insufficient": 1, "resolved": 0}
    rerun = _gaps(db, qnr.id)[0]
    assert rerun.reason == opened_reason
    assert rerun.close_reason == "answer_sufficient"
    assert rerun.closed_at == closed_at

    # Insufficient again -> one new open gap; the resolved row stays as history.
    _set_answer(db, q1.id, **_INSUFFICIENT)
    reopened = generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    assert reopened == {"generated": 1, "total_insufficient": 2, "resolved": 0}
    q1_gaps = sorted((g for g in _gaps(db, qnr.id) if g.question_id == q1.id), key=lambda g: g.id)
    assert [g.status for g in q1_gaps] == ["resolved", "open"]
    assert q1_gaps[0].id == gap1_id
    assert q1_gaps[0].reason == opened_reason
    assert q1_gaps[0].close_reason == "answer_sufficient"
    assert q1_gaps[0].closed_at == closed_at
    assert q1_gaps[1].closed_at is None and q1_gaps[1].close_reason is None


def test_regeneration_resolves_gap_when_question_is_removed(db_session: Session, qnr):
    from app.services.evidence_gap_service import generate_gaps_for_questionnaire

    db = db_session
    q1, q2, _q3 = _questions(db, qnr.id)
    db.add_all([_insufficient(q1.id), _insufficient(q2.id)])
    db.commit()
    generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    gap2 = next(g for g in _gaps(db, qnr.id) if g.question_id == q2.id)
    gap2_id, gap2_reason = gap2.id, gap2.reason

    # The question is removed from the questionnaire (FKs on the gap are ON DELETE SET NULL).
    db.query(Answer).filter(Answer.question_id == q2.id).delete(synchronize_session=False)
    db.query(Question).filter(Question.id == q2.id).delete(synchronize_session=False)
    db.commit()

    result = generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    gaps = {g.id: g for g in _gaps(db, qnr.id)}
    assert len(gaps) == 2
    removed = gaps[gap2_id]
    assert removed.question_id is None
    assert removed.status == "resolved"
    assert removed.reason == gap2_reason
    assert removed.close_reason == "question_removed"
    assert removed.closed_at is not None
    assert removed.reason.splitlines()[0].startswith("No workspace evidence supports")
    assert [g.status for g in gaps.values() if g.question_id == q1.id] == ["open"]
    assert result == {"generated": 0, "total_insufficient": 1, "resolved": 1}


def test_regeneration_preserves_manually_accepted_and_dismissed_gaps(db_session: Session, qnr):
    from app.services.evidence_gap_service import generate_gaps_for_questionnaire

    db = db_session
    q1, q2, q3 = _questions(db, qnr.id)
    db.add_all([_insufficient(q.id) for q in (q1, q2, q3)])
    db.commit()
    generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    by_q = {g.question_id: g for g in _gaps(db, qnr.id)}
    by_q[q1.id].status = "accepted"
    by_q[q2.id].status = "dismissed"
    db.commit()
    manual = {
        g.question_id: (g.status, g.reason, g.updated_at, g.closed_at, g.close_reason)
        for g in _gaps(db, qnr.id)
        if g.question_id in (q1.id, q2.id)
    }

    for q in (q1, q2, q3):
        _set_answer(db, q.id, **_SUFFICIENT)
    result = generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    after = {g.question_id: g for g in _gaps(db, qnr.id)}
    assert after[q3.id].status == "resolved"
    assert after[q3.id].close_reason == "answer_sufficient"
    assert after[q3.id].closed_at is not None
    for qid, (status, reason, updated_at, closed_at, close_reason) in manual.items():
        assert (
            after[qid].status,
            after[qid].reason,
            after[qid].updated_at,
            after[qid].closed_at,
            after[qid].close_reason,
        ) == (status, reason, updated_at, closed_at, close_reason)
    assert result == {"generated": 0, "total_insufficient": 0, "resolved": 1}

    # User decisions still block a duplicate when the answers turn insufficient again.
    for q in (q1, q2):
        _set_answer(db, q.id, **_INSUFFICIENT)
    again = generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    assert again == {"generated": 0, "total_insufficient": 2, "resolved": 0}
    assert sorted(g.status for g in _gaps(db, qnr.id)) == ["accepted", "dismissed", "resolved"]


def test_regeneration_leaves_llm_error_placeholders_untouched(db_session: Session, qnr):
    from app.services.evidence_gap_service import generate_gaps_for_questionnaire

    db = db_session
    q1, q2, q3 = _questions(db, qnr.id)
    db.add_all([_insufficient(q1.id), _insufficient(q3.id)])
    db.commit()
    generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    before = {
        g.question_id: (g.id, g.status, g.reason, g.updated_at, g.closed_at, g.close_reason)
        for g in _gaps(db, qnr.id)
    }

    # q1's rerun hit a provider failure: TC-10-002 placeholder. q2 only has a placeholder.
    # q3 got evidence, so its gap closes (the part that fails on ce4d861).
    _set_answer(db, q1.id, outcome_code="model_timeout", insufficient_reason="llm_error")
    db.add(_insufficient(q2.id, outcome_code="model_timeout", insufficient_reason="llm_error"))
    db.commit()
    _set_answer(db, q3.id, **_SUFFICIENT)

    result = generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    after = {g.question_id: g for g in _gaps(db, qnr.id)}
    assert set(after) == {q1.id, q3.id}  # no gap opened for the q2 placeholder
    g1 = after[q1.id]
    assert (
        g1.id,
        g1.status,
        g1.reason,
        g1.updated_at,
        g1.closed_at,
        g1.close_reason,
    ) == before[q1.id]  # not closed
    assert after[q3.id].status == "resolved"
    assert after[q3.id].close_reason == "answer_sufficient"
    assert after[q3.id].closed_at is not None
    assert after[q3.id].reason == before[q3.id][2]
    assert result == {"generated": 0, "total_insufficient": 0, "resolved": 1}


def test_concurrent_regeneration_resolves_once_and_keeps_one_open_gap(db_session: Session, qnr):
    """Overlapping regenerations: stale gap closed once, one open gap per insufficient question."""
    from sqlalchemy.orm import Session as SASession

    from app.core.database import SessionLocal
    from app.services.evidence_gap_service import generate_gaps_for_questionnaire

    db = db_session
    qnr_id = qnr.id
    q1, q2, q3 = _questions(db, qnr_id)
    db.add_all([_insufficient(q1.id), _insufficient(q2.id), _insufficient(q3.id)])
    db.commit()
    _set_answer(db, q1.id, **_SUFFICIENT)

    original_commit = SASession.commit

    def _commit_after_pause(self):
        time.sleep(0.2)
        return original_commit(self)

    for trial in range(4):
        db.query(EvidenceGap).filter(EvidenceGap.questionnaire_id == qnr_id).delete(
            synchronize_session=False
        )
        # Stale state from an earlier run: q1 and q2 open, q3 resolved by an earlier run.
        for question, status in ((q1, "open"), (q2, "open"), (q3, "resolved")):
            db.add(
                EvidenceGap(
                    workspace_id=WS_ID,
                    questionnaire_id=qnr_id,
                    question_id=question.id,
                    gap_type="missing_evidence",
                    reason="Synthetic earlier gap.",
                    status=status,
                )
            )
        db.commit()
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []
        results: list[dict] = []

        def _run() -> None:
            session = SessionLocal()
            try:
                barrier.wait(timeout=5)
                results.append(generate_gaps_for_questionnaire(session, WS_ID, qnr_id))
            except BaseException as exc:  # reported below; a leaked thread must not hide it
                errors.append(exc)
            finally:
                session.close()

        with patch.object(SASession, "commit", _commit_after_pause):
            threads = [
                threading.Thread(target=_run, name=f"gap-regen-{trial}-{i}") for i in range(2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
        assert errors == []
        assert not any(thread.is_alive() for thread in threads)

        gaps = _gaps(db, qnr_id)
        open_qids = sorted(g.question_id for g in gaps if g.status == "open")
        assert open_qids == [q2.id, q3.id], f"trial {trial}: open gaps for {open_qids}"
        (q1_gap,) = [g for g in gaps if g.question_id == q1.id]
        assert q1_gap.status == "resolved"
        assert q1_gap.close_reason == "answer_sufficient"
        assert q1_gap.closed_at is not None
        assert q1_gap.reason == "Synthetic earlier gap."
        assert sorted(g.status for g in gaps if g.question_id == q3.id) == ["open", "resolved"]
        assert sum(r["resolved"] for r in results) == 1
        assert sum(r["generated"] for r in results) == 1


@pytest.mark.parametrize("judged_status", ["rejected", "flagged"])
def test_regeneration_keeps_gap_open_when_answer_is_rejected_or_flagged(
    db_session: Session, qnr, judged_status: str
):
    """A rejected or flagged answer is not sufficient: its gap stays open (ruling 3).

    q2 shows the same rerun still closes a gap whose answer is a plain draft, so the test fails
    on a base without the close-on-regeneration fix and on one that treats rejected/flagged as
    sufficient.
    """
    from app.services.evidence_gap_service import generate_gaps_for_questionnaire

    db = db_session
    q1, q2, _q3 = _questions(db, qnr.id)
    db.add_all([_insufficient(q1.id), _insufficient(q2.id)])
    db.commit()
    generate_gaps_for_questionnaire(db, WS_ID, qnr.id)
    before = {
        g.question_id: (g.id, g.reason, g.updated_at, g.closed_at, g.close_reason)
        for g in _gaps(db, qnr.id)
    }

    # A reviewer (or the system) judged q1's new answer not good enough; q2 got a grounded draft.
    _set_answer(db, q1.id, **{**_SUFFICIENT, "status": judged_status})
    _set_answer(db, q2.id, **_SUFFICIENT)
    result = generate_gaps_for_questionnaire(db, WS_ID, qnr.id)

    after = {g.question_id: g for g in _gaps(db, qnr.id)}
    g1 = after[q1.id]
    assert g1.status == "open"
    assert (g1.id, g1.reason, g1.updated_at, g1.closed_at, g1.close_reason) == before[q1.id]
    assert after[q2.id].status == "resolved"
    assert after[q2.id].close_reason == "answer_sufficient"
    assert after[q2.id].closed_at is not None
    assert after[q2.id].reason == before[q2.id][1]
    assert result == {"generated": 0, "total_insufficient": 0, "resolved": 1}

    # A second answer row that is sufficient does not outvote the rejected/flagged one.
    db.add(Answer(question_id=q1.id, **_SUFFICIENT))
    db.commit()
    assert generate_gaps_for_questionnaire(db, WS_ID, qnr.id)["resolved"] == 0
    assert _gaps(db, qnr.id)[0].status == "open"


def test_resolution_note_format_is_delimited_and_keeps_reason():
    """Grammar of the historical note. New closures do not append it; the migration parses it."""
    from datetime import datetime, timedelta, timezone

    from app.services.evidence_gap_service import append_resolution_note

    at = datetime(2026, 10, 27, 9, 30, 15, 123456, tzinfo=timezone(timedelta(hours=-5)))
    assert append_resolution_note("Original\nreason.", "question_removed", at) == (
        "Original\nreason.\n[resolved on regeneration: question_removed at 2026-10-27T14:30:15Z]"
    )
    assert append_resolution_note(None, "answer_sufficient", at) == (
        "[resolved on regeneration: answer_sufficient at 2026-10-27T14:30:15Z]"
    )
