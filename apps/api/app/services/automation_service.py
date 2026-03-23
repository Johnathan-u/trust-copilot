"""Automate Everything: auto-trigger generation after parse, evaluate results, notify on needs_review.

Enqueues the same ``generate_answers`` job kind and worker path as ``POST /api/exports/generate/{questionnaire_id}``
(see ``export_service.enqueue_generate_answers_job``).
"""

import json
import logging

from sqlalchemy.orm import Session

from app.core.audit import persist_audit
from app.models import Answer, Job, JobStatus, Question, Questionnaire
from app.models.workspace import Workspace
from app.services.answer_evidence_policy import is_insufficient_answer_text

logger = logging.getLogger(__name__)


def _is_automation_enabled(session: Session, workspace_id: int) -> bool:
    ws = session.query(Workspace).filter(Workspace.id == workspace_id).first()
    return bool(ws and getattr(ws, "ai_automate_everything", False))


def maybe_auto_generate(session: Session, parse_job: Job, payload: dict) -> None:
    """After parse_questionnaire completes, auto-enqueue generate_answers if automation is enabled."""
    ws_id = parse_job.workspace_id
    if not _is_automation_enabled(session, ws_id):
        return

    qnr_id = payload.get("questionnaire_id")
    if not qnr_id:
        return

    qnr = session.query(Questionnaire).filter(
        Questionnaire.id == qnr_id, Questionnaire.workspace_id == ws_id
    ).first()
    if not qnr:
        return

    questions = session.query(Question).filter(Question.questionnaire_id == qnr_id).count()
    if questions == 0:
        return

    existing = session.query(Job).filter(
        Job.workspace_id == ws_id,
        Job.kind == "generate_answers",
        Job.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value]),
        Job.payload.contains(f'"questionnaire_id": {qnr_id}'),
    ).first()
    if existing:
        return

    gen_job = Job(
        workspace_id=ws_id,
        kind="generate_answers",
        status=JobStatus.QUEUED.value,
        payload=json.dumps({"questionnaire_id": qnr_id, "workspace_id": ws_id}),
    )
    session.add(gen_job)
    session.commit()
    session.refresh(gen_job)

    persist_audit(
        session, "automation.run_started",
        workspace_id=ws_id,
        resource_type="questionnaire",
        resource_id=qnr_id,
        details={"job_id": gen_job.id, "questionnaire": qnr.filename, "question_count": questions},
    )

    logger.info("automation: auto-enqueued generate_answers job=%s for qnr=%s ws=%s", gen_job.id, qnr_id, ws_id)


def evaluate_generation_result(session: Session, gen_job: Job, payload: dict) -> None:
    """After generate_answers completes, check for insufficient-evidence answers and notify if needed."""
    ws_id = gen_job.workspace_id
    if not _is_automation_enabled(session, ws_id):
        return

    qnr_id = payload.get("questionnaire_id")
    if not qnr_id:
        return

    qnr = session.query(Questionnaire).filter(
        Questionnaire.id == qnr_id, Questionnaire.workspace_id == ws_id
    ).first()
    if not qnr:
        return

    questions = session.query(Question).filter(Question.questionnaire_id == qnr_id).all()
    q_ids = [q.id for q in questions]
    if not q_ids:
        return

    answers = session.query(Answer).filter(Answer.question_id.in_(q_ids)).all()
    answer_map = {a.question_id: a for a in answers}

    insufficient_ids = []
    for q in questions:
        a = answer_map.get(q.id)
        if not a:
            insufficient_ids.append(q.id)
            continue
        if getattr(a, "status", None) == "insufficient_evidence":
            insufficient_ids.append(q.id)
            continue
        if is_insufficient_answer_text(a.text):
            insufficient_ids.append(q.id)
            continue
        if a.confidence == 0 and not (a.text or "").strip():
            insufficient_ids.append(q.id)

    total = len(questions)
    insufficient_count = len(insufficient_ids)
    qnr_name = qnr.filename or f"Questionnaire #{qnr_id}"
    link = f"/dashboard/review/{qnr_id}"

    if insufficient_count == 0:
        persist_audit(
            session, "automation.run_completed",
            workspace_id=ws_id,
            resource_type="questionnaire",
            resource_id=qnr_id,
            details={"questionnaire": qnr_name, "total": total, "status": "completed"},
        )
        logger.info("automation: qnr=%s completed, all %s questions have sufficient evidence", qnr_id, total)
    else:
        persist_audit(
            session, "automation.run_needs_review",
            workspace_id=ws_id,
            resource_type="questionnaire",
            resource_id=qnr_id,
            details={
                "questionnaire": qnr_name,
                "total": total,
                "insufficient_count": insufficient_count,
                "insufficient_question_ids": insufficient_ids[:50],
                "status": "needs_review",
            },
        )

        summary = (
            f"{qnr_name}: {insufficient_count} of {total} questions have insufficient evidence. "
            f"All answers are preserved. Please review."
        )

        _notify_needs_review(session, ws_id, qnr_name, insufficient_count, total, link)

        logger.info(
            "automation: qnr=%s needs_review, %s/%s insufficient",
            qnr_id, insufficient_count, total,
        )


def _notify_needs_review(
    session: Session,
    workspace_id: int,
    qnr_name: str,
    insufficient_count: int,
    total: int,
    link: str,
) -> None:
    """Send a single summary notification via in-app, email, and Slack."""
    title = f"Review needed: {qnr_name}"
    body = f"{insufficient_count} of {total} questions have insufficient evidence. All answers are preserved — please review and supplement."

    # In-app notification
    try:
        from app.services.in_app_notification_service import notify_admins
        notify_admins(session, workspace_id, title, body, category="warning", link=link)
    except Exception:
        pass

    # Email notification
    try:
        from app.services.notification_service import fire_notification
        ws = session.query(Workspace).filter(Workspace.id == workspace_id).first()
        ws_name = ws.name if ws else "Workspace"
        fire_notification(session, workspace_id, "questionnaire.generated", detail=body, workspace_name=ws_name)
    except Exception:
        pass
