"""Real SQL projection checks; SQLite does not qualify PostgreSQL migrations."""

from datetime import datetime

import pytest
from sqlalchemy import Column, DateTime, Integer, MetaData, Table, create_engine
from sqlalchemy.orm import Session

from app.models import EvidenceGap
from app.services.compliance_coverage import _attach_gap_provenance, _recommendation

pytestmark = pytest.mark.unit


@pytest.fixture
def question_projection():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    questionnaires = Table(
        "questionnaires",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("workspace_id", Integer, nullable=False),
        Column("deleted_at", DateTime),
    )
    questions = Table(
        "questions",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("questionnaire_id", Integer, nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            questionnaires.insert(),
            [
                {"id": 11, "workspace_id": 1, "deleted_at": None},
                {"id": 22, "workspace_id": 1, "deleted_at": None},
                {"id": 33, "workspace_id": 2, "deleted_at": None},
                {"id": 44, "workspace_id": 1, "deleted_at": datetime(2026, 1, 1)},
            ],
        )
        connection.execute(
            questions.insert(),
            [
                {"id": 101, "questionnaire_id": 22},
                {"id": 102, "questionnaire_id": 22},
                {"id": 105, "questionnaire_id": 11},
                {"id": 301, "questionnaire_id": 33},
                {"id": 401, "questionnaire_id": 44},
            ],
        )
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_titled_sources_use_actual_parents_and_drop_unavailable_questions(question_projection):
    # The independently stored gap questionnaire must not override the question's parent.
    gaps = [
        EvidenceGap(
            suggested_evidence_doc_title="Policy",
            question_id=question_id,
            questionnaire_id=11,
        )
        for question_id in [105, 101, 101, 301, 401, 9999]
    ]
    gaps.append(EvidenceGap(suggested_evidence_doc_title="Other", question_id=102))
    suggestions = [
        _recommendation("Policy", 6),
        _recommendation("Other", 1),
        _recommendation("Sourceless", 1),
    ]

    _attach_gap_provenance(question_projection, 1, suggestions, gaps)

    assert suggestions[0]["question_sources"] == [
        {"question_id": 101, "questionnaire_id": 22},
        {"question_id": 105, "questionnaire_id": 11},
    ]
    assert suggestions[0]["question_ids"] == [101, 105]
    assert suggestions[0]["improves_questions"] == 6
    assert suggestions[1]["question_sources"] == [{"question_id": 102, "questionnaire_id": 22}]
    assert suggestions[2]["question_sources"] == []
    assert suggestions[2]["question_ids"] == []
    assert suggestions[2]["improves_questions"] == 1
