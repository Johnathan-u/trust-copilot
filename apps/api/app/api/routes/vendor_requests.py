"""Outbound vendor requests and invitation lifecycle."""

import re

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth_deps import require_session
from app.core.database import get_db
from app.models import Questionnaire, VendorRequest
from app.models.vendor_request import VENDOR_REQUEST_STATUSES
from app.services import vendor_request_service as service

router = APIRouter(prefix="/vendor-requests", tags=["vendor-requests"])


def _current_permission(permission: str):
    async def dependency(request: Request, db: Session = Depends(get_db)) -> dict:
        session = await require_session(request, db)
        if session.get("email") == "api-key":
            session = {
                **session,
                "_api_key_hash": service.digest(request.headers["Authorization"][7:].strip()),
            }
        return service.current_permission(db, session, permission)

    return dependency


require_vendor_admin = _current_permission("can_admin")
require_vendor_review = _current_permission("can_review")


class VendorRequestCreate(BaseModel):
    vendor_email: str = Field(max_length=255)
    questionnaire_id: int | None = Field(default=None, gt=0)
    message: str | None = Field(default=None, max_length=10000)
    expires_in_days: int = Field(default=7, ge=1, le=90)

    @field_validator("vendor_email")
    @classmethod
    def validate_vendor_email(cls, value: str) -> str:
        if not value.isascii():
            raise ValueError("Enter a valid email address")
        value = value.strip(" ").lower()
        atom = r"[a-z0-9!#$%&'*+/=?^_`{|}~-]+"
        label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
        if not re.fullmatch(rf"{atom}(?:\.{atom})*@(?:{label}\.)+[a-z]{{2,63}}", value):
            raise ValueError("Enter a valid email address")
        if len(value.split("@", 1)[0]) > 64:
            raise ValueError("Enter a valid email address")
        return value

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("Message contains an unsupported character")
        return value


class VendorRequestUpdate(BaseModel):
    status: str | None = None


def _require_workspace_questionnaire(db: Session, ws: int, questionnaire_id: int) -> int:
    row = (
        db.query(Questionnaire.id)
        .filter(
            Questionnaire.id == questionnaire_id,
            Questionnaire.workspace_id == ws,
            Questionnaire.deleted_at.is_(None),
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    return questionnaire_id


@router.get("/")
@router.get("")
def list_vendor_requests(
    session: dict = Depends(require_vendor_review), db: Session = Depends(get_db)
):
    """List the current workspace's vendor requests without changing their state."""
    rows = (
        db.query(VendorRequest)
        .filter(VendorRequest.workspace_id == session["workspace_id"])
        .order_by(VendorRequest.created_at.desc())
        .all()
    )
    return [service.serialize(row) for row in rows]


@router.post("/")
@router.post("")
def create_vendor_request(
    body: VendorRequestCreate,
    session: dict = Depends(require_vendor_admin),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None),
):
    """Create an expiring invitation. Its raw link is returned once."""
    ws = session["workspace_id"]
    if body.questionnaire_id is not None:
        _require_workspace_questionnaire(db, ws, body.questionnaire_id)
    try:
        return service.create_request(
            db,
            ws,
            body.vendor_email,
            body.questionnaire_id,
            body.message,
            body.expires_in_days,
            idempotency_key,
            session,
        )
    except IntegrityError:
        db.rollback()
        if body.questionnaire_id is None:
            raise
        raise HTTPException(status_code=404, detail="Questionnaire not found") from None


@router.patch("/{request_id}")
def update_vendor_request(
    request_id: int,
    body: VendorRequestUpdate,
    session: dict = Depends(require_vendor_admin),
    db: Session = Depends(get_db),
):
    """Update progress. Completion requires the vendor's submitted response."""
    row = service.scoped_request(db, session["workspace_id"], request_id, lock=True)
    if body.status is not None:
        if body.status == "completed":
            raise HTTPException(
                status_code=409, detail="Completion requires a submitted vendor response."
            )
        if body.status not in VENDOR_REQUEST_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        if row.submitted_at is not None or row.revoked_at is not None:
            raise HTTPException(
                status_code=409, detail="This request no longer accepts progress changes."
            )
        row.status = body.status
        service.audit(db, row, "progress_updated", session)
    db.commit()
    db.refresh(row)
    return service.serialize(row)


@router.post("/{request_id}/send")
def send_vendor_request(
    request_id: int,
    session: dict = Depends(require_vendor_admin),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None),
):
    """Send an invitation with a durable delivery outcome and replay protection."""
    return service.send(db, session["workspace_id"], request_id, idempotency_key, False, session)


@router.post("/{request_id}/resend")
def resend_vendor_request(
    request_id: int,
    session: dict = Depends(require_vendor_admin),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None),
):
    """Rotate the previous link and explicitly send another invitation."""
    return service.send(db, session["workspace_id"], request_id, idempotency_key, True, session)


@router.post("/{request_id}/revoke")
def revoke_vendor_request(
    request_id: int, session: dict = Depends(require_vendor_admin), db: Session = Depends(get_db)
):
    """Revoke public access to this request's invitation."""
    return service.revoke(db, session["workspace_id"], request_id, session)
