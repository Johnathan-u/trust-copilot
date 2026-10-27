"""Licensed catalog enablement scaffold.

Advertised frameworks are listed and stored as blocked until TC-01-007 clears
content rights. Synthetic dev rows stay labelled dev/test only. This module
does not load, copy, or invent framework control text.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Framework, FrameworkCatalogEvent, FrameworkControl
from app.services.framework_catalog_registry import (
    ADVERTISED_CATALOGS,
    CATALOG_CONTRACT_VERSION,
    CONTENT_DEV,
    CONTENT_NONE,
    ENABLEMENT_BLOCKED,
    ENABLEMENT_DEV,
    ERROR_CONTRACT_VERSION,
    ERROR_DEV,
    ERROR_NAME,
    ERROR_PARTIAL,
    ERROR_RIGHTS,
    ERROR_UNKNOWN,
    KIND_ADVERTISED,
    KIND_DEV,
    KIND_LEGACY,
    LICENCE_DEV,
    LICENCE_NOT_CLEARED,
    RIGHTS_BLOCKED,
    RIGHTS_DEV,
    RIGHTS_TICKET,
    AdvertisedCatalog,
    is_dev_catalog_row,
    is_dev_enable_request,
    is_synthetic_dev_control_key,
    is_synthetic_dev_version,
    normalize_catalog_name,
    provenance_for,
    provenance_json,
    resolve_advertised,
)

logger = logging.getLogger(__name__)

# Customer-facing wording. The ticket id stays in logs and docs, not in this text.
_LICENSING_TEXT = "Pending content licensing"
_BLOCKED_REASON = (
    f"{_LICENSING_TEXT}. No licensed catalog is loaded and this entry cannot be enabled."
)
_DEV_REASON = (
    "This row is a synthetic dev/test catalog. It is not a production catalog "
    "and cannot be enabled as one."
)


def _utcnow() -> datetime:
    # Naive UTC matches the timestamp columns. utcnow() is deprecated.
    return datetime.now(UTC).replace(tzinfo=None)


def _control_keys_by_framework(db: Session) -> dict[int, list[str]]:
    grouped: dict[int, list[str]] = {}
    rows = db.query(FrameworkControl.framework_id, FrameworkControl.control_key).all()
    for framework_id, control_key in rows:
        grouped.setdefault(framework_id, []).append(control_key or "")
    return grouped


def _stamp_common(row: Framework, kind: str) -> None:
    row.rights_ticket = RIGHTS_TICKET
    row.contract_version = CATALOG_CONTRACT_VERSION
    row.production_catalog = False
    row.source_provenance = provenance_json(kind)
    row.updated_at = _utcnow()


def label_dev_framework_row(row: Framework) -> None:
    """Mark a row as dev/test only. It must not keep a production catalog key."""
    row.catalog_key = None
    row.catalog_kind = KIND_DEV
    row.enablement_state = ENABLEMENT_DEV
    row.rights_status = RIGHTS_DEV
    row.licence_status = LICENCE_DEV
    row.content_origin = CONTENT_DEV
    _stamp_common(row, KIND_DEV)


def _public_provenance(kind: str) -> dict[str, object]:
    """Provenance for an API response. The rights ticket stays in logs and storage."""
    payload = dict(provenance_for(kind))
    payload.pop("rights_ticket", None)
    return payload


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _row_dev_test_only(row: Framework, control_keys: list[str]) -> bool:
    return bool(
        row.catalog_kind == KIND_DEV
        or row.enablement_state == ENABLEMENT_DEV
        or row.rights_status == RIGHTS_DEV
        or row.content_origin == CONTENT_DEV
        or is_synthetic_dev_version(row.version)
        or any(is_synthetic_dev_control_key(key) for key in control_keys)
    )


def display_name_for_framework(row: Framework) -> str:
    """Registry display name for an advertised catalog_key. Stored name is unchanged."""
    if row.catalog_key:
        for spec in ADVERTISED_CATALOGS:
            if spec.catalog_key == row.catalog_key:
                return spec.name
    return row.name


def framework_ids_for_exact_name(db: Session, name: str) -> list[int]:
    """Exact-name lookup. A dev row and an advertised row never both resolve."""
    rows = db.query(Framework).filter(Framework.name == name).order_by(Framework.id).all()
    if len(rows) <= 1:
        return [row.id for row in rows]
    keys = _control_keys_by_framework(db)
    dev_ids = {row.id for row in rows if _row_dev_test_only(row, keys.get(row.id, []))}
    advertised = [row for row in rows if row.id not in dev_ids and row.catalog_key]
    if dev_ids and advertised:
        return [row.id for row in advertised]
    if dev_ids and len(rows) != len(dev_ids):
        return [row.id for row in rows if row.id not in dev_ids]
    return [row.id for row in rows]


def _virtual_blocked(spec: AdvertisedCatalog) -> dict[str, Any]:
    """In-memory blocked catalog. Nothing is inserted."""
    return {
        "id": None,
        "name": spec.name,
        "version": None,
        "created_at": None,
        "catalog_key": spec.catalog_key,
        "source_provenance": _public_provenance(KIND_ADVERTISED),
        "rights_status": RIGHTS_BLOCKED,
        "licence_status": LICENCE_NOT_CLEARED,
        "enablement_state": ENABLEMENT_BLOCKED,
        "catalog_kind": KIND_ADVERTISED,
        "production_catalog": False,
        "contract_version": CATALOG_CONTRACT_VERSION,
        "content_version": None,
        "content_origin": CONTENT_NONE,
        "blocked_reason": _BLOCKED_REASON,
        "synthetic_dev_content_present": False,
        "dev_test_only": False,
        "stored_control_count": 0,
        "controls_are_production_catalog": False,
    }


def serialize_framework(row: Framework, control_keys: list[str]) -> dict[str, Any]:
    """Public list item. Stored name and version are not rewritten.

    Advertised catalogs are projected as blocked even if the stored rights
    columns were tampered. Provenance is rebuilt so a stored blob cannot add
    control text. content_version stays null.
    """
    dev_only = _row_dev_test_only(row, control_keys)
    advertised = bool(row.catalog_key) and not dev_only
    if advertised:
        kind = KIND_ADVERTISED
        reason = _BLOCKED_REASON
        rights_status = RIGHTS_BLOCKED
        licence_status = LICENCE_NOT_CLEARED
        enablement_state = ENABLEMENT_BLOCKED
        catalog_kind = KIND_ADVERTISED
        name = display_name_for_framework(row)
    elif dev_only:
        kind = KIND_DEV
        reason = _DEV_REASON
        rights_status = RIGHTS_DEV
        licence_status = LICENCE_DEV
        enablement_state = ENABLEMENT_DEV
        catalog_kind = KIND_DEV
        name = row.name
    else:
        kind = row.catalog_kind or KIND_LEGACY
        reason = _BLOCKED_REASON
        rights_status = RIGHTS_BLOCKED
        licence_status = LICENCE_NOT_CLEARED
        enablement_state = ENABLEMENT_BLOCKED
        catalog_kind = kind
        name = row.name
    return {
        "id": row.id,
        "name": name,
        "version": row.version,
        "created_at": _iso(row.created_at),
        "catalog_key": None if dev_only else row.catalog_key,
        "source_provenance": _public_provenance(kind),
        "rights_status": rights_status,
        "licence_status": licence_status,
        "enablement_state": enablement_state,
        "catalog_kind": catalog_kind,
        "production_catalog": False,
        "contract_version": row.contract_version or CATALOG_CONTRACT_VERSION,
        "content_version": None,
        "content_origin": row.content_origin,
        "blocked_reason": reason,
        "synthetic_dev_content_present": dev_only,
        "dev_test_only": dev_only,
        "stored_control_count": len(control_keys),
        "controls_are_production_catalog": False,
    }


def list_catalog(db: Session) -> list[dict[str, Any]]:
    """Read-only list. Does not insert, update, flush, or commit."""
    keys = _control_keys_by_framework(db)
    rows = db.query(Framework).order_by(Framework.id).all()
    by_key: dict[str, Framework] = {}
    for row in rows:
        if (
            row.catalog_key
            and row.catalog_key not in by_key
            and not _row_dev_test_only(row, keys.get(row.id, []))
        ):
            by_key[row.catalog_key] = row
    items: list[dict[str, Any]] = []
    seen: set[int] = set()
    for spec in ADVERTISED_CATALOGS:
        row = by_key.get(spec.catalog_key)
        if row is None:
            items.append(_virtual_blocked(spec))
            continue
        items.append(serialize_framework(row, keys.get(row.id, [])))
        seen.add(row.id)
    extras = [row for row in rows if row.id not in seen]
    extras.sort(key=lambda row: ((row.name or "").lower(), row.id or 0))
    for row in extras:
        items.append(serialize_framework(row, keys.get(row.id, [])))
    return items


def _error(
    *,
    code: str,
    message: str,
    request_id: str,
    retryable: bool,
    field_errors: dict[str, str] | None = None,
    catalog_key: str | None = None,
    rights_status: str | None = None,
    enablement_state: str | None = None,
    licence_status: str | None = None,
    partial_failure: bool = False,
    steps: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": ERROR_CONTRACT_VERSION,
        "code": code,
        "message": message,
        "request_id": request_id,
        "retryable": retryable,
        "field_errors": field_errors or {},
        "catalog_key": catalog_key,
        "rights_status": rights_status,
        "licence_status": licence_status,
        "enablement_state": enablement_state,
        "partial_failure": partial_failure,
        "steps": steps or [],
    }


def _find_dev_row(db: Session, name: str) -> Framework | None:
    norm = normalize_catalog_name(name)
    if not norm:
        return None
    keys = _control_keys_by_framework(db)
    for row in db.query(Framework).order_by(Framework.id).all():
        if (
            normalize_catalog_name(row.name) != norm
            and normalize_catalog_name(row.catalog_key) != norm
        ):
            continue
        if row.catalog_kind == KIND_DEV or is_dev_catalog_row(
            row.name, row.version, keys.get(row.id, [])
        ):
            return row
    return None


def _write_event(
    db: Session,
    *,
    framework: Framework | None,
    workspace_id: int | None,
    actor_user_id: int | None,
    actor_role: str | None,
    catalog_key: str | None,
    catalog_name: str | None,
    attempted_version: str | None,
    outcome: str,
    error_code: str,
    request_id: str,
    message: str,
) -> str | None:
    """Insert only the audit event. Return a safe failure reason, or None.

    framework_id is optional. catalog_key and name are snapshotted so the event
    survives if the framework row is later removed (ON DELETE SET NULL).
    """
    if workspace_id is None:
        return "workspace_required"
    try:
        with db.begin_nested():
            db.add(
                FrameworkCatalogEvent(
                    framework_id=framework.id if framework is not None else None,
                    workspace_id=workspace_id,
                    actor_user_id=actor_user_id,
                    actor_role=(actor_role or None),
                    catalog_key=catalog_key,
                    name=catalog_name
                    if catalog_name is not None
                    else (framework.name if framework is not None else None),
                    attempted_version=attempted_version,
                    outcome=outcome,
                    error_code=error_code,
                    contract_version=ERROR_CONTRACT_VERSION,
                    request_id=request_id,
                    detail=message,
                )
            )
            db.flush()
    except IntegrityError:
        return "foreign_key_violation"
    return None


class EnableResult:
    def __init__(self, http_status: int, error: dict[str, Any], framework_id: int | None):
        self.http_status = http_status
        self.error = error
        self.framework_id = framework_id

    @property
    def partial_failure(self) -> bool:
        return bool(self.error.get("partial_failure"))


def _resolve_spec(name: str | None, catalog_key: str | None) -> AdvertisedCatalog | None:
    """catalog_key is authoritative. A name is not a fallback when a key was sent."""
    if catalog_key and catalog_key.strip():
        token = catalog_key.strip()
        for spec in ADVERTISED_CATALOGS:
            if spec.catalog_key == token:
                return spec
        return None
    return resolve_advertised(name)


def attempt_enable(
    db: Session,
    *,
    name: str | None,
    version: str | None,
    actor_user_id: int | None,
    actor_role: str | None,
    workspace_id: int | None,
    request_id: str,
    catalog_key: str | None = None,
) -> EnableResult:
    """Refuse enablement. The only write is the audit event. Catalog rows are not changed.

    A foreign-key failure while writing the audit event is a partial failure:
    no catalog row is inserted or updated, and the event is not written.
    """
    cleaned_key = catalog_key.strip() if isinstance(catalog_key, str) else ""
    cleaned = (name or "").strip()
    if not cleaned and not cleaned_key:
        return EnableResult(
            400,
            _error(
                code=ERROR_NAME,
                message="name is required",
                request_id=request_id,
                retryable=False,
                field_errors={"name": "required"},
            ),
            None,
        )

    attempted = version.strip() if isinstance(version, str) and version.strip() else None
    identity = cleaned_key or cleaned

    if is_dev_enable_request(identity, attempted) or is_dev_enable_request(cleaned, attempted):
        dev_row = _find_dev_row(db, cleaned or identity)
        message = (
            "Synthetic DEV catalog keys are dev/test only and cannot be enabled "
            "as a production catalog."
        )
        logger.info(
            "framework enablement refused dev catalog rights_ticket=%s name=%s",
            RIGHTS_TICKET,
            identity,
        )
        failure = _write_event(
            db,
            framework=dev_row,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            catalog_key=None,
            catalog_name=dev_row.name if dev_row is not None else identity,
            attempted_version=attempted,
            outcome="refused_dev",
            error_code=ERROR_DEV,
            request_id=request_id,
            message=message,
        )
        if failure:
            db.rollback()
            return EnableResult(
                409,
                _error(
                    code=ERROR_PARTIAL,
                    message=(
                        "The synthetic dev catalog was not changed, but the audit record "
                        "could not be written because a foreign-key check failed. "
                        "The catalog was not enabled."
                    ),
                    request_id=request_id,
                    retryable=True,
                    field_errors={"name": "dev_test_only"},
                    rights_status=RIGHTS_DEV,
                    licence_status=LICENCE_DEV,
                    enablement_state=ENABLEMENT_DEV,
                    partial_failure=True,
                    steps=[
                        {"step": "catalog_state", "status": "unchanged"},
                        {"step": "audit_event", "status": "failed", "reason": failure},
                        {
                            "step": "production_enablement",
                            "status": "refused",
                            "reason": "dev_test_only",
                        },
                    ],
                ),
                dev_row.id if dev_row is not None else None,
            )
        db.commit()
        return EnableResult(
            409,
            _error(
                code=ERROR_DEV,
                message=message,
                request_id=request_id,
                retryable=False,
                field_errors={"name": "dev_test_only"}
                if is_synthetic_dev_control_key(identity) or is_synthetic_dev_version(identity)
                else {"version": "dev_test_only"},
                rights_status=RIGHTS_DEV,
                licence_status=LICENCE_DEV,
                enablement_state=ENABLEMENT_DEV,
            ),
            dev_row.id if dev_row is not None else None,
        )

    spec = _resolve_spec(cleaned, cleaned_key or None)
    if spec is None:
        bare_nist = normalize_catalog_name(cleaned) == "nist" and not cleaned_key
        message = (
            "No advertised framework catalog matches this name."
            if not bare_nist
            else (
                "NIST is not a single production catalog. NIST CSF 2, NIST 800-53r5, "
                "and NIST 800-171r3 are separate catalogs."
            )
        )
        message += f" {_LICENSING_TEXT}."
        logger.info(
            "framework enablement refused unknown catalog rights_ticket=%s name=%s",
            RIGHTS_TICKET,
            identity,
        )
        return EnableResult(
            400,
            _error(
                code=ERROR_UNKNOWN,
                message=message,
                request_id=request_id,
                retryable=False,
                field_errors={"name": "not_advertised"},
            ),
            None,
        )

    row = (
        db.query(Framework)
        .filter(Framework.catalog_key == spec.catalog_key)
        .order_by(Framework.id)
        .first()
    )
    message = f"{spec.name} cannot be enabled. {_LICENSING_TEXT}. No licensed catalog is loaded."
    logger.info(
        "framework enablement refused rights_ticket=%s catalog_key=%s",
        RIGHTS_TICKET,
        spec.catalog_key,
    )
    failure = _write_event(
        db,
        framework=row,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        catalog_key=spec.catalog_key,
        catalog_name=row.name if row is not None else spec.name,
        attempted_version=attempted,
        outcome="refused_rights",
        error_code=ERROR_RIGHTS,
        request_id=request_id,
        message=message,
    )
    if failure:
        db.rollback()
        return EnableResult(
            409,
            _error(
                code=ERROR_PARTIAL,
                message=(
                    f"{spec.name} was not changed. {_LICENSING_TEXT}. The audit record "
                    "could not be written because a foreign-key check failed. "
                    "Retrying will not enable the catalog."
                ),
                request_id=request_id,
                retryable=True,
                field_errors={"name": "rights_not_cleared"},
                catalog_key=spec.catalog_key,
                rights_status=RIGHTS_BLOCKED,
                licence_status=LICENCE_NOT_CLEARED,
                enablement_state=ENABLEMENT_BLOCKED,
                partial_failure=True,
                steps=[
                    {"step": "catalog_state", "status": "unchanged"},
                    {"step": "audit_event", "status": "failed", "reason": failure},
                    {
                        "step": "production_enablement",
                        "status": "refused",
                        "reason": "rights_not_cleared",
                    },
                ],
            ),
            row.id if row is not None else None,
        )
    db.commit()
    return EnableResult(
        409,
        _error(
            code=ERROR_RIGHTS,
            message=message,
            request_id=request_id,
            retryable=False,
            field_errors={"name": "rights_not_cleared"},
            catalog_key=spec.catalog_key,
            rights_status=RIGHTS_BLOCKED,
            licence_status=LICENCE_NOT_CLEARED,
            enablement_state=ENABLEMENT_BLOCKED,
            steps=[
                {"step": "catalog_state", "status": "unchanged"},
                {"step": "audit_event", "status": "persisted"},
                {
                    "step": "production_enablement",
                    "status": "refused",
                    "reason": "rights_not_cleared",
                },
            ],
        ),
        row.id if row is not None else None,
    )
