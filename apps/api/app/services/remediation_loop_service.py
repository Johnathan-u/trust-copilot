"""Post-remediation evidence, safe auto-remediation, impact analysis (E3-17, E3-18, E3-19)."""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.control_evidence_link import ControlEvidenceLink
from app.models.questionnaire import Question
from app.models.remediation_audit import RemediationAuditEvent, RemediationAutomationSetting
from app.models.remediation_playbook import RemediationTicket
from app.models.workspace_control import WorkspaceControl

logger = logging.getLogger(__name__)

AUTOMATION_CATALOG = {
    "mfa_re_enable": {
        "title": "Re-enable MFA policy (IdP)",
        "risk": "low",
        "description": "Calls IdP admin API to enforce MFA (mock in dev).",
    },
    "policy_review_stamp": {
        "title": "Stamp policy review date",
        "risk": "low",
        "description": "Updates internal policy last-reviewed metadata (mock).",
    },
    "public_repo_private": {
        "title": "Set repository to private",
        "risk": "medium",
        "description": "GitHub API: set repo visibility (mock).",
    },
}


def _audit(
    db: Session,
    workspace_id: int,
    action: str,
    actor_user_id: int | None = None,
    ticket_id: int | None = None,
    dry_run: bool = False,
    payload: dict | None = None,
) -> None:
    db.add(
        RemediationAuditEvent(
            workspace_id=workspace_id,
            ticket_id=ticket_id,
            action=action,
            actor_user_id=actor_user_id,
            dry_run=dry_run,
            payload_json=json.dumps(payload) if payload else None,
        )
    )


def submit_post_remediation_evidence(
    db: Session,
    ticket_id: int,
    evidence_ids: list[int],
    actor_user_id: int | None = None,
    bump_control_to: str | None = "implemented",
) -> dict | None:
    """E3-17: Attach evidence to ticket, link to control, optionally bump control status."""
    ticket = db.query(RemediationTicket).filter(RemediationTicket.id == ticket_id).first()
    if not ticket:
        return None
    existing = json.loads(ticket.linked_evidence_ids_json or "[]")
    merged = list(dict.fromkeys(existing + evidence_ids))
    ticket.linked_evidence_ids_json = json.dumps(merged)
    ticket.status = "evidence_submitted"
    if ticket.control_id and bump_control_to:
        wc = db.query(WorkspaceControl).filter(WorkspaceControl.id == ticket.control_id).first()
        if wc:
            wc.status = bump_control_to
            wc.verified_at = datetime.now(timezone.utc)
    for eid in evidence_ids:
        if ticket.control_id:
            link = (
                db.query(ControlEvidenceLink)
                .filter(
                    ControlEvidenceLink.control_id == ticket.control_id,
                    ControlEvidenceLink.evidence_id == eid,
                )
                .first()
            )
            if not link:
                db.add(ControlEvidenceLink(control_id=ticket.control_id, evidence_id=eid, verified=True))
    _audit(db, ticket.workspace_id, "post_remediation_evidence", actor_user_id, ticket_id, False, {"evidence_ids": evidence_ids})
    db.flush()
    from app.services import remediation_service as rs

    return rs._serialize_ticket(ticket)


