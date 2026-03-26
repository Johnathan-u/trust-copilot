"""Remediation playbook model (E3-14)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base

REMEDIATION_STATUSES = ("open", "in_progress", "evidence_submitted", "verified", "closed")


class RemediationPlaybook(Base):
    __tablename__ = "remediation_playbooks"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    control_key = Column(String(128), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    steps_json = Column(Text, nullable=True)  # JSON array of step objects
    evidence_needed_json = Column(Text, nullable=True)  # JSON array
    default_assignee_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    severity = Column(String(32), default="medium")
    sla_hours = Column(Integer, nullable=True, default=72)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class RemediationTicket(Base):
    __tablename__ = "remediation_tickets"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    playbook_id = Column(Integer, ForeignKey("remediation_playbooks.id", ondelete="SET NULL"), nullable=True)
    control_id = Column(Integer, ForeignKey("workspace_controls.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="open")
    assignee_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    deadline = Column(DateTime, nullable=True)
    affected_deal_ids_json = Column(Text, nullable=True)  # JSON array
    evidence_needed_json = Column(Text, nullable=True)
    external_ticket_id = Column(String(255), nullable=True)  # Jira/Linear ID
    external_ticket_url = Column(String(512), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
