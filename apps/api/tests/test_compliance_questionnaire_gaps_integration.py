"""Questionnaire-driven evidence gaps on GET /api/compliance/gaps (approved/manual mappings, zero ControlEvidenceLink)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ControlEvidenceLink, Document, EvidenceItem, WorkspaceControl
from app.models.ai_mapping import QuestionMappingPreference
from app.models.questionnaire import Question, Questionnaire


def _login_reviewer(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"email": "reviewer@trust.local", "password": "r"})
    assert r.status_code == 200


def _get_gaps_payload(client: TestClient) -> dict:
    r = client.get("/api/compliance/gaps")
    assert r.status_code == 200
    return r.json()


@pytest.fixture
def qnr_two_questions(db_session: Session):
    """Questionnaire with two questions; cleaned up after."""
    qnr = Questionnaire(
        workspace_id=1,
        filename="gap-qnr.xlsx",
        status="parsed",
        display_id="QNR-GAP-TEST",
    )
    db_session.add(qnr)
    db_session.commit()
    db_session.refresh(qnr)
    texts = ["First question about access?", "Second question also maps to same control?"]
    qs = []
    for t in texts:
        q = Question(questionnaire_id=qnr.id, text=t, section="S", answer_type="text")
        db_session.add(q)
        qs.append(q)
    db_session.commit()
    for q in qs:
        db_session.refresh(q)
    try:
        yield qnr, qs
    finally:
        db_session.query(QuestionMappingPreference).filter(
            QuestionMappingPreference.questionnaire_id == qnr.id,
        ).delete(synchronize_session=False)
        db_session.query(Question).filter(Question.questionnaire_id == qnr.id).delete(
            synchronize_session=False
        )
        db_session.query(Questionnaire).filter(Questionnaire.id == qnr.id).delete(
            synchronize_session=False
        )
        db_session.commit()


def test_global_gaps_response_shape_unchanged(client: TestClient, db_session: Session):
    """Aggregate response includes legacy global list with expected keys."""
    _login_reviewer(client)
    data = _get_gaps_payload(client)
    assert isinstance(data["gaps"], list)
    for g in data["gaps"]:
        assert set(g.keys()) >= {
            "control_id",
            "control_key",
            "name",
            "framework",
            "evidence_count",
            "max_confidence",
            "gap_reason",
        }


def test_approved_mapping_no_evidence_surfaces_questionnaire_gap(
    client: TestClient,
    db_session: Session,
    qnr_two_questions: tuple,
):
    qnr, qs = qnr_two_questions
    wc = WorkspaceControl(
        workspace_id=1,
        framework_control_id=None,
        custom_name="Gap control WC",
    )
    db_session.add(wc)
    db_session.commit()
    db_session.refresh(wc)
    cid = wc.id

    m = QuestionMappingPreference(
        workspace_id=1,
        questionnaire_id=qnr.id,
        question_id=qs[0].id,
        normalized_question_text=(qs[0].text or "")[:2000],
        preferred_control_id=cid,
        source="manual",
        status="approved",
        approved=True,
    )
    db_session.add(m)
    db_session.commit()

    _login_reviewer(client)
    data = _get_gaps_payload(client)
    qgaps = data["questionnaire_evidence_gaps"]
    assert len(qgaps) >= 1
    hit = next((x for x in qgaps if x["control_id"] == cid), None)
    assert hit is not None
    assert hit["gap_kind"] == "questionnaire_mapping_no_evidence"
    assert hit["evidence_link_count"] == 0
    assert len(hit["questionnaire_refs"]) == 1
    ref = hit["questionnaire_refs"][0]
    assert ref["questionnaire_id"] == qnr.id
    assert ref["question_id"] == qs[0].id
    assert "access" in ref["question_text_preview"].lower()


def test_approved_mapping_with_evidence_no_questionnaire_gap(
    client: TestClient,
    db_session: Session,
    qnr_two_questions: tuple,
):
    qnr, qs = qnr_two_questions
    wc = WorkspaceControl(
        workspace_id=1,
        framework_control_id=None,
        custom_name="Has evidence WC",
    )
    db_session.add(wc)
    db_session.commit()
    db_session.refresh(wc)
    cid = wc.id

    m = QuestionMappingPreference(
        workspace_id=1,
        questionnaire_id=qnr.id,
        question_id=qs[0].id,
        normalized_question_text=(qs[0].text or "")[:2000],
        preferred_control_id=cid,
        source="manual",
        status="approved",
        approved=True,
    )
    db_session.add(m)
    db_session.commit()

    doc = Document(workspace_id=1, storage_key="g-ev", filename="gap-close.pdf")
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)
    ev = EvidenceItem(
        workspace_id=1,
        document_id=doc.id,
        title="Proof",
        source_type="document",
    )
    db_session.add(ev)
    db_session.commit()
    db_session.refresh(ev)
    db_session.add(ControlEvidenceLink(control_id=cid, evidence_id=ev.id, confidence_score=0.8))
    db_session.commit()

    _login_reviewer(client)
    data = _get_gaps_payload(client)
    qgaps = data["questionnaire_evidence_gaps"]
    assert not any(x["control_id"] == cid for x in qgaps)


def test_suggested_and_rejected_mappings_no_questionnaire_gap(
    client: TestClient,
    db_session: Session,
    qnr_two_questions: tuple,
):
    qnr, qs = qnr_two_questions
    wc = WorkspaceControl(workspace_id=1, framework_control_id=None, custom_name="Suggested WC")
    db_session.add(wc)
    db_session.commit()
    db_session.refresh(wc)
    cid = wc.id

    m_s = QuestionMappingPreference(
        workspace_id=1,
        questionnaire_id=qnr.id,
        question_id=qs[0].id,
        normalized_question_text="x",
        preferred_control_id=cid,
        source="ai",
        status="suggested",
        approved=False,
    )
    m_r = QuestionMappingPreference(
        workspace_id=1,
        questionnaire_id=qnr.id,
        question_id=qs[1].id,
        normalized_question_text="y",
        preferred_control_id=cid,
        source="ai",
        status="rejected",
        approved=False,
    )
    db_session.add_all([m_s, m_r])
    db_session.commit()

    _login_reviewer(client)
    data = _get_gaps_payload(client)
    assert not any(x["control_id"] == cid for x in data["questionnaire_evidence_gaps"])


def test_two_questions_same_control_one_row_with_two_refs(
    client: TestClient,
    db_session: Session,
    qnr_two_questions: tuple,
):
    qnr, qs = qnr_two_questions
    wc = WorkspaceControl(workspace_id=1, framework_control_id=None, custom_name="Multi-ref WC")
    db_session.add(wc)
    db_session.commit()
    db_session.refresh(wc)
    cid = wc.id

    for q in qs:
        db_session.add(
            QuestionMappingPreference(
                workspace_id=1,
                questionnaire_id=qnr.id,
                question_id=q.id,
                normalized_question_text=(q.text or "")[:2000],
                preferred_control_id=cid,
                source="manual",
                status="manual",
                approved=True,
            )
        )
    db_session.commit()

    _login_reviewer(client)
    data = _get_gaps_payload(client)
    hit = next((x for x in data["questionnaire_evidence_gaps"] if x["control_id"] == cid), None)
    assert hit is not None
    assert len(hit["questionnaire_refs"]) == 2
    qids = {r["question_id"] for r in hit["questionnaire_refs"]}
    assert qids == {qs[0].id, qs[1].id}


def test_mapping_preference_does_not_affect_questionnaire_evidence_gap_truth(
    client: TestClient,
    db_session: Session,
    qnr_two_questions: tuple,
):
    """Soft framework preference on questionnaire must not change zero-link evidence gap detection."""
    qnr, qs = qnr_two_questions
    wc = WorkspaceControl(workspace_id=1, framework_control_id=None, custom_name="Pref WC")
    db_session.add(wc)
    db_session.commit()
    db_session.refresh(wc)
    cid = wc.id

    m = QuestionMappingPreference(
        workspace_id=1,
        questionnaire_id=qnr.id,
        question_id=qs[0].id,
        normalized_question_text=(qs[0].text or "")[:2000],
        preferred_control_id=cid,
        source="manual",
        status="approved",
        approved=True,
    )
    db_session.add(m)
    db_session.commit()

    _login_reviewer(client)
    client.patch(
        f"/api/questionnaires/{qnr.id}/mapping-preference?workspace_id=1",
        json={"mapping_preferred_subject_areas": ["Encryption"]},
    )
    data_soc = _get_gaps_payload(client)
    assert any(x["control_id"] == cid for x in data_soc["questionnaire_evidence_gaps"])

    client.patch(
        f"/api/questionnaires/{qnr.id}/mapping-preference?workspace_id=1",
        json={"mapping_preferred_subject_areas": []},
    )
    data_all = _get_gaps_payload(client)
    assert any(x["control_id"] == cid for x in data_all["questionnaire_evidence_gaps"])