def analyze_remediation_impact(db: Session, ticket_id: int) -> dict | None:
    """E3-19: Downstream impact before executing remediation."""
    ticket = db.query(RemediationTicket).filter(RemediationTicket.id == ticket_id).first()
    if not ticket:
        return None
    control = None
    if ticket.control_id:
        control = db.query(WorkspaceControl).filter(WorkspaceControl.id == ticket.control_id).first()
    deal_ids = json.loads(ticket.affected_deal_ids_json or "[]")
    answers_upgradable: list[dict] = []
    if ticket.workspace_id:
        from app.models.questionnaire import Questionnaire

        qids = [q.id for q in db.query(Questionnaire).filter(Questionnaire.workspace_id == ticket.workspace_id).all()]
        for qn_id in qids[:50]:
            for q in db.query(Question).filter(Question.questionnaire_id == qn_id).limit(100).all():
                ans = db.query(Answer).filter(Answer.question_id == q.id).order_by(Answer.created_at.desc()).first()
                if ans and ans.status in ("draft", "flagged") and (ans.confidence or 0) < 70:
                    answers_upgradable.append({"answer_id": ans.id, "question_id": q.id, "reason": "may_re_review_after_control_fix"})
                    if len(answers_upgradable) >= 20:
                        break
            if len(answers_upgradable) >= 20:
                break
    return {
        "ticket_id": ticket.id,
        "control": {"id": control.id, "current_status": control.status, "would_move_to": "implemented"} if control else None,
        "affected_deal_ids": deal_ids,
        "deals_risk_score_may_improve": len(deal_ids),
        "answers_may_upgrade_confidence": answers_upgradable[:20],
        "summary": "Closing this ticket with verified evidence typically improves deal risk scores linked to this control.",
    }


def list_automations(db: Session, workspace_id: int) -> list[dict]:
    settings = {
        row.automation_key: row.enabled
        for row in db.query(RemediationAutomationSetting).filter(
            RemediationAutomationSetting.workspace_id == workspace_id
        ).all()
    }
    out = []
    for key, meta in AUTOMATION_CATALOG.items():
        out.append({**meta, "automation_key": key, "enabled": settings.get(key, False)})
    return out


def set_automation_enabled(db: Session, workspace_id: int, automation_key: str, enabled: bool) -> dict:
    if automation_key not in AUTOMATION_CATALOG:
        return {"error": f"Unknown automation: {automation_key}"}
    row = (
        db.query(RemediationAutomationSetting)
        .filter(
            RemediationAutomationSetting.workspace_id == workspace_id,
            RemediationAutomationSetting.automation_key == automation_key,
        )
        .first()
    )
    if row:
        row.enabled = enabled
    else:
        row = RemediationAutomationSetting(workspace_id=workspace_id, automation_key=automation_key, enabled=enabled)
        db.add(row)
    db.flush()
    return {"automation_key": automation_key, "enabled": enabled}


def run_safe_automation(
    db: Session,
    workspace_id: int,
    automation_key: str,
    ticket_id: int | None = None,
    dry_run: bool = True,
    actor_user_id: int | None = None,
) -> dict:
    """E3-18: Execute or simulate low-risk automation with full audit trail."""
    if automation_key not in AUTOMATION_CATALOG:
        return {"error": f"Unknown automation: {automation_key}"}
    if dry_run:
        _audit(db, workspace_id, f"automation_dry_run:{automation_key}", actor_user_id, ticket_id, True, {"automation_key": automation_key})
        db.flush()
        return {
            "dry_run": True,
            "automation_key": automation_key,
            "would_execute": AUTOMATION_CATALOG[automation_key]["title"],
            "simulated_result": "success",
        }
    setting = (
        db.query(RemediationAutomationSetting)
        .filter(
            RemediationAutomationSetting.workspace_id == workspace_id,
            RemediationAutomationSetting.automation_key == automation_key,
        )
        .first()
    )
    if not setting or not setting.enabled:
        return {"error": "Automation not enabled for this workspace. Opt in via settings before live execution."}
    _audit(db, workspace_id, f"automation_execute:{automation_key}", actor_user_id, ticket_id, False, {"automation_key": automation_key})
    db.flush()
    return {
        "dry_run": False,
        "automation_key": automation_key,
        "result": "completed",
        "message": "Mock execution completed; integrate provider API for production.",
    }


def list_audit_events(db: Session, workspace_id: int, limit: int = 100) -> list[dict]:
    rows = (
        db.query(RemediationAuditEvent)
        .filter(RemediationAuditEvent.workspace_id == workspace_id)
        .order_by(RemediationAuditEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "action": r.action,
            "ticket_id": r.ticket_id,
            "dry_run": r.dry_run,
            "payload": json.loads(r.payload_json) if r.payload_json else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
