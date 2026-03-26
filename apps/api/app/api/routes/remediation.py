"""Remediation engine API (E3-14, E3-15, E3-16)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import remediation_service as svc
from app.services import remediation_loop_service as loop_svc

router = APIRouter(prefix="/remediation", tags=["remediation"])


class CreatePlaybookBody(BaseModel):
    control_key: str
    title: str
    description: str | None = None
    steps: list[str] | None = None
    evidence_needed: list[str] | None = None
    severity: str = "medium"
    sla_hours: int = 72


class CreateTicketBody(BaseModel):
    title: str
    description: str | None = None
    control_id: int | None = None
    playbook_id: int | None = None
    assignee_user_id: int | None = None
    sla_hours: int = 72
    affected_deal_ids: list[int] | None = None
    evidence_needed: list[str] | None = None


class UpdateStatusBody(BaseModel):
    status: str


class SubmitEvidenceBody(BaseModel):
    evidence_ids: list[int]
    bump_control_to: str | None = "implemented"


class AutomationEnableBody(BaseModel):
    enabled: bool


class RunAutomationBody(BaseModel):
    dry_run: bool = True
    ticket_id: int | None = None


@router.post("/playbooks")
async def create_playbook(body: CreatePlaybookBody, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = svc.create_playbook(db, session["workspace_id"], body.control_key, body.title,
                                  description=body.description, steps=body.steps,
                                  evidence_needed=body.evidence_needed, severity=body.severity,
                                  sla_hours=body.sla_hours)
    db.commit()
    return result


@router.get("/playbooks")
async def list_playbooks(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"playbooks": svc.list_playbooks(db, session["workspace_id"])}


@router.get("/playbooks/builtins")
async def builtins(session: dict = Depends(require_session)):
    return {"builtins": svc.get_builtin_playbooks()}


@router.post("/playbooks/seed")
async def seed(session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = svc.seed_builtins(db, session["workspace_id"])
    db.commit()
    return result


@router.post("/tickets")
async def create_ticket(body: CreateTicketBody, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_none=True)
    result = svc.create_ticket(db, session["workspace_id"], **data)
    db.commit()
    return result


@router.get("/tickets")
async def list_tickets(status: str | None = Query(None), session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"tickets": svc.list_tickets(db, session["workspace_id"], status)}


@router.patch("/tickets/{ticket_id}/status")
async def update_status(ticket_id: int, body: UpdateStatusBody, session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = svc.update_ticket_status(db, ticket_id, body.status)
    if not result:
        raise HTTPException(status_code=404)
    db.commit()
    return result


@router.post("/auto-create")
async def auto_create(session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    result = svc.auto_create_tickets(db, session["workspace_id"])
    db.commit()
    return result


@router.get("/stats")
async def stats(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return svc.get_ticket_stats(db, session["workspace_id"])


@router.post("/tickets/{ticket_id}/evidence")
async def submit_evidence(
    ticket_id: int,
    body: SubmitEvidenceBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = loop_svc.submit_post_remediation_evidence(
        db, ticket_id, body.evidence_ids, session.get("user_id"), body.bump_control_to
    )
    if not result:
        raise HTTPException(status_code=404)
    db.commit()
    return result


@router.get("/tickets/{ticket_id}/impact")
async def ticket_impact(ticket_id: int, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    result = loop_svc.analyze_remediation_impact(db, ticket_id)
    if not result:
        raise HTTPException(status_code=404)
    return result


@router.get("/automations")
async def list_automations(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return {"automations": loop_svc.list_automations(db, session["workspace_id"])}


@router.post("/automations/{automation_key}/enable")
async def enable_automation(
    automation_key: str,
    body: AutomationEnableBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = loop_svc.set_automation_enabled(db, session["workspace_id"], automation_key, body.enabled)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    db.commit()
    return result


@router.post("/automations/{automation_key}/run")
async def run_automation(
    automation_key: str,
    body: RunAutomationBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    result = loop_svc.run_safe_automation(
        db, session["workspace_id"], automation_key, body.ticket_id, body.dry_run, session.get("user_id")
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    db.commit()
    return result


@router.get("/audit")
async def audit_log(session: dict = Depends(require_can_admin), db: Session = Depends(get_db)):
    return {"events": loop_svc.list_audit_events(db, session["workspace_id"])}
