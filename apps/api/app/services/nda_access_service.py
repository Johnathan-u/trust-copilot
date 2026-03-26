"""NDA-gated access request service (P1-65)."""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.nda_access_request import NDA_REQUEST_STATUSES, NdaAccessRequest

logger = logging.getLogger(__name__)

DEFAULT_ACCESS_DAYS = 30


def request_access(
    db: Session,
    workspace_id: int,
    requester_name: str,
    requester_email: str,
    nda_accepted: bool,
    requester_company: str | None = None,
    purpose: str | None = None,
) -> dict:
    """Create a new NDA-gated access request."""
    if not nda_accepted:
        return {"error": "NDA must be accepted to request access"}

    req = NdaAccessRequest(
        workspace_id=workspace_id,
        requester_name=requester_name,
        requester_email=requester_email,
        requester_company=requester_company,
        purpose=purpose,
        nda_accepted=True,
        nda_accepted_at=datetime.now(timezone.utc),
        status="pending",
    )
    db.add(req)
    db.flush()
    return _serialize(req)


def approve_request(
    db: Session,
    request_id: int,
    approved_by_user_id: int,
    access_days: int = DEFAULT_ACCESS_DAYS,
) -> dict | None:
    """Approve a pending request, generating a time-limited access token."""
    req = db.query(NdaAccessRequest).filter(NdaAccessRequest.id == request_id).first()
    if not req:
        return None

    req.status = "approved"
    req.approved_by_user_id = approved_by_user_id
    req.access_token = secrets.token_urlsafe(32)
    req.expires_at = datetime.now(timezone.utc) + timedelta(days=access_days)
    db.flush()
    return _serialize(req)


def reject_request(db: Session, request_id: int) -> dict | None:
    """Reject a pending access request."""
    req = db.query(NdaAccessRequest).filter(NdaAccessRequest.id == request_id).first()
    if not req:
        return None
    req.status = "rejected"
    db.flush()
    return _serialize(req)


def revoke_access(db: Session, request_id: int) -> dict | None:
    """Revoke a previously approved access."""
    req = db.query(NdaAccessRequest).filter(NdaAccessRequest.id == request_id).first()
    if not req:
        return None
    req.status = "revoked"
    req.revoked_at = datetime.now(timezone.utc)
    db.flush()
    return _serialize(req)


def validate_access_token(db: Session, token: str) -> dict:
    """Validate an access token and return access details."""
    req = db.query(NdaAccessRequest).filter(NdaAccessRequest.access_token == token).first()
    if not req:
        return {"valid": False, "reason": "Token not found"}
    if req.status != "approved":
        return {"valid": False, "reason": f"Access is {req.status}"}
    if req.expires_at:
        expires = req.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            return {"valid": False, "reason": "Token expired"}
    return {
        "valid": True,
        "workspace_id": req.workspace_id,
        "requester_name": req.requester_name,
        "requester_email": req.requester_email,
        "expires_at": req.expires_at.isoformat() if req.expires_at else None,
    }


def list_requests(
    db: Session,
    workspace_id: int,
    status: str | None = None,
) -> list[dict]:
    """List access requests for a workspace."""
    q = db.query(NdaAccessRequest).filter(NdaAccessRequest.workspace_id == workspace_id)
    if status:
        q = q.filter(NdaAccessRequest.status == status)
    q = q.order_by(NdaAccessRequest.created_at.desc())
    return [_serialize(r) for r in q.all()]


def _serialize(req: NdaAccessRequest) -> dict:
    return {
        "id": req.id,
        "workspace_id": req.workspace_id,
        "requester_name": req.requester_name,
        "requester_email": req.requester_email,
        "requester_company": req.requester_company,
        "purpose": req.purpose,
        "nda_accepted": req.nda_accepted,
        "nda_accepted_at": req.nda_accepted_at.isoformat() if req.nda_accepted_at else None,
        "status": req.status,
        "access_token": req.access_token,
        "expires_at": req.expires_at.isoformat() if req.expires_at else None,
        "created_at": req.created_at.isoformat() if req.created_at else None,
    }
