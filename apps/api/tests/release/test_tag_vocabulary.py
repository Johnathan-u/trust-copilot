"""TC-08-011: canonical tag vocabulary, alias resolution, and mapping invalidation.

The catalog contract is ``docs/product/tag-vocabulary.json``. Runtime code loads that
file when the checkout contains it, and the packaged copy under
``app/data/tag_vocabulary.json`` otherwise. These tests fail if the two copies or
the loaded catalog diverge, if an alias becomes a second tag key, if an unapproved
suggestion is written into document JSON, or if a tag change stale-marks a mapping
that did not use that tag.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.models import Document, EvidenceItem, EvidenceTagMapping, QuestionMappingPreference, Tag
from app.services import tag_service
from app.services.tag_service import (
    SYSTEM_TAGS,
    approve_tag,
    assign_tag,
    auto_tag_document,
    ensure_system_tags,
    get_or_create_tag,
    remove_tag,
    resolve_tag,
)

REPO = Path(__file__).resolve().parents[4]
DOCS_VOCABULARY = REPO / "docs" / "product" / "tag-vocabulary.json"
PACKAGED_VOCABULARY = (
    Path(tag_service.__file__).resolve().parent.parent / "data" / "tag_vocabulary.json"
)
DOCUMENT_TYPES = (
    ("policy", "Policy"),
    ("procedure", "Procedure"),
    ("report", "Report"),
    ("screenshot", "Screenshot"),
    ("training_record", "Training Record"),
    ("certificate", "Certificate"),
)


def _token(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _docs() -> dict:
    assert DOCS_VOCABULARY.is_file(), f"missing {DOCS_VOCABULARY}"
    return json.loads(DOCS_VOCABULARY.read_text(encoding="utf-8"))


def _login(client, email: str, password: str) -> None:
    client.post("/api/auth/login", json={"email": email, "password": password})


def _create_doc(db: Session, workspace_id: int, frameworks: list[str] | None = None) -> Document:
    doc = Document(
        workspace_id=workspace_id,
        storage_key=f"synthetic/{uuid.uuid4().hex}.pdf",
        filename="synthetic.pdf",
        status="uploaded",
        frameworks_json=json.dumps(frameworks) if frameworks else None,
    )
    db.add(doc)
    db.flush()
    return doc


def _preference(db: Session, workspace_id: int, tag_id: int) -> QuestionMappingPreference:
    row = QuestionMappingPreference(
        workspace_id=workspace_id,
        preferred_tag_id=tag_id,
        source="ai",
        status="approved",
        approved=True,
        normalized_question_text="synthetic question",
    )
    db.add(row)
    db.flush()
    return row


def _evidence_mapping(db: Session, workspace_id: int, tag_id: int) -> EvidenceTagMapping:
    evidence = EvidenceItem(
        workspace_id=workspace_id,
        title="synthetic evidence",
        source_type="manual",
    )
    db.add(evidence)
    db.flush()
    row = EvidenceTagMapping(
        workspace_id=workspace_id,
        evidence_id=evidence.id,
        tag_id=tag_id,
        source="ai",
        approved=True,
    )
    db.add(row)
    db.flush()
    return row


def _assert_only_target_stale(
    db: Session,
    target_pref: QuestionMappingPreference,
    other_pref: QuestionMappingPreference,
    other_workspace_pref: QuestionMappingPreference,
    target_evidence: EvidenceTagMapping,
    other_evidence: EvidenceTagMapping,
    other_workspace_evidence: EvidenceTagMapping,
) -> None:
    db.refresh(target_pref)
    db.refresh(other_pref)
    db.refresh(other_workspace_pref)
    db.refresh(target_evidence)
    db.refresh(other_evidence)
    db.refresh(other_workspace_evidence)
    assert target_pref.status == "stale"
    assert target_pref.approved is False
    assert other_pref.status == "approved"
    assert other_pref.approved is True
    assert other_workspace_pref.status == "approved"
    assert other_workspace_pref.approved is True
    assert target_evidence.approved is False
    assert other_evidence.approved is True
    assert other_workspace_evidence.approved is True


@pytest.fixture
def db(db_session: Session, _ensure_test_data: bool) -> Session:
    assert _ensure_test_data
    ensure_system_tags(db_session)
    return db_session


def test_vocabulary_aliases_do_not_collide() -> None:
    docs = _docs()
    assert docs["version"] == 1
    assert docs["subject_tag_category"] == "topic"
    for section in ("frameworks", "subjects"):
        seen: dict[str, str] = {}
        for entry in docs[section]:
            tokens = [_token(entry["key"]), _token(entry["label"])]
            tokens.extend(_token(alias) for alias in entry["aliases"])
            for item in tokens:
                assert item, entry["key"]
                previous = seen.get(item)
                assert previous in (None, entry["key"]), (item, previous, entry["key"])
                seen[item] = entry["key"]


def test_runtime_catalog_matches_the_docs_file() -> None:
    docs = _docs()
    assert PACKAGED_VOCABULARY.is_file()
    packaged = json.loads(PACKAGED_VOCABULARY.read_text(encoding="utf-8"))
    assert packaged == docs
    from app.services.tag_vocabulary import load_tag_vocabulary, vocabulary_path

    assert load_tag_vocabulary() == docs
    assert vocabulary_path().resolve() == DOCS_VOCABULARY.resolve()
    frameworks = [
        (row["key"], row["label"]) for row in SYSTEM_TAGS if row["category"] == "framework"
    ]
    subjects = [(row["key"], row["label"]) for row in SYSTEM_TAGS if row["category"] == "topic"]
    assert frameworks == [(entry["key"], entry["label"]) for entry in docs["frameworks"]]
    assert subjects == [(entry["key"], entry["label"]) for entry in docs["subjects"]]
    document_types = [
        (row["key"], row["label"]) for row in SYSTEM_TAGS if row["category"] == "document_type"
    ]
    assert document_types == list(DOCUMENT_TYPES)


def test_alias_resolves_to_one_canonical_tag(db: Session) -> None:
    docs = _docs()
    before = db.query(Tag).count()
    soc = get_or_create_tag(db, "framework", "SOC II", "SOC II", workspace_id=1)
    iso = resolve_tag(db, "framework", "ISO/IEC 27001", workspace_id=1)
    identity = get_or_create_tag(db, "topic", "iam", "IAM", workspace_id=1)
    access = resolve_tag(db, "topic", "Access Control", workspace_id=1)
    db.flush()
    assert soc.key == "soc2"
    assert soc.label == "SOC 2"
    assert soc.is_system is True
    assert soc.workspace_id is None
    assert iso is not None and iso.key == "iso27001"
    assert identity.key == "identity_authentication"
    assert access is not None and access.key == "access_control"
    assert db.query(Tag).count() == before
    canonical = {entry["key"] for entry in docs["frameworks"]}
    canonical.update(entry["key"] for entry in docs["subjects"])
    assert soc.key in canonical
    second = get_or_create_tag(db, "framework", "soc-2", "SOC-2", workspace_id=1)
    assert second.id == soc.id


def test_unknown_key_still_creates_a_workspace_tag(db: Session) -> None:
    key = f"custom_{uuid.uuid4().hex}"
    created = get_or_create_tag(db, "custom", key, "Synthetic", workspace_id=1)
    db.flush()
    assert created.key == key
    assert created.workspace_id == 1
    assert created.is_system is False
    again = get_or_create_tag(db, "custom", key, "Synthetic", workspace_id=1)
    assert again.id == created.id
    hidden = {row["key"] for row in tag_service.list_available_tags(db, 2)}
    assert key not in hidden


def test_suggestions_stay_out_of_document_json_until_approved(db: Session) -> None:
    from unittest.mock import patch

    doc = _create_doc(db, 1, frameworks=["GDPR"])
    suggestions = [
        {"key": "soc2", "category": "framework", "confidence": 0.85},
        {"key": "access_control", "category": "topic", "confidence": 0.8},
        {"key": "policy", "category": "document_type", "confidence": 0.8},
    ]
    with (
        patch("app.services.tag_service._classify_document_deterministic", return_value=([], True)),
        patch("app.services.tag_service._classify_document_llm_tiebreak", return_value=suggestions),
    ):
        count = auto_tag_document(
            db,
            doc.id,
            workspace_id=1,
            filename="synthetic.pdf",
            chunk_texts=["synthetic SOC 2 access control text"],
        )
    db.flush()
    db.refresh(doc)
    assert count == 3
    assert json.loads(doc.frameworks_json or "[]") == ["GDPR"]
    assert doc.subject_areas_json in (None, "[]", "null")
    rows = tag_service.list_tags_for_document(db, doc.id, 1)
    assert {row["key"] for row in rows} == {"soc2", "access_control", "policy"}
    assert all(row["approved"] is False and row["source"] == "ai" for row in rows)
    soc_assignment = next(row for row in rows if row["key"] == "soc2")
    topic_assignment = next(row for row in rows if row["key"] == "access_control")
    approve_tag(db, soc_assignment["id"], workspace_id=1, approved=True)
    db.flush()
    db.refresh(doc)
    assert json.loads(doc.frameworks_json) == ["GDPR", "SOC 2"]
    assert doc.subject_areas_json in (None, "[]", "null")
    approve_tag(db, topic_assignment["id"], workspace_id=1, approved=True)
    db.flush()
    db.refresh(doc)
    assert json.loads(doc.subject_areas_json) == ["Access Control"]
    approve_tag(db, soc_assignment["id"], workspace_id=1, approved=False)
    db.flush()
    db.refresh(doc)
    assert json.loads(doc.frameworks_json) == ["GDPR"]


def test_add_invalidates_only_mappings_for_that_tag(db: Session) -> None:
    soc = resolve_tag(db, "framework", "soc2")
    hipaa = resolve_tag(db, "framework", "hipaa")
    assert soc is not None and hipaa is not None
    doc = _create_doc(db, 1)
    target = _preference(db, 1, soc.id)
    other = _preference(db, 1, hipaa.id)
    other_ws = _preference(db, 2, soc.id)
    target_evidence = _evidence_mapping(db, 1, soc.id)
    other_evidence = _evidence_mapping(db, 1, hipaa.id)
    other_ws_evidence = _evidence_mapping(db, 2, soc.id)
    assign_tag(db, doc.id, soc.id, workspace_id=1, source="manual", approved=True)
    _assert_only_target_stale(
        db, target, other, other_ws, target_evidence, other_evidence, other_ws_evidence
    )
    db.flush()
    db.refresh(doc)
    assert json.loads(doc.frameworks_json or "[]") == ["SOC 2"]


def test_approve_invalidates_only_mappings_for_that_tag(db: Session) -> None:
    soc = resolve_tag(db, "framework", "soc2")
    hipaa = resolve_tag(db, "framework", "hipaa")
    assert soc is not None and hipaa is not None
    doc = _create_doc(db, 1, frameworks=["GDPR"])
    assignment = assign_tag(db, doc.id, soc.id, workspace_id=1, source="ai", approved=False)
    db.refresh(doc)
    assert json.loads(doc.frameworks_json) == ["GDPR"]
    target = _preference(db, 1, soc.id)
    other = _preference(db, 1, hipaa.id)
    other_ws = _preference(db, 2, soc.id)
    target_evidence = _evidence_mapping(db, 1, soc.id)
    other_evidence = _evidence_mapping(db, 1, hipaa.id)
    other_ws_evidence = _evidence_mapping(db, 2, soc.id)
    approve_tag(db, assignment.id, workspace_id=1, approved=True)
    _assert_only_target_stale(
        db, target, other, other_ws, target_evidence, other_evidence, other_ws_evidence
    )
    db.flush()
    db.refresh(doc)
    assert json.loads(doc.frameworks_json) == ["GDPR", "SOC 2"]


def test_remove_invalidates_only_mappings_for_that_tag(db: Session) -> None:
    soc = resolve_tag(db, "framework", "soc2")
    hipaa = resolve_tag(db, "framework", "hipaa")
    assert soc is not None and hipaa is not None
    doc = _create_doc(db, 1, frameworks=["GDPR"])
    assign_tag(db, doc.id, soc.id, workspace_id=1, source="manual", approved=True)
    target = _preference(db, 1, soc.id)
    other = _preference(db, 1, hipaa.id)
    other_ws = _preference(db, 2, soc.id)
    target_evidence = _evidence_mapping(db, 1, soc.id)
    other_evidence = _evidence_mapping(db, 1, hipaa.id)
    other_ws_evidence = _evidence_mapping(db, 2, soc.id)
    assert remove_tag(db, doc.id, soc.id, workspace_id=1) is True
    _assert_only_target_stale(
        db, target, other, other_ws, target_evidence, other_evidence, other_ws_evidence
    )
    db.flush()
    db.refresh(doc)
    assert json.loads(doc.frameworks_json) == ["GDPR"]


def test_relabel_invalidates_only_mappings_for_that_tag(db: Session) -> None:
    relabel = getattr(tag_service, "relabel_tag", None)
    assert relabel is not None
    key = f"custom_{uuid.uuid4().hex}"
    custom = get_or_create_tag(db, "custom", key, "Old Label", workspace_id=1)
    other_tag = resolve_tag(db, "framework", "hipaa")
    system = resolve_tag(db, "framework", "soc2")
    assert other_tag is not None and system is not None
    doc = _create_doc(db, 1)
    assign_tag(db, doc.id, custom.id, workspace_id=1, source="manual", approved=True)
    target = _preference(db, 1, custom.id)
    other = _preference(db, 1, other_tag.id)
    other_ws = _preference(db, 2, custom.id)
    target_evidence = _evidence_mapping(db, 1, custom.id)
    other_evidence = _evidence_mapping(db, 1, other_tag.id)
    other_ws_evidence = _evidence_mapping(db, 2, custom.id)
    updated = relabel(db, custom.id, workspace_id=1, label="New Label")
    assert updated is not None
    assert updated.label == "New Label"
    _assert_only_target_stale(
        db, target, other, other_ws, target_evidence, other_evidence, other_ws_evidence
    )
    refused = relabel(db, system.id, workspace_id=1, label="Not SOC")
    assert refused is None
    db.refresh(system)
    assert system.label == "SOC 2"


def test_editor_cannot_relabel(client, db: Session) -> None:
    key = f"custom_{uuid.uuid4().hex}"
    custom = get_or_create_tag(db, "custom", key, "Keep", workspace_id=1)
    db.commit()
    _login(client, "editor@trust.local", "e")
    response = client.patch(f"/api/tags/{custom.id}", json={"label": "Changed"})
    assert response.status_code == 403
    db.refresh(custom)
    assert custom.label == "Keep"


def test_reviewer_relabel_stays_inside_the_workspace(client, db: Session) -> None:
    own_key = f"custom_{uuid.uuid4().hex}"
    foreign_key = f"custom_{uuid.uuid4().hex}"
    own = get_or_create_tag(db, "custom", own_key, "Own", workspace_id=1)
    foreign = get_or_create_tag(db, "custom", foreign_key, "Foreign", workspace_id=2)
    system = resolve_tag(db, "framework", "soc2")
    assert system is not None
    doc = _create_doc(db, 1)
    assign_tag(db, doc.id, own.id, workspace_id=1, source="manual", approved=True)
    db.commit()
    _login(client, "reviewer@trust.local", "r")
    renamed = client.patch(f"/api/tags/{own.id}", json={"label": "Renamed"})
    assert renamed.status_code == 200
    assert renamed.json()["label"] == "Renamed"
    assert renamed.json()["key"] == own_key
    blocked = client.patch(f"/api/tags/{foreign.id}", json={"label": "Stolen"})
    assert blocked.status_code == 404
    system_response = client.patch(f"/api/tags/{system.id}", json={"label": "Not SOC"})
    assert system_response.status_code == 404
    db.flush()
    db.refresh(foreign)
    db.refresh(system)
    db.refresh(own)
    db.refresh(doc)
    assert foreign.label == "Foreign"
    assert system.label == "SOC 2"
    assert own.label == "Renamed"
    assert doc.frameworks_json in (None, "[]", "null")
    assert doc.subject_areas_json in (None, "[]", "null")
