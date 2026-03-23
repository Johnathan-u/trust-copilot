"""Batch supporting evidence for questionnaire mappings (ControlEvidenceLink only)."""

import pytest
from sqlalchemy.orm import Session

from app.models import ControlEvidenceLink, Document, EvidenceItem, WorkspaceControl
from app.services.questionnaire_mapping_evidence import (
    batch_supporting_evidence_for_workspace_controls,
    is_stub_like,
)


@pytest.fixture
def temp_workspace_control(db_session: Session) -> int:
    wc = WorkspaceControl(workspace_id=1, framework_control_id=None, custom_name="Temp WC for evidence test")
    db_session.add(wc)
    db_session.commit()
    db_session.refresh(wc)
    wid = wc.id
    try:
        yield wid
    finally:
        db_session.query(ControlEvidenceLink).filter(ControlEvidenceLink.control_id == wid).delete(
            synchronize_session=False
        )
        db_session.query(WorkspaceControl).filter(WorkspaceControl.id == wid).delete(synchronize_session=False)
        db_session.commit()


def test_is_stub_like_detects_placeholders():
    assert is_stub_like("sample_evidence.txt", None) is True
    assert is_stub_like("policy.pdf", "Lorem ipsum excerpt") is True
    assert is_stub_like("security-policy.pdf", "Information Security Policy") is False


def test_batch_returns_empty_without_links(db_session: Session, temp_workspace_control: int):
    out = batch_supporting_evidence_for_workspace_controls(db_session, 1, [temp_workspace_control])
    assert out[temp_workspace_control] == []


def test_batch_excludes_evidence_from_other_workspace(db_session: Session, temp_workspace_control: int):
    """Links to evidence in workspace 2 must not appear when querying workspace 1."""
    doc = Document(workspace_id=2, storage_key="x", filename="wrong.pdf")
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)
    ev = EvidenceItem(workspace_id=2, document_id=doc.id, title="Wrong WS", source_type="document")
    db_session.add(ev)
    db_session.commit()
    db_session.refresh(ev)
    db_session.add(
        ControlEvidenceLink(
            control_id=temp_workspace_control,
            evidence_id=ev.id,
            confidence_score=0.99,
            verified=True,
        )
    )
    db_session.commit()

    out = batch_supporting_evidence_for_workspace_controls(db_session, 1, [temp_workspace_control])
    assert out[temp_workspace_control] == []


def test_batch_includes_linked_workspace_evidence(db_session: Session, temp_workspace_control: int):
    doc = Document(workspace_id=1, storage_key="k-ev", filename="security-policy.pdf")
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)
    ev = EvidenceItem(
        workspace_id=1,
        document_id=doc.id,
        title="Security policy",
        source_type="document",
    )
    db_session.add(ev)
    db_session.commit()
    db_session.refresh(ev)
    db_session.add(
        ControlEvidenceLink(
            control_id=temp_workspace_control,
            evidence_id=ev.id,
            confidence_score=0.85,
            verified=False,
        )
    )
    db_session.commit()

    out = batch_supporting_evidence_for_workspace_controls(db_session, 1, [temp_workspace_control])
    rows = out[temp_workspace_control]
    assert len(rows) == 1
    assert rows[0]["evidence_id"] == ev.id
    assert rows[0]["document_id"] == doc.id
    assert rows[0]["filename"] == "security-policy.pdf"
    assert rows[0]["source"] == "control_evidence_link"
    assert rows[0]["link_confidence"] == 0.85
    assert rows[0]["verified"] is False


def test_verified_link_sorts_before_unverified(db_session: Session, temp_workspace_control: int):
    doc1 = Document(workspace_id=1, storage_key="a", filename="a.pdf")
    doc2 = Document(workspace_id=1, storage_key="b", filename="b.pdf")
    db_session.add_all([doc1, doc2])
    db_session.commit()
    db_session.refresh(doc1)
    db_session.refresh(doc2)
    ev_lo = EvidenceItem(workspace_id=1, document_id=doc1.id, title="Low", source_type="document")
    ev_hi = EvidenceItem(workspace_id=1, document_id=doc2.id, title="High", source_type="document")
    db_session.add_all([ev_lo, ev_hi])
    db_session.commit()
    db_session.refresh(ev_lo)
    db_session.refresh(ev_hi)
    db_session.add_all(
        [
            ControlEvidenceLink(
                control_id=temp_workspace_control,
                evidence_id=ev_lo.id,
                confidence_score=0.99,
                verified=False,
            ),
            ControlEvidenceLink(
                control_id=temp_workspace_control,
                evidence_id=ev_hi.id,
                confidence_score=0.5,
                verified=True,
            ),
        ]
    )
    db_session.commit()

    out = batch_supporting_evidence_for_workspace_controls(db_session, 1, [temp_workspace_control])
    ids = [r["evidence_id"] for r in out[temp_workspace_control]]
    assert ids[0] == ev_hi.id


def test_duplicate_links_same_evidence_deduped(db_session: Session, temp_workspace_control: int):
    doc = Document(workspace_id=1, storage_key="d", filename="one.pdf")
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)
    ev = EvidenceItem(workspace_id=1, document_id=doc.id, title="One", source_type="document")
    db_session.add(ev)
    db_session.commit()
    db_session.refresh(ev)
    db_session.add_all(
        [
            ControlEvidenceLink(control_id=temp_workspace_control, evidence_id=ev.id, confidence_score=0.5),
            ControlEvidenceLink(control_id=temp_workspace_control, evidence_id=ev.id, confidence_score=0.9),
        ]
    )
    db_session.commit()

    out = batch_supporting_evidence_for_workspace_controls(db_session, 1, [temp_workspace_control])
    assert len(out[temp_workspace_control]) == 1
