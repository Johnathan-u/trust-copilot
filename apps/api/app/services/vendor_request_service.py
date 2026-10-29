"""Durable outbound grants and explicit delivery outcomes."""

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core import idempotency
from app.core.auth_deps import _resolve_permission
from app.core.roles import BUILTIN_ROLES
from app.core.config import get_settings
from app.models import ApiKey, AuditEvent, CustomRole, Questionnaire, VendorRequest, WorkspaceMember
from app.services import email_service

INVALID_LINK = "This link is invalid or has expired."


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def grant_expiry(row: VendorRequest) -> datetime | None:
    if row.expires_at is not None:
        return aware(row.expires_at)
    # A read-only compatibility policy bounds pre-migration raw grants too. It
    # does not backfill invented expiry/delivery/submission provenance.
    return aware(row.created_at) + timedelta(days=7) if row.created_at else None


def status(row: VendorRequest) -> str:
    if row.submitted_at is not None:
        return "completed"
    if row.revoked_at is not None:
        return "revoked"
    if grant_expiry(row) is None or grant_expiry(row) <= now():
        return "expired"
    return row.status if row.status in ("pending", "in_progress") else "pending"


def serialize(row: VendorRequest, token: str | None = None) -> dict:
    result = {
        "schema_version": "1",
        "id": row.id,
        "workspace_id": row.workspace_id,
        "vendor_email": row.vendor_email,
        "questionnaire_id": row.questionnaire_id,
        "message": row.message,
        "status": status(row),
        "link_token": token,
        "delivery_status": row.delivery_status or "unknown",
        "last_delivery_error": row.last_delivery_error,
    }
    for field in ("created_at", "expires_at", "revoked_at", "last_delivery_at", "submitted_at"):
        value = getattr(row, field)
        result[field] = aware(value).isoformat() if value else None
    if token is not None:
        result["share_url"] = f"/vendor-response?token={token}"
    return result


def scoped_request(
    db: Session, workspace_id: int, request_id: int, lock: bool = False
) -> VendorRequest:
    query = db.query(VendorRequest).filter(
        VendorRequest.id == request_id, VendorRequest.workspace_id == workspace_id
    )
    if lock:
        query = query.with_for_update().populate_existing()
    row = query.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Request not found")
    return row


def audit(db: Session, row: VendorRequest, action: str, actor: dict | None = None) -> None:
    db.add(
        AuditEvent(
            action=f"vendor_request.{action}",
            workspace_id=row.workspace_id,
            user_id=(actor or {}).get("user_id"),
            resource_type="vendor_request",
            resource_id=str(row.id),
        )
    )


def current_permission(db: Session, actor: dict, permission: str = "can_admin") -> dict:
    """Keep actor and role authorization stable until this write transaction commits."""
    workspace_id = actor.get("workspace_id")
    if actor.get("user_id") is not None:
        principal = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == actor["user_id"],
            )
            .with_for_update(read=True)
            .populate_existing()
            .first()
        )
        valid = principal is not None and not principal.suspended
    elif actor.get("email") == "api-key" and actor.get("_api_key_hash"):
        principal = (
            db.query(ApiKey)
            .filter(
                ApiKey.workspace_id == workspace_id,
                ApiKey.key_hash == actor["_api_key_hash"],
            )
            .with_for_update(read=True)
            .populate_existing()
            .first()
        )
        valid = principal is not None and (
            principal.expires_at is None or aware(principal.expires_at) > now()
        )
    else:
        principal, valid = None, False
    if not valid:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    role = principal.role
    if role in BUILTIN_ROLES:
        permitted = _resolve_permission(role, permission, workspace_id, db)
    else:
        custom = (
            db.query(CustomRole)
            .filter(
                CustomRole.workspace_id == workspace_id,
                CustomRole.name == role,
            )
            .with_for_update(read=True)
            .populate_existing()
            .first()
        )
        permitted = custom is not None and bool(getattr(custom, permission, False))
    if not permitted:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return {**actor, "role": role}


def rotate(row: VendorRequest, days: int = 7) -> str:
    token = secrets.token_urlsafe(32)
    row.link_token_hash = digest(token)
    row.link_token = None
    row.expires_at = now() + timedelta(days=days)
    return token


def _claim(db: Session, key: str, fingerprint: str | None = None):
    if not key:
        return None, None
    cached = idempotency.get(db, key)
    if cached:
        if fingerprint is not None and cached[1].get("input_digest") != fingerprint:
            raise HTTPException(
                status_code=409, detail="This request key was already used for different input."
            )
        return None, cached[1]
    owner = idempotency.claim(db, key)
    if owner is None:
        raise HTTPException(
            status_code=409, detail="Request in progress; retry with the same request key."
        )
    return owner, None


def _settle(
    db: Session, key: str, owner: str | None, row: VendorRequest, fingerprint: str | None = None
):
    if key:
        # Persist only resource identity and input fingerprint, never the raw bearer grant.
        idempotency.set(
            db,
            key,
            200,
            {"request_id": row.id, "input_digest": fingerprint},
            owner=owner,
            commit=False,
        )
    db.commit()


