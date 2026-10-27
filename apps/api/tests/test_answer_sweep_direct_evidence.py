"""TC-02-BUG-005: the draft sweep applies the direct-evidence rule it documents.

``_sweep_draft_insufficient_narratives`` computed ``direct_ev_missing`` and never used it, so a draft in a subject
that requires direct evidence (e.g. "Privileged Access") stayed ``draft`` even when every citation came from an
export-like document (a previously filled questionnaire / vendor response), which is not direct evidence.

Synthetic rows only; every row is created per test and removed afterwards.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy.orm import Session

from app.models import Answer, Document, Question, Questionnaire
from app.services.answer_generation import _sweep_draft_insufficient_narratives

WS = 1
DIRECT_SUBJECT = "Privileged Access"  # direct_evidence_required=True in framework_metadata
ORDINARY_SUBJECT = "Access Control"  # direct_evidence_required=False


@pytest.fixture
def sweep_env(db_session: Session):
    tag = uuid.uuid4().hex[:12]
    export_like = Document(  # tier 3: filename marks it as a prior questionnaire response
        workspace_id=WS,
        storage_key=f"raw/{WS}/sweep-{tag}-a.xlsx",
        filename=f"Vendor Response {tag} filled.xlsx",
        status="indexed",
    )
    policy = Document(  # tier 2: an ordinary policy document
        workspace_id=WS,
        storage_key=f"raw/{WS}/sweep-{tag}-b.pdf",
        filename=f"privileged-access-policy-{tag}.pdf",
        status="indexed",
    )
    db_session.add_all([export_like, policy])
    db_session.flush()
    qnr = Questionnaire(workspace_id=WS, filename=f"sweep-{tag}.xlsx", status="parsed")
    db_session.add(qnr)
    db_session.commit()
    created_q: list[int] = []

    def add_draft(subject: str, cited_doc_ids: list[int | None]) -> int:
        q = Question(questionnaire_id=qnr.id, text=f"Synthetic question {len(created_q)} {tag}?")
        db_session.add(q)
        db_session.flush()
        created_q.append(q.id)
        cits = [
            {"chunk_id": None, "snippet": "Synthetic snippet.", "document_id": did}
            for did in cited_doc_ids
        ]
        db_session.add(
            Answer(
                question_id=q.id,
                text="Yes. Privileged accounts are reviewed quarterly (synthetic).",
                status="draft",
                confidence=80,
                citations=json.dumps(cits),
                primary_categories_json=json.dumps({"subjects": [subject]}),
            )
        )
        db_session.commit()
        return q.id

    def answer(qid: int) -> Answer:
        db_session.expire_all()
        return db_session.query(Answer).filter(Answer.question_id == qid).one()

    env = type(
        "SweepEnv",
        (),
        {
            "qnr_id": qnr.id,
            "export_like": export_like.id,
            "policy": policy.id,
            "add_draft": staticmethod(add_draft),
            "answer": staticmethod(answer),
        },
    )
    try:
        yield env
    finally:
        db_session.rollback()
        db_session.query(Questionnaire).filter(Questionnaire.id == qnr.id).delete(
            synchronize_session=False
        )  # questions + answers cascade
        db_session.query(Document).filter(Document.id.in_([export_like.id, policy.id])).delete(
            synchronize_session=False
        )
        db_session.commit()


def test_direct_subject_citing_only_export_like_docs_is_reclassified(db_session, sweep_env):
    qid = sweep_env.add_draft(DIRECT_SUBJECT, [sweep_env.export_like, sweep_env.export_like])
    assert _sweep_draft_insufficient_narratives(db_session, sweep_env.qnr_id) == 1
    a = sweep_env.answer(qid)
    assert a.status == "insufficient_evidence"
    assert a.insufficient_reason == "direct_evidence_required:privileged_access"
    assert a.confidence == 0
    # TC-11-001: same outcome as the pre-LLM direct-evidence gate, never left as grounded.
    assert a.outcome_code == "no_evidence"


def test_direct_subject_with_a_direct_citation_stays_draft(db_session, sweep_env):
    qid = sweep_env.add_draft(DIRECT_SUBJECT, [sweep_env.export_like, sweep_env.policy])
    assert _sweep_draft_insufficient_narratives(db_session, sweep_env.qnr_id) == 0
    a = sweep_env.answer(qid)
    assert a.status == "draft" and a.insufficient_reason is None and a.confidence == 80


def test_rule_only_applies_to_direct_evidence_subjects(db_session, sweep_env):
    qid = sweep_env.add_draft(ORDINARY_SUBJECT, [sweep_env.export_like])
    assert _sweep_draft_insufficient_narratives(db_session, sweep_env.qnr_id) == 0
    assert sweep_env.answer(qid).status == "draft"


def test_unresolvable_citations_are_not_over_flagged(db_session, sweep_env):
    # No document id / a deleted document: directness unknown, so the sweep does not reclassify (conservative).
    qid_none = sweep_env.add_draft(DIRECT_SUBJECT, [None])
    qid_gone = sweep_env.add_draft(DIRECT_SUBJECT, [99999999])
    assert _sweep_draft_insufficient_narratives(db_session, sweep_env.qnr_id) == 0
    assert sweep_env.answer(qid_none).status == "draft"
    assert sweep_env.answer(qid_gone).status == "draft"


def test_existing_rules_unchanged(db_session, sweep_env):
    qid = sweep_env.add_draft(DIRECT_SUBJECT, [])
    assert _sweep_draft_insufficient_narratives(db_session, sweep_env.qnr_id) == 1
    a = sweep_env.answer(qid)
    assert a.status == "insufficient_evidence" and a.insufficient_reason == "no_citations"
