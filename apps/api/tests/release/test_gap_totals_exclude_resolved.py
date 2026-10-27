"""TC-02-BUG-018: user- and buyer-facing gap totals exclude gaps closed by regeneration.

Regeneration closes a stale gap by setting the system-only status ``resolved``. Every service
that shows a gap count or gap list to users or buyers must leave those rows out and, where it
shows statuses, report them separately. Each test seeds one open, one accepted and one resolved
gap in a disposable synthetic workspace on the side PostgreSQL test database and fails on a
base that counts resolved rows as gaps. No network, no model calls, no real keys.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy.orm import Session

from app.models import Question, Questionnaire
from app.models.evidence_gap import EvidenceGap
from app.models.workspace import Workspace

RESOLVED_REASON = (
    "No workspace evidence supports an answer to this question. Reason code: no_citations.\n"
    "[resolved on regeneration: answer_sufficient at 2026-10-27T00:00:00Z]"
)


@contextmanager
def _seeded_workspace(db: Session) -> Iterator[tuple[int, int]]:
    """A synthetic workspace with a questionnaire and gaps: open, accepted, resolved, resolved."""
    tag = uuid.uuid4().hex[:8]
    ws = Workspace(name=f"TC-02-BUG-018 totals {tag}", slug=f"tc02bug018-{tag}")
    db.add(ws)
    db.flush()
    qnr = Questionnaire(workspace_id=ws.id, filename=f"bug018-{tag}.xlsx", status="parsed")
    db.add(qnr)
    db.flush()
    questions = [
        Question(questionnaire_id=qnr.id, text=f"Synthetic Zorblat control {i}?") for i in range(4)
    ]
    db.add_all(questions)
    db.flush()
    for question, status in zip(questions, ("open", "accepted", "resolved", "resolved")):
        db.add(
            EvidenceGap(
                workspace_id=ws.id,
                questionnaire_id=qnr.id,
                question_id=question.id,
                gap_type="missing_evidence",
                reason=RESOLVED_REASON if status == "resolved" else "Synthetic open gap.",
                status=status,
            )
        )
    db.commit()
    ws_id, qnr_id = ws.id, qnr.id
    try:
        yield ws_id, qnr_id
    finally:
        db.rollback()
        db.query(EvidenceGap).filter(EvidenceGap.workspace_id == ws_id).delete(
            synchronize_session=False
        )
        db.query(Question).filter(Question.questionnaire_id == qnr_id).delete(
            synchronize_session=False
        )
        db.query(Questionnaire).filter(Questionnaire.id == qnr_id).delete(synchronize_session=False)
        db.query(Workspace).filter(Workspace.id == ws_id).delete(synchronize_session=False)
        db.commit()


@pytest.fixture
def gap_ws(db_session: Session):
    with _seeded_workspace(db_session) as ids:
        yield ids


def test_export_pack_evidence_bundle_lists_resolved_separately(db_session: Session, gap_ws):
    from app.services.export_pack_service import generate_evidence_bundle

    ws_id, qnr_id = gap_ws
    bundle = generate_evidence_bundle(db_session, ws_id, qnr_id)
    assert sorted(g["status"] for g in bundle["evidence_gaps"]) == ["accepted", "open"]
    assert bundle["evidence_gaps_resolved"] == 2


def test_demo_proof_gap_metric_excludes_resolved(db_session: Session, gap_ws):
    from app.services import demo_proof_service

    ws_id, _qnr_id = gap_ws
    raw = demo_proof_service._collect_gaps(db_session, ws_id, (None, None))
    metric = raw["counts"]["evidence_gaps_stored"]
    assert metric["value"] == 2
    assert metric["numerator"] == 2
    assert metric["exclusions"]["resolved"] == 2
    assert metric["exclusions"]["foreign_reference"] == 0
    assert raw["failures"] == []


def test_benchmark_evidence_metrics_exclude_resolved(db_session: Session, gap_ws):
    from app.services import benchmark_service

    ws_id, _qnr_id = gap_ws
    metrics = benchmark_service.get_benchmarks(db_session, ws_id)["evidence_metrics"]
    assert metrics["evidence_gaps"] == 2
    assert metrics["evidence_gaps_resolved"] == 2


def test_executive_dashboard_gap_total_excludes_resolved(db_session: Session):
    """Platform-wide count, so the test compares before/after deltas around its own rows."""
    from app.services import executive_dashboard_service as eds

    before = eds.get_executive_dashboard(db_session)["content"]
    with _seeded_workspace(db_session):
        after = eds.get_executive_dashboard(db_session)["content"]
    assert after["evidence_gaps"] - before["evidence_gaps"] == 2
    assert after["evidence_gaps_resolved"] - before.get("evidence_gaps_resolved", 0) == 2


def test_gap_summary_total_excludes_resolved(db_session: Session, gap_ws):
    from app.services.evidence_gap_service import gap_summary

    ws_id, _qnr_id = gap_ws
    assert gap_summary(db_session, ws_id) == {
        "open": 1,
        "accepted": 1,
        "dismissed": 0,
        "resolved": 2,
        "total": 2,
    }
