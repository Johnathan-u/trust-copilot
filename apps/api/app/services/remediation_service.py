"""Remediation engine service (E3-14, E3-15, E3-16).

Playbook management, auto-ticket creation on control failure, and status tracking.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.remediation_playbook import RemediationPlaybook, RemediationTicket
from app.models.workspace_control import WorkspaceControl

logger = logging.getLogger(__name__)

BUILTIN_PLAYBOOKS = [
    {"control_key": "mfa_disabled", "title": "Re-enable MFA enforcement", "severity": "high", "sla_hours": 24,
     "steps": ["Identify affected users", "Enable MFA policy in IdP", "Verify MFA enrollment", "Collect compliance screenshot"],
     "evidence_needed": ["MFA policy screenshot", "User enrollment report"]},
    {"control_key": "stale_access_review", "title": "Complete access review", "severity": "medium", "sla_hours": 72,
     "steps": ["Pull current access list", "Review with team leads", "Remove stale access", "Document changes"],
     "evidence_needed": ["Access review spreadsheet", "Change log"]},
    {"control_key": "public_repo", "title": "Fix public repository exposure", "severity": "high", "sla_hours": 4,
     "steps": ["Identify exposed repo", "Switch to private", "Audit for secrets", "Rotate any exposed keys"],
     "evidence_needed": ["Repository settings screenshot", "Secret scan results"]},
    {"control_key": "missing_logging", "title": "Enable audit logging", "severity": "medium", "sla_hours": 48,
     "steps": ["Identify services without logging", "Enable CloudTrail/audit log", "Verify log delivery", "Set retention policy"],
     "evidence_needed": ["Logging configuration", "Sample log entry"]},
    {"control_key": "expired_policy", "title": "Update expired policy document", "severity": "low", "sla_hours": 168,
     "steps": ["Review current policy", "Update content", "Get approval from policy owner", "Publish updated version"],
     "evidence_needed": ["Updated policy document", "Approval email/ticket"]},
]


def create_playbook(db: Session, workspace_id: int, control_key: str, title: str, **kwargs) -> dict:
    pb = RemediationPlaybook(
        workspace_id=workspace_id,
        control_key=control_key,
        title=title,
        description=kwargs.get("description"),
        steps_json=json.dumps(kwargs.get("steps", [])),
        evidence_needed_json=json.dumps(kwargs.get("evidence_needed", [])),
        severity=kwargs.get("severity", "medium"),
        sla_hours=kwargs.get("sla_hours", 72),
        default_assignee_user_id=kwargs.get("default_assignee_user_id"),
    )
    db.add(pb)
    db.flush()
    return _serialize_playbook(pb)


def list_playbooks(db: Session, workspace_id: int) -> list[dict]:
    pbs = db.query(RemediationPlaybook).filter(
        RemediationPlaybook.workspace_id == workspace_id,
    ).order_by(RemediationPlaybook.created_at.desc()).all()
    return [_serialize_playbook(pb) for pb in pbs]


def get_builtin_playbooks() -> list[dict]:
    return BUILTIN_PLAYBOOKS


def seed_builtins(db: Session, workspace_id: int) -> dict:
    created = 0
    for bp in BUILTIN_PLAYBOOKS:
        existing = db.query(RemediationPlaybook).filter(
            RemediationPlaybook.workspace_id == workspace_id,
            RemediationPlaybook.control_key == bp["control_key"],
        ).first()
        if not existing:
            create_playbook(db, workspace_id, bp["control_key"], bp["title"],
                            steps=bp["steps"], evidence_needed=bp["evidence_needed"],
                            severity=bp["severity"], sla_hours=bp["sla_hours"])
            created += 1
    db.flush()
    return {"seeded": created}


def create_ticket(db: Session, workspace_id: int, title: str, **kwargs) -> dict:
    now = datetime.now(timezone.utc)
    sla = kwargs.get("sla_hours", 72)
    ticket = RemediationTicket(
        workspace_id=workspace_id,
        playbook_id=kwargs.get("playbook_id"),
        control_id=kwargs.get("control_id"),
        title=title,
        description=kwargs.get("description"),
        assignee_user_id=kwargs.get("assignee_user_id"),
        deadline=now + timedelta(hours=sla),
        affected_deal_ids_json=json.dumps(kwargs.get("affected_deal_ids", [])),
        evidence_needed_json=json.dumps(kwargs.get("evidence_needed", [])),
    )
    db.add(ticket)
    db.flush()
    return _serialize_ticket(ticket)


def auto_create_tickets(db: Session, workspace_id: int) -> dict:
    """Scan for failing controls and create tickets from matching playbooks."""
    controls = db.query(WorkspaceControl).filter(
        WorkspaceControl.workspace_id == workspace_id,
        WorkspaceControl.status == "not_implemented",
    ).all()
    playbooks = db.query(RemediationPlaybook).filter(
        RemediationPlaybook.workspace_id == workspace_id,
    ).all()
    pb_map = {pb.control_key: pb for pb in playbooks}
    created = []
    for wc in controls:
        key = wc.custom_name or f"control-{wc.id}"
        if key in pb_map:
            pb = pb_map[key]
            existing = db.query(RemediationTicket).filter(
                RemediationTicket.workspace_id == workspace_id,
                RemediationTicket.control_id == wc.id,
                RemediationTicket.status.in_(["open", "in_progress"]),
            ).first()
            if not existing:
                ticket = create_ticket(db, workspace_id, pb.title,
                                       playbook_id=pb.id, control_id=wc.id,
                                       description=pb.description,
                                       assignee_user_id=pb.default_assignee_user_id,
                                       sla_hours=pb.sla_hours or 72,
                                       evidence_needed=json.loads(pb.evidence_needed_json or "[]"))
                created.append(ticket)
    db.flush()
    return {"created": len(created), "tickets": created}


def list_tickets(db: Session, workspace_id: int, status: str | None = None) -> list[dict]:
    q = db.query(RemediationTicket).filter(RemediationTicket.workspace_id == workspace_id)
    if status:
        q = q.filter(RemediationTicket.status == status)
    return [_serialize_ticket(t) for t in q.order_by(RemediationTicket.created_at.desc()).all()]


def update_ticket_status(db: Session, ticket_id: int, status: str) -> dict | None:
    ticket = db.query(RemediationTicket).filter(RemediationTicket.id == ticket_id).first()
    if not ticket:
        return None
    ticket.status = status
    if status in ("verified", "closed"):
        ticket.resolved_at = datetime.now(timezone.utc)
    db.flush()
    return _serialize_ticket(ticket)


def get_ticket_stats(db: Session, workspace_id: int) -> dict:
    tickets = db.query(RemediationTicket).filter(RemediationTicket.workspace_id == workspace_id).all()
    by_status = {}
    overdue = 0
    now = datetime.now(timezone.utc)
    for t in tickets:
        by_status[t.status] = by_status.get(t.status, 0) + 1
        if t.deadline and t.status in ("open", "in_progress"):
            deadline = t.deadline.replace(tzinfo=timezone.utc) if t.deadline.tzinfo is None else t.deadline
            if now > deadline:
                overdue += 1
    return {"total": len(tickets), "by_status": by_status, "overdue": overdue}


def _serialize_playbook(pb: RemediationPlaybook) -> dict:
    return {
        "id": pb.id,
        "workspace_id": pb.workspace_id,
        "control_key": pb.control_key,
        "title": pb.title,
        "description": pb.description,
        "steps": json.loads(pb.steps_json or "[]"),
        "evidence_needed": json.loads(pb.evidence_needed_json or "[]"),
        "severity": pb.severity,
        "sla_hours": pb.sla_hours,
    }


def _serialize_ticket(t: RemediationTicket) -> dict:
    return {
        "id": t.id,
        "workspace_id": t.workspace_id,
        "playbook_id": t.playbook_id,
        "control_id": t.control_id,
        "title": t.title,
        "status": t.status,
        "assignee_user_id": t.assignee_user_id,
        "deadline": t.deadline.isoformat() if t.deadline else None,
        "affected_deal_ids": json.loads(t.affected_deal_ids_json or "[]"),
        "evidence_needed": json.loads(t.evidence_needed_json or "[]"),
        "external_ticket_id": t.external_ticket_id,
        "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "linked_evidence_ids": json.loads(getattr(t, "linked_evidence_ids_json", None) or "[]"),
    }