def create_request(
    db: Session,
    workspace_id: int,
    email: str,
    questionnaire_id: int | None,
    message: str | None,
    days: int,
    client_key: str | None,
    actor: dict,
) -> dict:
    key = idempotency.scoped_key(workspace_id, "vendor-create", "new", client_key)
    fingerprint = digest(json.dumps([email, questionnaire_id, message, days], ensure_ascii=True))
    owner, cached = _claim(db, key, fingerprint)
    try:
        actor = current_permission(db, actor)
        if cached:
            return serialize(scoped_request(db, workspace_id, cached["request_id"]))
        if questionnaire_id is not None:
            # claim() commits; acquire the reference lock afterwards, in the write transaction.
            questionnaire = (
                db.query(Questionnaire)
                .filter(
                    Questionnaire.id == questionnaire_id,
                    Questionnaire.workspace_id == workspace_id,
                    Questionnaire.deleted_at.is_(None),
                )
                .with_for_update()
                .first()
            )
            if questionnaire is None:
                raise HTTPException(status_code=404, detail="Questionnaire not found")
        row = VendorRequest(
            workspace_id=workspace_id,
            vendor_email=email,
            questionnaire_id=questionnaire_id,
            message=message,
            status="pending",
            delivery_status="not_sent",
        )
        token = rotate(row, days)
        db.add(row)
        db.flush()
        audit(db, row, "created", actor)
        _settle(db, key, owner, row, fingerprint)
        db.refresh(row)
        return serialize(row, token)
    except Exception:
        db.rollback()
        if key:
            idempotency.release(db, key, owner=owner)
        raise


def revoke(db: Session, workspace_id: int, request_id: int, actor: dict) -> dict:
    actor = current_permission(db, actor)
    row = scoped_request(db, workspace_id, request_id, lock=True)
    if row.revoked_at is None:
        row.revoked_at = now()
        audit(db, row, "revoked", actor)
        db.commit()
        db.refresh(row)
    return serialize(row)


def send(
    db: Session,
    workspace_id: int,
    request_id: int,
    client_key: str | None,
    resend: bool,
    actor: dict,
) -> dict:
    # Scope before key lookup so missing and foreign ids are indistinguishable even on replay.
    scoped_request(db, workspace_id, request_id)
    if not client_key:
        raise HTTPException(
            status_code=422, detail="A request key is required to send an invitation."
        )
    action = "resend" if resend else "send"
    key = idempotency.scoped_key(workspace_id, f"vendor-{action}", request_id, client_key)
    owner, cached = _claim(db, key)
    started = False
    try:
        actor = current_permission(db, actor)
        if cached:
            return serialize(scoped_request(db, workspace_id, request_id))
        row = scoped_request(db, workspace_id, request_id, lock=True)
        if row.revoked_at is not None or row.submitted_at is not None:
            raise HTTPException(
                status_code=409, detail="This request no longer accepts invitations."
            )
        if row.delivery_status in ("sending", "uncertain"):
            raise HTTPException(
                status_code=409,
                detail="The previous delivery outcome is unknown. Reconcile it before sending again.",
            )
        if row.delivery_status == "accepted" and not resend:
            raise HTTPException(
                status_code=409,
                detail="An invitation was already accepted. Use resend for a new invitation.",
            )
        provider = email_service.get_email_provider()
        if isinstance(
            provider, (email_service.ConsoleEmailProvider, email_service.DisabledEmailProvider)
        ):
            row.delivery_status = "unavailable"
            row.last_delivery_error = "provider_unavailable"
            audit(db, row, "delivery_unavailable", actor)
            _settle(db, key, owner, row)
            return serialize(row)
        base = get_settings().app_base_url.rstrip("/")
        parsed = urlsplit(base)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise HTTPException(status_code=503, detail="Invitation delivery is not configured.")
        token = rotate(row)
        row.delivery_status = "sending"
        row.last_delivery_at = now()
        row.last_delivery_error = None
        audit(db, row, "delivery_started", actor)
        # The durable intent and replay marker commit before the external side effect.
        _settle(db, key, owner, row)
        started = True
        message = email_service.EmailMessage(
            to=row.vendor_email,
            subject="Security information request",
            body_text=f"{row.message or 'Please respond to this security information request.'}\n\n{base}/vendor-response?token={token}",
        )
        try:
            if isinstance(provider, email_service.SmtpEmailProvider):
                accepted = provider.send(message, sensitive=True) is True
            else:
                accepted = provider.send(message) is True
        except Exception:
            accepted = False
        row.delivery_status = "accepted" if accepted else "uncertain"
        row.last_delivery_error = None if accepted else "delivery_uncertain"
        audit(db, row, "delivery_accepted" if accepted else "delivery_uncertain", actor)
        db.commit()
        db.refresh(row)
        return serialize(row, token)
    except Exception:
        db.rollback()
        # Once intent committed, releasing the key could repeat an already accepted send.
        if not started:
            idempotency.release(db, key, owner=owner)
        raise


def public_request(db: Session, token: str, lock: bool = False) -> VendorRequest:
    query = db.query(VendorRequest).filter(
        or_(
            VendorRequest.link_token_hash == digest(token),
            (VendorRequest.link_token_hash.is_(None) & (VendorRequest.link_token == token)),
        )
    )
    if lock:
        query = query.with_for_update().populate_existing()
    row = query.first()
    if (
        row is None
        or row.revoked_at is not None
        or grant_expiry(row) is None
        or grant_expiry(row) <= now()
    ):
        raise HTTPException(status_code=404, detail=INVALID_LINK)
    return row


def final_submit(db: Session, token: str, response: str) -> dict:
    row = public_request(db, token, lock=True)
    response_digest = digest(response)
    if row.submitted_at is not None:
        if row.response_digest != response_digest:
            raise HTTPException(
                status_code=409, detail="A different final response was already submitted."
            )
    else:
        row.response_payload = response
        row.response_digest = response_digest
        row.submitted_at = now()
        row.status = "completed"
        audit(db, row, "submitted")
        db.commit()
        db.refresh(row)
    return {
        "status": "completed",
        "submitted_at": aware(row.submitted_at).isoformat(),
        "response_digest": row.response_digest,
    }
