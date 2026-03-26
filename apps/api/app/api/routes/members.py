"""Workspace members and invites API (AUTH-208, AUTH-215, AUTH-216)."""

import hashlib
import logging
import secrets
import threading
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import persist_audit
from app.core.auth_deps import require_can_admin, require_session
from app.core.invite_codes import generate_invite_code_pair, hash_invite_code
from app.core.config import get_settings
from app.core.database import get_db
from app.core.roles import BUILTIN_ROLES
from app.models import ApiKey, CustomRole, Invite, MfaRecoveryCode, User, UserMfa, UserSession, Workspace, WorkspaceMember
from app.services.email_service import send_invite_email
from app.services.notification_service import fire_notification
from app.services.in_app_notification_service import notify_admins, notify_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/members", tags=["members"])


def _fire_notif(db: Session, workspace_id: int, event_type: str, detail: str = "") -> None:
    """Fire notification safely — never let notification failures break the main operation."""
    try:
        ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        ws_name = ws.name if ws else "Workspace"
        fire_notification(db, workspace_id, event_type, detail=detail, workspace_name=ws_name)
    except Exception:
        pass


def _validate_role(role: str, workspace_id: int, db: Session) -> str:
    """Validate role is a built-in or existing custom role for this workspace. Returns normalized name."""
    role = (role or "").strip().lower()
    if role in BUILTIN_ROLES:
        return role
    cr = db.query(CustomRole).filter(CustomRole.workspace_id == workspace_id, CustomRole.name == role).first()
    if cr:
        return cr.name
    raise HTTPException(status_code=400, detail=f"Invalid role: '{role}'. Must be a built-in role or an existing custom role.")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class CreateInviteRequest(BaseModel):
    email: str
    role: str


class UpdateMemberRequest(BaseModel):
    role: str


class SuspendMemberRequest(BaseModel):
    suspended: bool


