"""Shared connect / verify / rotate / revoke handlers for connector routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin
from app.core.database import get_db
from app.core.idempotency import IdempotencyKeyError
from app.core.idempotency import scoped_key as idempotency_scoped_key
from app.services.credential_lifecycle.scopes import (
    canonical_source,
)
from app.services.credential_lifecycle.service import (
    LifecycleConflict,
    LifecycleNotFound,
    connect,
    revoke,
    rotate,
    verify,
)


class CredentialMaterialBody(BaseModel):
    value: str | None = None
    source_type: str | None = None
    connector_type: str | None = None
    credential_type: str | None = None
    access_key_id: str | None = None
    external_account_id: str | None = None
    region: str | None = None
    base_url: str | None = None
    rotation_interval_days: int | None = None
    expires_at: datetime | None = None


def _extra(body: CredentialMaterialBody) -> dict:
    return {
        "access_key_id": body.access_key_id,
        "external_account_id": body.external_account_id,
        "region": body.region,
        "base_url": body.base_url,
    }


def _idempotency_key(request: Request, workspace_id: int, route: str, resource_id: str) -> str:
    raw = request.headers.get("Idempotency-Key")
    try:
        return idempotency_scoped_key(workspace_id, route, resource_id, raw)
    except IdempotencyKeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _call(action):
    try:
        return action()
    except LifecycleNotFound as exc:
        raise HTTPException(status_code=404, detail="Credential not found") from exc
    except LifecycleConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _require_value(body: CredentialMaterialBody) -> str:
    if body.value is None or not body.value.strip():
        raise HTTPException(status_code=400, detail="Value is required")
    return body.value


def run_connect(
    db: Session,
    request: Request,
    session: dict,
    body: CredentialMaterialBody,
    *,
    source_type: str,
    credential_type: str,
    route_name: str,
) -> dict:
    value = _require_value(body)
    source = canonical_source(source_type)
    cred_type = body.credential_type or credential_type
    workspace_id = session["workspace_id"]
    key = _idempotency_key(request, workspace_id, route_name, f"{source}:{cred_type}")
    return _call(
        lambda: connect(
            db,
            workspace_id,
            source,
            cred_type,
            value,
            extra=_extra(body),
            rotation_interval_days=body.rotation_interval_days,
            expires_at=body.expires_at,
            idempotency_key=key,
        )
    )


def run_verify(
    db: Session,
    session: dict,
    *,
    source_type: str,
    credential_type: str,
    credential_id: int | None = None,
) -> dict:
    return _call(
        lambda: verify(
            db,
            session["workspace_id"],
            credential_id=credential_id,
            source_type=None if credential_id is not None else canonical_source(source_type),
            credential_type=None if credential_id is not None else credential_type,
        )
    )


def run_rotate(
    db: Session,
    request: Request,
    session: dict,
    body: CredentialMaterialBody,
    *,
    source_type: str,
    credential_type: str,
    route_name: str,
    credential_id: int | None = None,
) -> dict:
    value = _require_value(body)
    source = canonical_source(source_type)
    cred_type = body.credential_type or credential_type
    workspace_id = session["workspace_id"]
    resource = str(credential_id) if credential_id is not None else f"{source}:{cred_type}"
    key = _idempotency_key(request, workspace_id, route_name, resource)
    return _call(
        lambda: rotate(
            db,
            workspace_id,
            value,
            credential_id=credential_id,
            source_type=None if credential_id is not None else source,
            credential_type=None if credential_id is not None else cred_type,
            extra=_extra(body),
            idempotency_key=key,
        )
    )


def run_revoke(
    db: Session,
    request: Request,
    session: dict,
    *,
    source_type: str,
    credential_type: str,
    route_name: str,
    credential_id: int | None = None,
) -> dict:
    source = canonical_source(source_type)
    workspace_id = session["workspace_id"]
    resource = str(credential_id) if credential_id is not None else f"{source}:{credential_type}"
    key = _idempotency_key(request, workspace_id, route_name, resource)
    return _call(
        lambda: revoke(
            db,
            workspace_id,
            credential_id=credential_id,
            source_type=None if credential_id is not None else source,
            credential_type=None if credential_id is not None else credential_type,
            idempotency_key=key,
        )
    )


def register_fixed(
    router: APIRouter,
    *,
    source_type: str,
    credential_type: str,
    prefix: str,
    path: str = "",
) -> None:
    """Mount /connect /verify /rotate /revoke under ``path`` (for example ``/salesforce``)."""
    base = path.rstrip("/")

    async def connect_route(
        request: Request,
        body: CredentialMaterialBody,
        session: dict = Depends(require_can_admin),
        db: Session = Depends(get_db),
    ):
        result = run_connect(
            db,
            request,
            session,
            body,
            source_type=source_type,
            credential_type=credential_type,
            route_name=f"{prefix}.connect",
        )
        commit_if_needed(db)
        return result

    async def verify_route(
        session: dict = Depends(require_can_admin),
        db: Session = Depends(get_db),
    ):
        result = run_verify(
            db,
            session,
            source_type=source_type,
            credential_type=credential_type,
        )
        commit_if_needed(db)
        return result

    async def rotate_route(
        request: Request,
        body: CredentialMaterialBody,
        session: dict = Depends(require_can_admin),
        db: Session = Depends(get_db),
    ):
        result = run_rotate(
            db,
            request,
            session,
            body,
            source_type=source_type,
            credential_type=credential_type,
            route_name=f"{prefix}.rotate",
        )
        commit_if_needed(db)
        return result

    async def revoke_route(
        request: Request,
        session: dict = Depends(require_can_admin),
        db: Session = Depends(get_db),
    ):
        result = run_revoke(
            db,
            request,
            session,
            source_type=source_type,
            credential_type=credential_type,
            route_name=f"{prefix}.revoke",
        )
        commit_if_needed(db)
        return result

    router.add_api_route(
        f"{base}/connect",
        connect_route,
        methods=["POST"],
        operation_id=f"{prefix}_connect_credential",
    )
    router.add_api_route(
        f"{base}/verify",
        verify_route,
        methods=["POST"],
        operation_id=f"{prefix}_verify_credential",
    )
    router.add_api_route(
        f"{base}/rotate",
        rotate_route,
        methods=["POST"],
        operation_id=f"{prefix}_rotate_credential",
    )
    router.add_api_route(
        f"{base}/revoke",
        revoke_route,
        methods=["POST"],
        operation_id=f"{prefix}_revoke_credential",
    )


def key_committed(db: Session) -> bool:
    """True when the session has no pending writes (idempotency helpers already committed)."""
    return not db.new and not db.dirty and not db.deleted


def commit_if_needed(db: Session) -> None:
    if not key_committed(db):
        db.commit()
