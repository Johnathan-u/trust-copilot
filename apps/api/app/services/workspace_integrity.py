"""Same-workspace checks for write paths that store a reference to another workspace-owned row.

A foreign key only proves the target row exists. These helpers prove it also belongs to the
caller's workspace. Questions and answers carry no workspace_id, so ownership is resolved through
Answer -> Question -> Questionnaire.workspace_id.

Routes translate CrossWorkspaceReference into a uniform 404 so a caller cannot tell a missing id
from another tenant's id. Migration tc06001_same_workspace_refs enforces the same rule in Postgres
for new writes to evidence_items, export_records and evidence_gaps.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Answer, Document, Question, Questionnaire

NOT_FOUND_DETAIL = "Referenced resource not found"


class CrossWorkspaceReference(LookupError):
    """A referenced id is missing or belongs to a different workspace."""


class InvalidReference(ValueError):
    """A referenced id is not an integer."""


def db_exists(query) -> bool:
    return query.limit(1).first() is not None


def document_in_workspace(db: Session, workspace_id: int, document_id: int) -> bool:
    return db_exists(
        db.query(Document.id).filter(
            Document.id == document_id, Document.workspace_id == workspace_id
        )
    )


def questionnaire_in_workspace(db: Session, workspace_id: int, questionnaire_id: int) -> bool:
    return db_exists(
        db.query(Questionnaire.id).filter(
            Questionnaire.id == questionnaire_id, Questionnaire.workspace_id == workspace_id
        )
    )


def question_in_workspace(db: Session, workspace_id: int, question_id: int) -> bool:
    return db_exists(
        db.query(Question.id)
        .join(Questionnaire, Questionnaire.id == Question.questionnaire_id)
        .filter(Question.id == question_id, Questionnaire.workspace_id == workspace_id)
    )


def answer_in_workspace(db: Session, workspace_id: int, answer_id: int) -> bool:
    return db_exists(
        db.query(Answer.id)
        .join(Question, Question.id == Answer.question_id)
        .join(Questionnaire, Questionnaire.id == Question.questionnaire_id)
        .filter(Answer.id == answer_id, Questionnaire.workspace_id == workspace_id)
    )


_CHECKS = {
    "document_id": document_in_workspace,
    "questionnaire_id": questionnaire_in_workspace,
    "question_id": question_in_workspace,
    "answer_id": answer_in_workspace,
}


def require_same_workspace(db: Session, workspace_id: int, **refs: int | None) -> None:
    """Raise CrossWorkspaceReference unless every non-null ref belongs to workspace_id.

    Raises InvalidReference when a ref is not an integer (callers map it to 422).

    Accepted keywords: document_id, questionnaire_id, question_id, answer_id.
    """
    for name, value in refs.items():
        if value is None:
            continue
        check = _CHECKS[name]
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidReference(name)
        if not check(db, workspace_id, value):
            raise CrossWorkspaceReference(name)