@router.get("")
async def list_members(
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """AUTH-216: List workspace members (current workspace from session)."""
    workspace_id = session["workspace_id"]
    members = (
        db.query(WorkspaceMember, User)
        .join(User, WorkspaceMember.user_id == User.id)
        .filter(WorkspaceMember.workspace_id == workspace_id)
        .order_by(User.email)
        .all()
    )
    return {
        "members": [
            {
                "id": mem.id,
                "user_id": mem.user_id,
                "email": u.email,
                "display_name": u.display_name or u.email,
                "role": mem.role,
                "suspended": bool(mem.suspended),
                "created_at": mem.created_at.isoformat() if mem.created_at else None,
            }
            for mem, u in members
        ],
    }


@router.get("/invites")
async def list_invites(
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """AUTH-208: List pending invites for current workspace."""
    workspace_id = session["workspace_id"]
    invites = (
        db.query(Invite, User)
        .outerjoin(User, Invite.created_by_user_id == User.id)
        .filter(Invite.workspace_id == workspace_id)
        .order_by(Invite.created_at.desc())
        .all()
    )
    return {
        "invites": [
            {
                "id": inv.id,
                "email": inv.email,
                "role": inv.role,
                "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
                "invited_by": inviter.email if inviter else None,
            }
            for inv, inviter in invites
        ],
    }


@router.post("/invites")
async def create_invite(
    req: CreateInviteRequest,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """AUTH-208: Create workspace invite; send email with accept link."""
    workspace_id = session["workspace_id"]
    email = (req.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")
    role = _validate_role(req.role, workspace_id, db)
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    existing = (
        db.query(WorkspaceMember)
        .join(User, WorkspaceMember.user_id == User.id)
        .filter(WorkspaceMember.workspace_id == workspace_id, User.email == email)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="User is already a member")
    pending = db.query(Invite).filter(Invite.workspace_id == workspace_id, Invite.email == email).first()
    if pending:
        raise HTTPException(status_code=400, detail="Invite already sent to this email")
    token_raw = secrets.token_urlsafe(32)
    token_hash_val = _token_hash(token_raw)
    code_display, _code_norm = generate_invite_code_pair()
    code_hash_val = hash_invite_code(code_display)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    inv = Invite(
        workspace_id=workspace_id,
        email=email,
        role=role,
        token_hash=token_hash_val,
        invite_code_hash=code_hash_val,
        expires_at=expires_at,
        created_by_user_id=session.get("user_id"),
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    persist_audit(
        db,
        "auth.invite_created",
        user_id=session.get("user_id"),
        email=session.get("email"),
        workspace_id=workspace_id,
        details={"invite_email": email, "role": role},
    )
    try:
        notify_admins(db, workspace_id, f"New invite: {email}", f"Invited as {role}", category="admin", link="/dashboard/members")
    except Exception:
        pass

    base = get_settings().frontend_url.rstrip("/")
    verify_page_url = f"{base}/accept-invite"
    inviter_name = session.get("email", "A team member")
    ws_name = ws.name

    def _bg_send():
        try:
            ok = send_invite_email(email, inviter_name, ws_name, verify_page_url, code_display)
            if not ok:
                logger.warning("Invite email not accepted for delivery to %s", email)
        except Exception as exc:
            logger.warning("Invite email background send failed for %s: %s", email, exc)
        try:
            from app.core.database import SessionLocal
            bg_db = SessionLocal()
            try:
                _fire_notif(bg_db, workspace_id, "member.invited", detail=f"{email} invited as {role}")
                bg_db.commit()
            finally:
                bg_db.close()
        except Exception:
            pass

    threading.Thread(target=_bg_send, daemon=True).start()

    return {
        "id": inv.id,
        "email": inv.email,
        "role": inv.role,
        "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
    }


@router.delete("/invites/{invite_id}")
async def revoke_invite(
    invite_id: int,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """AUTH-208: Revoke a pending invite."""
    workspace_id = session["workspace_id"]
    inv = db.query(Invite).filter(
        Invite.id == invite_id,
        Invite.workspace_id == workspace_id,
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invite not found")
    db.delete(inv)
    db.commit()
    persist_audit(
        db,
        "auth.invite_revoked",
        user_id=session.get("user_id"),
        workspace_id=workspace_id,
        details={"invite_email": inv.email},
    )
    return {"ok": True}


@router.patch("/{member_id}")
async def update_member_role(
    member_id: int,
    req: UpdateMemberRequest,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """AUTH-216: Change member role. AUTH-215: Last admin cannot demote self."""
    workspace_id = session["workspace_id"]
    user_id = session.get("user_id")
    role = _validate_role(req.role, workspace_id, db)
    mem = db.query(WorkspaceMember).filter(
        WorkspaceMember.id == member_id,
        WorkspaceMember.workspace_id == workspace_id,
    ).first()
    if not mem:
        raise HTTPException(status_code=404, detail="Member not found")
    if mem.user_id == user_id:
        admin_count = db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == "admin",
        ).count()
        if admin_count <= 1 and role != "admin":
            raise HTTPException(status_code=400, detail="Transfer ownership to another admin before changing your role")
    mem.role = role
    db.commit()
    db.refresh(mem)
    persist_audit(
        db,
        "auth.role_changed",
        user_id=user_id,
        workspace_id=workspace_id,
        details={"target_user_id": mem.user_id, "new_role": role},
    )
    _fire_notif(db, workspace_id, "member.role_changed", detail=f"User {mem.user_id} role changed to {role}")
    try:
        notify_user(db, workspace_id, mem.user_id, f"Your role changed to {role}", category="admin", link="/dashboard/members")
    except Exception:
        pass
    return {"id": mem.id, "user_id": mem.user_id, "role": mem.role}


@router.delete("/{member_id}")
async def remove_member(
    member_id: int,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """AUTH-216: Remove member from workspace. AUTH-215: Last admin cannot remove self."""
    workspace_id = session["workspace_id"]
    user_id = session.get("user_id")
    mem = db.query(WorkspaceMember).filter(
        WorkspaceMember.id == member_id,
        WorkspaceMember.workspace_id == workspace_id,
    ).first()
    if not mem:
        raise HTTPException(status_code=404, detail="Member not found")
    if mem.user_id == user_id:
        admin_count = db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == "admin",
        ).count()
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Transfer ownership to another admin before leaving")
    removed_user_id = mem.user_id
    db.delete(mem)
    db.commit()
    persist_audit(
        db,
        "auth.member_removed",
        user_id=user_id,
        workspace_id=workspace_id,
        details={"removed_user_id": removed_user_id},
    )
    _fire_notif(db, workspace_id, "member.removed", detail=f"User {removed_user_id} removed")

    remaining = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == removed_user_id).count()
    if remaining == 0:
        orphan = db.query(User).filter(User.id == removed_user_id).first()
        if orphan:
            db.delete(orphan)
            db.commit()
            logger.info("Deleted orphaned user %s (no workspace memberships remain)", removed_user_id)

    return {"ok": True}


@router.patch("/{member_id}/suspend")
async def suspend_member(
    member_id: int,
    req: SuspendMemberRequest,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Suspend or unsuspend a workspace member. Suspended members cannot access the workspace."""
    workspace_id = session["workspace_id"]
    user_id = session.get("user_id")
    mem = db.query(WorkspaceMember).filter(
        WorkspaceMember.id == member_id,
        WorkspaceMember.workspace_id == workspace_id,
    ).first()
    if not mem:
        raise HTTPException(status_code=404, detail="Member not found")
    if mem.user_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot suspend yourself")
    if mem.role == "admin" and req.suspended:
        admin_count = db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == "admin",
            WorkspaceMember.suspended == False,
        ).count()
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot suspend the last active admin")
    mem.suspended = req.suspended
    db.commit()
    db.refresh(mem)
    action = "auth.member_suspended" if req.suspended else "auth.member_unsuspended"
    persist_audit(
        db,
        action,
        user_id=user_id,
        workspace_id=workspace_id,
        details={"target_user_id": mem.user_id, "suspended": req.suspended},
    )
    if req.suspended:
        _fire_notif(db, workspace_id, "member.suspended", detail=f"User {mem.user_id} suspended")
        try:
            notify_admins(db, workspace_id, f"Member suspended", f"User {mem.user_id} has been suspended", category="warning", link="/dashboard/members")
        except Exception:
            pass
    return {"id": mem.id, "user_id": mem.user_id, "suspended": bool(mem.suspended)}


@router.post("/{member_id}/revoke-sessions")
async def admin_revoke_member_sessions(
    member_id: int,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Admin-triggered session revocation for a workspace member."""
    workspace_id = session["workspace_id"]
    mem = db.query(WorkspaceMember).filter(
        WorkspaceMember.id == member_id,
        WorkspaceMember.workspace_id == workspace_id,
    ).first()
    if not mem:
        raise HTTPException(status_code=404, detail="Member not found")
    deleted = db.query(UserSession).filter(
        UserSession.user_id == mem.user_id,
    ).delete(synchronize_session=False)
    db.commit()
    persist_audit(
        db,
        "auth.sessions_revoked_by_admin",
        user_id=session.get("user_id"),
        workspace_id=workspace_id,
        details={"target_user_id": mem.user_id, "sessions_revoked": deleted},
    )
    return {"ok": True, "revoked": deleted}


@router.post("/reset-mfa/{user_id}")
async def admin_reset_mfa(
    user_id: int,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """AUTH-212: Admin-assisted MFA recovery. Reset target user's MFA (same workspace). Strong audit."""
    workspace_id = session["workspace_id"]
    admin_uid = session.get("user_id")
    target_mem = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user_id,
        WorkspaceMember.workspace_id == workspace_id,
    ).first()
    if not target_mem:
        raise HTTPException(status_code=404, detail="User not found in this workspace")
    db.query(UserMfa).filter(UserMfa.user_id == user_id).delete()
    db.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == user_id).delete()
    db.commit()
    target = db.query(User).filter(User.id == user_id).first()
    persist_audit(
        db,
        "auth.mfa_admin_reset",
        user_id=admin_uid,
        workspace_id=workspace_id,
        details={"target_user_id": user_id, "target_email": target.email if target else None},
    )
    return {"ok": True}


# --- API keys (machine auth) ---

class CreateApiKeyRequest(BaseModel):
    label: str | None = None
    role: str = "editor"


@router.post("/api-keys")
async def create_api_key(
    req: CreateApiKeyRequest,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Create a workspace-scoped API key. Returns the raw key once; store it securely."""
    workspace_id = session["workspace_id"]
    role = (req.role or "editor").lower()
    if role not in ("editor", "reviewer", "admin"):
        raise HTTPException(status_code=400, detail="role must be editor, reviewer, or admin")
    raw_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    api_key = ApiKey(
        workspace_id=workspace_id,
        key_hash=key_hash,
        label=(req.label or "").strip() or None,
        role=role,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return {
        "id": api_key.id,
        "label": api_key.label,
        "role": api_key.role,
        "created_at": api_key.created_at.isoformat() if api_key.created_at else None,
        "key": raw_key,
    }


@router.get("/api-keys")
async def list_api_keys(
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """List API keys for the current workspace (keys are not returned)."""
    workspace_id = session["workspace_id"]
    keys = db.query(ApiKey).filter(ApiKey.workspace_id == workspace_id).order_by(ApiKey.created_at.desc()).all()
    return {
        "api_keys": [
            {
                "id": k.id,
                "label": k.label,
                "role": k.role,
                "expires_at": k.expires_at.isoformat() if k.expires_at else None,
                "created_at": k.created_at.isoformat() if k.created_at else None,
            }
            for k in keys
        ],
    }


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Revoke an API key by id (must belong to current workspace)."""
    workspace_id = session["workspace_id"]
    row = db.query(ApiKey).filter(ApiKey.id == key_id, ApiKey.workspace_id == workspace_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="API key not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


# --- Custom roles (Phase B) ---


class CreateCustomRoleRequest(BaseModel):
    name: str
    description: str | None = None
    can_edit: bool = False
    can_review: bool = True
    can_export: bool = False
    can_admin: bool = False


class UpdateCustomRoleRequest(BaseModel):
    description: str | None = None
    can_edit: bool | None = None
    can_review: bool | None = None
    can_export: bool | None = None
    can_admin: bool | None = None


def _role_to_dict(cr: CustomRole) -> dict:
    return {
        "id": cr.id,
        "name": cr.name,
        "description": cr.description,
        "can_edit": bool(cr.can_edit),
        "can_review": bool(cr.can_review),
        "can_export": bool(cr.can_export),
        "can_admin": bool(cr.can_admin),
        "created_at": cr.created_at.isoformat() if cr.created_at else None,
    }


@router.get("/roles")
async def list_roles(
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """List built-in and custom roles for this workspace."""
    workspace_id = session["workspace_id"]
    from app.core.roles import BUILTIN_PERMISSIONS
    builtin = [
        {"id": None, "name": name, "description": f"Built-in {name} role", "builtin": True, **perms}
        for name, perms in BUILTIN_PERMISSIONS.items()
    ]
    custom = db.query(CustomRole).filter(CustomRole.workspace_id == workspace_id).order_by(CustomRole.name).all()
    custom_list = [{**_role_to_dict(cr), "builtin": False} for cr in custom]
    return {"roles": builtin + custom_list}


@router.post("/roles")
async def create_custom_role(
    req: CreateCustomRoleRequest,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Create a custom role for this workspace."""
    workspace_id = session["workspace_id"]
    name = (req.name or "").strip().lower()
    if not name or len(name) < 2 or len(name) > 64:
        raise HTTPException(status_code=400, detail="Role name must be 2-64 characters")
    if name in BUILTIN_ROLES:
        raise HTTPException(status_code=400, detail=f"Cannot use built-in role name '{name}'")
    existing = db.query(CustomRole).filter(CustomRole.workspace_id == workspace_id, CustomRole.name == name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Role '{name}' already exists")
    cr = CustomRole(
        workspace_id=workspace_id,
        name=name,
        description=(req.description or "").strip() or None,
        can_edit=req.can_edit,
        can_review=req.can_review,
        can_export=req.can_export,
        can_admin=req.can_admin,
    )
    db.add(cr)
    db.commit()
    db.refresh(cr)
    persist_audit(
        db,
        "role.created",
        user_id=session.get("user_id"),
        workspace_id=workspace_id,
        resource_type="custom_role",
        resource_id=cr.id,
        details={"name": name, "can_edit": req.can_edit, "can_review": req.can_review, "can_export": req.can_export, "can_admin": req.can_admin},
    )
    return _role_to_dict(cr)


@router.patch("/roles/{role_id}")
async def update_custom_role(
    role_id: int,
    req: UpdateCustomRoleRequest,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Update permissions on a custom role."""
    workspace_id = session["workspace_id"]
    cr = db.query(CustomRole).filter(CustomRole.id == role_id, CustomRole.workspace_id == workspace_id).first()
    if not cr:
        raise HTTPException(status_code=404, detail="Custom role not found")
    changes = {}
    if req.description is not None:
        cr.description = req.description.strip() or None
    for field in ("can_edit", "can_review", "can_export", "can_admin"):
        val = getattr(req, field)
        if val is not None:
            old = getattr(cr, field)
            setattr(cr, field, val)
            if old != val:
                changes[field] = {"from": old, "to": val}
    db.commit()
    db.refresh(cr)
    persist_audit(
        db,
        "role.updated",
        user_id=session.get("user_id"),
        workspace_id=workspace_id,
        resource_type="custom_role",
        resource_id=cr.id,
        details={"name": cr.name, "changes": changes},
    )
    return _role_to_dict(cr)


@router.delete("/roles/{role_id}")
async def delete_custom_role(
    role_id: int,
    db: Session = Depends(get_db),
    session: dict = Depends(require_can_admin),
):
    """Delete a custom role. Members using it are reverted to 'reviewer'."""
    workspace_id = session["workspace_id"]
    cr = db.query(CustomRole).filter(CustomRole.id == role_id, CustomRole.workspace_id == workspace_id).first()
    if not cr:
        raise HTTPException(status_code=404, detail="Custom role not found")
    role_name = cr.name
    reverted = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.role == role_name,
    ).update({"role": "reviewer"}, synchronize_session=False)
    db.delete(cr)
    db.commit()
    persist_audit(
        db,
        "role.deleted",
        user_id=session.get("user_id"),
        workspace_id=workspace_id,
        resource_type="custom_role",
        details={"name": role_name, "members_reverted": reverted},
    )
    return {"ok": True, "members_reverted": reverted}
