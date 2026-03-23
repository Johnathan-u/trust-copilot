"""Phase 5: Compliance audit history, actor resolution, workspace staleness settings; Phase 6: audit export."""

import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_can_export, require_can_review
from app.core.database import get_db
from app.models import AuditEvent, User, Workspace, WorkspaceMember

router = APIRouter(prefix="/compliance", tags=["compliance-audit"])

COMPLIANCE_ACTION_PREFIX = "compliance."


def _audit_rows(db: Session, workspace_id: int, limit: int) -> list[dict]:
    rows = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.workspace_id == workspace_id,
            AuditEvent.action.like(f"{COMPLIANCE_ACTION_PREFIX}%"),
        )
        .order_by(AuditEvent.occurred_at.desc())
        .limit(limit)
        .all()
    )
    out = []
    for r in rows:
        action_short = r.action[len(COMPLIANCE_ACTION_PREFIX):] if r.action.startswith(COMPLIANCE_ACTION_PREFIX) else r.action
        try:
            details = json.loads(r.details) if r.details else None
        except (TypeError, ValueError):
            details = None
        actor = r.email or (f"User #{r.user_id}" if r.user_id is not None else "System")
        out.append({
            "id": r.id,
            "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
            "action": action_short,
            "actor": actor,
            "user_id": r.user_id,
            "email": r.email,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "details": details,
        })
    return out


@router.get("/audit-history", response_model=list)
def get_compliance_audit_history(
    limit: int = Query(200, ge=1, le=500),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """List recent compliance audit events (evidence/control verification, mapping confirm/override)."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    return _audit_rows(db, ws, limit)


@router.get("/audit-history/export")
def export_compliance_audit_history(
    format: str = Query("json", description="csv or json"),
    limit: int = Query(1000, ge=1, le=5000),
    session: dict = Depends(require_can_export),
    db: Session = Depends(get_db),
):
    """Export compliance audit history as CSV or JSON. Requires export permission."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    data = _audit_rows(db, ws, limit)
    if (format or "").lower() == "csv":
        if not data:
            body = "id,occurred_at,action,actor,user_id,email,resource_type,resource_id,details\n"
        else:
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow(["id", "occurred_at", "action", "actor", "user_id", "email", "resource_type", "resource_id", "details"])
            for row in data:
                details_str = json.dumps(row["details"]) if row.get("details") is not None else ""
                writer.writerow([
                    row.get("id"),
                    row.get("occurred_at"),
                    row.get("action"),
                    row.get("actor"),
                    row.get("user_id"),
                    row.get("email"),
                    row.get("resource_type"),
                    row.get("resource_id"),
                    details_str,
                ])
            body = out.getvalue()
        return Response(
            content=body,
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="compliance-audit.csv"'},
        )
    body = json.dumps(data, default=str)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="compliance-audit.json"'},
    )


@router.get("/actors", response_model=dict)
def get_actors(
    user_ids: str = Query(..., description="Comma-separated user IDs"),
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Resolve user IDs to display name/email for workspace members. Safe fallback if user not found."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    ids = []
    for s in user_ids.split(","):
        s = s.strip()
        if s:
            try:
                ids.append(int(s))
            except ValueError:
                pass
    if not ids:
        return {}
    members = (
        db.query(WorkspaceMember.user_id, User.email, User.display_name)
        .join(User, WorkspaceMember.user_id == User.id)
        .filter(
            WorkspaceMember.workspace_id == ws,
            WorkspaceMember.user_id.in_(ids),
        )
        .all()
    )
    result = {}
    for user_id, email, display_name in members:
        key = str(user_id)
        result[key] = {
            "user_id": user_id,
            "email": email or "",
            "display_name": (display_name or email or f"User #{user_id}").strip(),
        }
    return result


@router.get("/settings", response_model=dict)
def get_compliance_settings(
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """Get workspace-level compliance settings (evidence staleness thresholds in days)."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    row = db.query(Workspace).filter(Workspace.id == ws).first()
    if not row:
        return {"evidence_stale_verified_days": 365, "evidence_stale_unverified_days": 90, "compliance_webhook_url": None}
    return {
        "evidence_stale_verified_days": row.evidence_stale_verified_days if row.evidence_stale_verified_days is not None else 365,
        "evidence_stale_unverified_days": row.evidence_stale_unverified_days if row.evidence_stale_unverified_days is not None else 90,
        "compliance_webhook_url": row.compliance_webhook_url,
    }


class ComplianceSettingsBody(BaseModel):
    evidence_stale_verified_days: int | None = None
    evidence_stale_unverified_days: int | None = None
    compliance_webhook_url: str | None = None


@router.patch("/settings", response_model=dict)
def update_compliance_settings(
    body: ComplianceSettingsBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Update workspace-level compliance settings (staleness thresholds). Admin only."""
    ws = session.get("workspace_id")
    if not ws:
        raise HTTPException(status_code=403, detail="No workspace")
    row = db.query(Workspace).filter(Workspace.id == ws).first()
    if not row:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if body.evidence_stale_verified_days is not None:
        if body.evidence_stale_verified_days < 1 or body.evidence_stale_verified_days > 3650:
            raise HTTPException(status_code=400, detail="evidence_stale_verified_days must be between 1 and 3650")
        row.evidence_stale_verified_days = body.evidence_stale_verified_days
    if body.evidence_stale_unverified_days is not None:
        if body.evidence_stale_unverified_days < 1 or body.evidence_stale_unverified_days > 3650:
            raise HTTPException(status_code=400, detail="evidence_stale_unverified_days must be between 1 and 3650")
        row.evidence_stale_unverified_days = body.evidence_stale_unverified_days
    if body.compliance_webhook_url is not None:
        row.compliance_webhook_url = body.compliance_webhook_url.strip() or None
    db.commit()
    db.refresh(row)
    return {
        "evidence_stale_verified_days": row.evidence_stale_verified_days if row.evidence_stale_verified_days is not None else 365,
        "evidence_stale_unverified_days": row.evidence_stale_unverified_days if row.evidence_stale_unverified_days is not None else 90,
        "compliance_webhook_url": row.compliance_webhook_url,
    }
