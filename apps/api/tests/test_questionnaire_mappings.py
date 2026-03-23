"""Tests for questionnaire auto-mapping: generate, list, update, regenerate endpoints."""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings


def _login(client: TestClient, email: str = "demo@trust.local", password: str = "j"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login failed: {r.text}"


@pytest.fixture
def env_mapping_rerank_on_bulk_off():
    """LLM rerank on globally; bulk rerank off (default production-like for interactive bulk)."""
    old_llm = os.environ.get("MAPPING_LLM_RERANK")
    old_bulk = os.environ.get("MAPPING_LLM_RERANK_BULK")
    os.environ["MAPPING_LLM_RERANK"] = "1"
    os.environ["MAPPING_LLM_RERANK_BULK"] = "0"
    get_settings.cache_clear()
    yield
    if old_llm is None:
        os.environ.pop("MAPPING_LLM_RERANK", None)
    else:
        os.environ["MAPPING_LLM_RERANK"] = old_llm
    if old_bulk is None:
        os.environ.pop("MAPPING_LLM_RERANK_BULK", None)
    else:
        os.environ["MAPPING_LLM_RERANK_BULK"] = old_bulk
    get_settings.cache_clear()


def _create_questionnaire_with_questions(db: Session, workspace_id: int = 1) -> int:
    """Insert a test questionnaire with 3 questions directly in the DB."""
    from app.models.questionnaire import Questionnaire, Question

    qnr = Questionnaire(
        workspace_id=workspace_id,
        filename="test-mapping.xlsx",
        status="parsed",
        display_id="QNR-TEST-MAP",
    )
    db.add(qnr)
    db.commit()
    db.refresh(qnr)

    for i, text in enumerate([
        "How do you manage access control for your systems?",
        "What encryption standards do you use for data at rest?",
        "Describe your incident response process.",
    ]):
        db.add(Question(
            questionnaire_id=qnr.id,
            text=text,
            section=f"Section {i + 1}",
            answer_type="text",
        ))
    db.commit()
    return qnr.id


def _cleanup_questionnaire(db: Session, qnr_id: int):
    from app.models.questionnaire import Question, Questionnaire
    from app.models.ai_mapping import QuestionMappingPreference
    db.query(QuestionMappingPreference).filter(
        QuestionMappingPreference.questionnaire_id == qnr_id,
    ).delete()
    db.query(Question).filter(Question.questionnaire_id == qnr_id).delete()
    db.query(Questionnaire).filter(Questionnaire.id == qnr_id).delete()
    db.commit()


@pytest.fixture
def qnr_with_questions(db_session: Session):
    qnr_id = _create_questionnaire_with_questions(db_session)
    yield qnr_id
    _cleanup_questionnaire(db_session, qnr_id)


# -- auth tests --

def test_generate_mappings_requires_auth(client: TestClient):
    r = client.post("/api/questionnaires/1/generate-mappings?workspace_id=1")
    assert r.status_code == 401


def test_list_mappings_requires_auth(client: TestClient):
    r = client.get("/api/questionnaires/1/mappings?workspace_id=1")
    assert r.status_code == 401


# -- generate tests --

def test_generate_mappings_creates_rows(client: TestClient, qnr_with_questions: int):
    _login(client)
    qnr_id = qnr_with_questions

    r = client.post(f"/api/questionnaires/{qnr_id}/generate-mappings?workspace_id=1")
    assert r.status_code == 200
    data = r.json()
    assert data["total_questions"] == 3
    assert data["created"] + data["updated"] + data["skipped"] == 3


def test_generate_mappings_not_found(client: TestClient):
    _login(client)
    r = client.post("/api/questionnaires/99999/generate-mappings?workspace_id=1")
    assert r.status_code == 404


# -- list tests --

def test_list_mappings_returns_shape(client: TestClient, qnr_with_questions: int):
    _login(client)
    qnr_id = qnr_with_questions

    client.post(f"/api/questionnaires/{qnr_id}/generate-mappings?workspace_id=1")

    r = client.get(f"/api/questionnaires/{qnr_id}/mappings?workspace_id=1")
    assert r.status_code == 200
    data = r.json()
    assert "mappings" in data
    assert data.get("mapping_preferred_subject_areas") == []
    assert data["total_questions"] == 3
    assert data["mapped_count"] == sum(
        1 for m in data["mappings"] if m.get("preferred_control_id") is not None
    )

    for m in data["mappings"]:
        assert "id" in m
        assert "question_id" in m
        assert "question_text" in m
        assert "status" in m
        assert "source" in m
        assert "confidence" in m
        assert "supporting_evidence" in m
        assert isinstance(m["supporting_evidence"], list)
        assert "suggested_evidence" in m
        assert isinstance(m["suggested_evidence"], list)
        assert "match_keywords" in m
        assert isinstance(m["match_keywords"], list)
        assert m["status"] == "suggested"
        assert m["source"] == "ai"


@patch("app.api.routes.questionnaires.suggest_documents_for_mapping_review")
def test_list_mappings_omits_suggested_evidence_by_default(mock_suggest, client: TestClient, qnr_with_questions: int):
    """Large list loads must not run per-row retrieval (embed + search)."""
    _login(client)
    qnr_id = qnr_with_questions
    client.post(f"/api/questionnaires/{qnr_id}/generate-mappings?workspace_id=1")
    r = client.get(f"/api/questionnaires/{qnr_id}/mappings?workspace_id=1")
    assert r.status_code == 200
    mock_suggest.assert_not_called()
    for m in r.json()["mappings"]:
        assert m.get("suggested_evidence") == []


def test_list_mappings_include_suggested_evidence_param_accepted(client: TestClient, qnr_with_questions: int):
    """include_suggested_evidence=true is accepted; suggest runs only for rows with a control and no links."""
    _login(client)
    qnr_id = qnr_with_questions
    client.post(f"/api/questionnaires/{qnr_id}/generate-mappings?workspace_id=1")
    with patch("app.api.routes.questionnaires.batch_supporting_evidence_for_workspace_controls", return_value={}):
        with patch("app.api.routes.questionnaires.suggest_documents_for_mapping_review") as mock_suggest:
            mock_suggest.return_value = []
            r = client.get(
                f"/api/questionnaires/{qnr_id}/mappings",
                params={"workspace_id": 1, "include_suggested_evidence": True},
            )
            assert r.status_code == 200
            data = r.json()
            n_mapped = sum(1 for m in data["mappings"] if m.get("preferred_control_id") is not None)
            assert mock_suggest.call_count == n_mapped


def test_get_mapping_suggested_evidence_requires_auth(client: TestClient, qnr_with_questions: int):
    r = client.get(f"/api/questionnaires/{qnr_with_questions}/mappings/1/suggested-evidence?workspace_id=1")
    assert r.status_code == 401


# -- update tests --

def test_approve_mapping(client: TestClient, qnr_with_questions: int):
    _login(client)
    qnr_id = qnr_with_questions

    client.post(f"/api/questionnaires/{qnr_id}/generate-mappings?workspace_id=1")
    mappings = client.get(f"/api/questionnaires/{qnr_id}/mappings?workspace_id=1").json()["mappings"]
    m_id = mappings[0]["id"]

    r = client.patch(
        f"/api/questionnaires/{qnr_id}/mappings/{m_id}?workspace_id=1",
        json={"status": "approved"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    assert r.json()["approved"] is True


def test_reject_mapping(client: TestClient, qnr_with_questions: int):
    _login(client)
    qnr_id = qnr_with_questions

    client.post(f"/api/questionnaires/{qnr_id}/generate-mappings?workspace_id=1")
    mappings = client.get(f"/api/questionnaires/{qnr_id}/mappings?workspace_id=1").json()["mappings"]
    m_id = mappings[1]["id"]

    r = client.patch(
        f"/api/questionnaires/{qnr_id}/mappings/{m_id}?workspace_id=1",
        json={"status": "rejected"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert r.json()["approved"] is False


def test_invalid_status_rejected(client: TestClient, qnr_with_questions: int):
    _login(client)
    qnr_id = qnr_with_questions

    client.post(f"/api/questionnaires/{qnr_id}/generate-mappings?workspace_id=1")
    mappings = client.get(f"/api/questionnaires/{qnr_id}/mappings?workspace_id=1").json()["mappings"]
    m_id = mappings[0]["id"]

    r = client.patch(
        f"/api/questionnaires/{qnr_id}/mappings/{m_id}?workspace_id=1",
        json={"status": "invalid_status"},
    )
    assert r.status_code == 400


def test_update_mapping_not_found(client: TestClient, qnr_with_questions: int):
    _login(client)
    qnr_id = qnr_with_questions
    r = client.patch(
        f"/api/questionnaires/{qnr_id}/mappings/99999?workspace_id=1",
        json={"status": "approved"},
    )
    assert r.status_code == 404


# -- regeneration skips approved/manual --

def test_regenerate_skips_approved(client: TestClient, qnr_with_questions: int):
    _login(client)
    qnr_id = qnr_with_questions

    client.post(f"/api/questionnaires/{qnr_id}/generate-mappings?workspace_id=1")
    mappings = client.get(f"/api/questionnaires/{qnr_id}/mappings?workspace_id=1").json()["mappings"]

    client.patch(
        f"/api/questionnaires/{qnr_id}/mappings/{mappings[0]['id']}?workspace_id=1",
        json={"status": "approved"},
    )
    client.patch(
        f"/api/questionnaires/{qnr_id}/mappings/{mappings[1]['id']}?workspace_id=1",
        json={"status": "manual"},
    )

    r = client.post(f"/api/questionnaires/{qnr_id}/generate-mappings?workspace_id=1")
    data = r.json()
    assert data["skipped"] == 2
    assert data["updated"] == 1


# -- regenerate single --

def test_regenerate_single_mapping(client: TestClient, qnr_with_questions: int):
    _login(client)
    qnr_id = qnr_with_questions

    client.post(f"/api/questionnaires/{qnr_id}/generate-mappings?workspace_id=1")
    mappings = client.get(f"/api/questionnaires/{qnr_id}/mappings?workspace_id=1").json()["mappings"]

    client.patch(
        f"/api/questionnaires/{qnr_id}/mappings/{mappings[0]['id']}?workspace_id=1",
        json={"status": "approved"},
    )

    r = client.post(
        f"/api/questionnaires/{qnr_id}/mappings/{mappings[0]['id']}/regenerate?workspace_id=1",
    )
    assert r.status_code == 200
    assert r.json()["status"] == "suggested"
    assert r.json()["source"] == "ai"


def test_regenerate_single_not_found(client: TestClient, qnr_with_questions: int):
    _login(client)
    qnr_id = qnr_with_questions
    r = client.post(f"/api/questionnaires/{qnr_id}/mappings/99999/regenerate?workspace_id=1")
    assert r.status_code == 404


# -- persistence --

def test_list_mappings_supporting_evidence_via_control_link(
    client: TestClient,
    db_session: Session,
    qnr_with_questions: int,
):
    """Mapped control with ControlEvidenceLink surfaces evidence (framework preference does not filter it)."""
    from app.models import ControlEvidenceLink, Document, EvidenceItem, WorkspaceControl

    _login(client)
    qnr_id = qnr_with_questions
    client.post(f"/api/questionnaires/{qnr_id}/generate-mappings?workspace_id=1")
    data = client.get(f"/api/questionnaires/{qnr_id}/mappings?workspace_id=1").json()
    m0 = data["mappings"][0]

    wc = WorkspaceControl(
        workspace_id=1,
        framework_control_id=None,
        custom_name="Evidence API test WC",
    )
    db_session.add(wc)
    db_session.commit()
    db_session.refresh(wc)
    cid = wc.id

    r_patch = client.patch(
        f"/api/questionnaires/{qnr_id}/mappings/{m0['id']}?workspace_id=1",
        json={"preferred_control_id": cid},
    )
    assert r_patch.status_code == 200

    doc = Document(workspace_id=1, storage_key="qmap-ev-test", filename="mapping-evidence.pdf")
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)
    ev = EvidenceItem(
        workspace_id=1,
        document_id=doc.id,
        title="Policy excerpt",
        source_type="document",
    )
    db_session.add(ev)
    db_session.commit()
    db_session.refresh(ev)
    db_session.add(
        ControlEvidenceLink(control_id=cid, evidence_id=ev.id, confidence_score=0.91, verified=True),
    )
    db_session.commit()

    listed = client.get(f"/api/questionnaires/{qnr_id}/mappings?workspace_id=1").json()
    hit = next(x for x in listed["mappings"] if x["id"] == m0["id"])
    assert len(hit["supporting_evidence"]) >= 1
    top = hit["supporting_evidence"][0]
    assert top["evidence_id"] == ev.id
    assert top["filename"] == "mapping-evidence.pdf"
    assert top["source"] == "control_evidence_link"

    client.patch(
        f"/api/questionnaires/{qnr_id}/mapping-preference?workspace_id=1",
        json={"mapping_preferred_subject_areas": ["Encryption"]},
    )
    listed2 = client.get(f"/api/questionnaires/{qnr_id}/mappings?workspace_id=1").json()
    hit2 = next(x for x in listed2["mappings"] if x["id"] == m0["id"])
    assert len(hit2["supporting_evidence"]) == len(hit["supporting_evidence"])


def test_patch_mapping_preference_subject_areas(client: TestClient, qnr_with_questions: int):
    _login(client)
    qnr_id = qnr_with_questions
    r = client.patch(
        f"/api/questionnaires/{qnr_id}/mapping-preference?workspace_id=1",
        json={"mapping_preferred_subject_areas": ["Access Control", "Encryption"]},
    )
    assert r.status_code == 200
    assert r.json()["mapping_preferred_subject_areas"] == ["Access Control", "Encryption"]
    listed = client.get(f"/api/questionnaires/{qnr_id}/mappings?workspace_id=1").json()
    assert listed["mapping_preferred_subject_areas"] == ["Access Control", "Encryption"]
    r_all = client.patch(
        f"/api/questionnaires/{qnr_id}/mapping-preference?workspace_id=1",
        json={"mapping_preferred_subject_areas": []},
    )
    assert r_all.status_code == 200
    assert r_all.json()["mapping_preferred_subject_areas"] == []


def test_patch_mapping_preference_unknown_labels_filtered(client: TestClient, qnr_with_questions: int):
    _login(client)
    qnr_id = qnr_with_questions
    r = client.patch(
        f"/api/questionnaires/{qnr_id}/mapping-preference?workspace_id=1",
        json={"mapping_preferred_subject_areas": ["Not A Catalog Label", "Encryption"]},
    )
    assert r.status_code == 200
    assert r.json()["mapping_preferred_subject_areas"] == ["Encryption"]


def test_mappings_persist_after_refresh(client: TestClient, qnr_with_questions: int):
    _login(client)
    qnr_id = qnr_with_questions

    client.post(f"/api/questionnaires/{qnr_id}/generate-mappings?workspace_id=1")
    mappings = client.get(f"/api/questionnaires/{qnr_id}/mappings?workspace_id=1").json()["mappings"]

    client.patch(
        f"/api/questionnaires/{qnr_id}/mappings/{mappings[0]['id']}?workspace_id=1",
        json={"status": "approved"},
    )

    r2 = client.get(f"/api/questionnaires/{qnr_id}/mappings?workspace_id=1")
    assert r2.status_code == 200
    refreshed = r2.json()["mappings"]
    approved = [m for m in refreshed if m["status"] == "approved"]
    assert len(approved) == 1
    assert approved[0]["id"] == mappings[0]["id"]


# -- bulk vs single-row LLM rerank --


def test_bulk_generate_does_not_call_maybe_rerank_when_bulk_disabled(
    client: TestClient,
    qnr_with_questions: int,
    env_mapping_rerank_on_bulk_off,
):
    _login(client)
    qnr_id = qnr_with_questions

    def _fail(*_a, **_k):
        raise AssertionError("maybe_rerank should not run for bulk when MAPPING_LLM_RERANK_BULK is 0")

    with patch("app.services.compliance_hooks.maybe_rerank_framework_controls_with_llm", side_effect=_fail):
        r = client.post(f"/api/questionnaires/{qnr_id}/generate-mappings?workspace_id=1")
    assert r.status_code == 200


def test_regenerate_single_passes_skip_llm_rerank_false(
    client: TestClient,
    qnr_with_questions: int,
    env_mapping_rerank_on_bulk_off,
):
    """Single-row regenerate must not use the bulk fast path (LLM rerank allowed when enabled)."""
    _login(client)
    qnr_id = qnr_with_questions
    from app.services.mapping_llm_classify import classify_and_persist

    with patch("app.api.routes.questionnaires.classify_question_signal", wraps=classify_and_persist) as m_cls:
        client.post(f"/api/questionnaires/{qnr_id}/generate-mappings?workspace_id=1")
        m_cls.reset_mock()
        mappings = client.get(f"/api/questionnaires/{qnr_id}/mappings?workspace_id=1").json()["mappings"]
        r = client.post(
            f"/api/questionnaires/{qnr_id}/mappings/{mappings[0]['id']}/regenerate?workspace_id=1",
        )
    assert r.status_code == 200
    assert m_cls.call_count >= 1
