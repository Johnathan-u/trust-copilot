"""Same-workspace validation for referenced ids (TC-06-BUG-013).

Routes that accept ids of other records (in the request body or the path) must
make sure each referenced row exists *and* belongs to the caller's workspace
before using it. A missing id and an id owned by another workspace are
indistinguishable to the caller: both raise the same 404.
"""

from collections.abc import Iterable

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.deal import Deal
from app.models.evidence_item import EvidenceItem
from app.models.golden_answer import GoldenAnswer
from app.models.operator_queue import OperatorQueueItem
from app.models.questionnaire import Question, Questionnaire
from app.models.remediation_playbook import RemediationPlaybook, RemediationTicket
from app.models.tag import Tag
from app.models.trust_promise import TrustPromise
from app.models.user import WorkspaceMember
from app.models.workspace_control import WorkspaceControl

NOT_FOUND_DETAIL = "Referenced resource not found"


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)


def _owned_ids(db: Session, workspace_id: int, kind: str, ids: set[int]) -> set[int]:
    """Return the subset of ``ids`` of type ``kind`` visible in ``workspace_id``."""
    if kind == "questionnaire":
        q = db.query(Questionnaire.id).filter(
            Questionnaire.id.in_(ids),
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_(None),
        )
    elif kind == "question":
        q = (
            db.query(Question.id)
            .join(Questionnaire, Question.questionnaire_id == Questionnaire.id)
            .filter(
                Question.id.in_(ids),
                Questionnaire.workspace_id == workspace_id,
                Questionnaire.deleted_at.is_(None),
            )
        )
    elif kind == "answer":
        q = (
            db.query(Answer.id)
            .join(Question, Answer.question_id == Question.id)
            .join(Questionnaire, Question.questionnaire_id == Questionnaire.id)
            .filter(
                Answer.id.in_(ids),
                Questionnaire.workspace_id == workspace_id,
                Questionnaire.deleted_at.is_(None),
            )
        )
    elif kind == "tag":
        # Tags are either global (workspace_id NULL) or workspace-scoped.
        q = db.query(Tag.id).filter(
            Tag.id.in_(ids),
            or_(Tag.workspace_id == workspace_id, Tag.workspace_id.is_(None)),
        )
    elif kind == "user":
        q = db.query(WorkspaceMember.user_id).filter(
            WorkspaceMember.user_id.in_(ids),
            WorkspaceMember.workspace_id == workspace_id,
        )
    else:
        model = _SIMPLE_MODELS.get(kind)
        if model is None:
            raise ValueError(f"Unknown reference kind: {kind}")
        q = db.query(model.id).filter(model.id.in_(ids), model.workspace_id == workspace_id)
    return {row[0] for row in q.all()}


_SIMPLE_MODELS = {
    "deal": Deal,
    "golden_answer": GoldenAnswer,
    "control": WorkspaceControl,
    "evidence": EvidenceItem,
    "playbook": RemediationPlaybook,
    "remediation_ticket": RemediationTicket,
    "promise": TrustPromise,
    "operator_queue_item": OperatorQueueItem,
}


def require_in_workspace(
    db: Session,
    workspace_id: int | None,
    kind: str,
    ids: int | Iterable[int] | None,
) -> None:
    """Raise the uniform 404 unless every id of ``kind`` belongs to ``workspace_id``.

    ``None`` (an optional reference that was not supplied) and an empty list are accepted.
    """
    if ids is None:
        return
    wanted = {ids} if isinstance(ids, int) else set(ids)
    if not wanted:
        return
    if workspace_id is None:
        raise _not_found()
    if _owned_ids(db, workspace_id, kind, wanted) != wanted:
        raise _not_found()


def require_refs(
    db: Session,
    workspace_id: int | None,
    refs: Iterable[tuple[str, int | Iterable[int] | None]],
) -> None:
    """Validate several ``(kind, ids)`` references; see :func:`require_in_workspace`."""
    for kind, ids in refs:
        require_in_workspace(db, workspace_id, kind, ids)
