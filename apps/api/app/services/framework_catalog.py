"""Licensed catalog enablement scaffold.

Advertised frameworks are listed and stored as blocked until TC-01-007 clears
content rights. Synthetic dev rows stay labelled dev/test only. This module
does not load, copy, or invent framework control text.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Framework, FrameworkCatalogEvent, FrameworkControl
from app.services.framework_catalog_registry import (
    ADVERTISED_CATALOGS,
    CATALOG_CONTRACT_VERSION,
    CONTENT_DEV,
    CONTENT_LEGACY,
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
    UNLICENSED_VERSION,
    AdvertisedCatalog,
    is_dev_catalog_row,
    is_dev_enable_request,
    is_synthetic_dev_control_key,
    is_synthetic_dev_version,
    normalize_catalog_name,
    provenance_for,
    provenance_json,
    resolve_advertised,
    rights_are_cleared,
)

_BLOCKED_REASON = (
    "Framework content rights are pending decision TC-01-007. "
    "No licensed catalog is loaded and this entry cannot be enabled."
)
_DEV_REASON = (
    "This row is a synthetic dev/test catalog. It is not a production catalog "
    "and cannot be enabled as one."
)


def _utcnow() -> datetime:
    return datetime.utcnow()


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


def _apply_advertised(row: Framework, spec: AdvertisedCatalog, *, control_count: int) -> None:
    row.catalog_key = spec.catalog_key
    row.name = spec.name
    if not (row.version and row.version.strip()) or is_synthetic_dev_version(row.version):
        row.version = UNLICENSED_VERSION
    row.catalog_kind = KIND_ADVERTISED
    row.enablement_state = ENABLEMENT_BLOCKED
    row.rights_status = RIGHTS_BLOCKED
    row.licence_status = LICENCE_NOT_CLEARED
    if row.content_origin == CONTENT_DEV or not row.content_origin:
        row.content_origin = CONTENT_LEGACY if control_count else CONTENT_NONE
    _stamp_common(row, KIND_ADVERTISED)


def _apply_legacy(row: Framework) -> None:
    row.catalog_key = None
    row.catalog_kind = KIND_LEGACY
    row.enablement_state = ENABLEMENT_BLOCKED
    row.rights_status = RIGHTS_BLOCKED
    row.licence_status = LICENCE_NOT_CLEARED
    if not row.content_origin or row.content_origin == CONTENT_NONE:
        row.content_origin = CONTENT_LEGACY
    _stamp_common(row, KIND_LEGACY)


def _new_advertised(spec: AdvertisedCatalog) -> Framework:
    row = Framework(
        name=spec.name,
        version=UNLICENSED_VERSION,
        catalog_key=spec.catalog_key,
        catalog_kind=KIND_ADVERTISED,
        enablement_state=ENABLEMENT_BLOCKED,
        rights_status=RIGHTS_BLOCKED,
        licence_status=LICENCE_NOT_CLEARED,
        rights_ticket=RIGHTS_TICKET,
        contract_version=CATALOG_CONTRACT_VERSION,
        content_origin=CONTENT_NONE,
        scaffold_inserted=True,
        production_catalog=False,
        source_provenance=provenance_json(KIND_ADVERTISED),
        updated_at=_utcnow(),
    )
    return row


def reconcile_catalog(db: Session) -> None:
    """Make persisted rows match the blocked registry. Does not commit.

    Dev rows lose any production catalog key. Missing advertised rows are
    inserted as blocked. Rights cannot be cleared from stored columns.
    """
    if rights_are_cleared():
        raise RuntimeError("rights gate must stay closed until TC-01-007 is decided")

    keys = _control_keys_by_framework(db)
    rows = db.query(Framework).order_by(Framework.id).all()
    for row in rows:
        control_keys = keys.get(row.id, [])
        dev = row.catalog_kind == KIND_DEV or row.content_origin == CONTENT_DEV or is_dev_catalog_row(
            row.name, row.version, control_keys
        )
        if dev:
            label_dev_framework_row(row)
    db.flush()

    for spec in ADVERTISED_CATALOGS:
        row = db.query(Framework).filter(Framework.catalog_key == spec.catalog_key).one_or_none()
        if row is None:
            # A non-dev row with a matching name can become the advertised slot.
            match = None
            for candidate in db.query(Framework).order_by(Framework.id).all():
                if candidate.catalog_kind == KIND_DEV or candidate.content_origin == CONTENT_DEV:
                    continue
                if candidate.catalog_key and candidate.catalog_key != spec.catalog_key:
                    continue
                if normalize_catalog_name(candidate.name) in spec.match_norms():
                    match = candidate
                    break
            if match is not None:
                count = len(keys.get(match.id, []))
                _apply_advertised(match, spec, control_count=count)
                db.flush()
                continue
            created = _new_advertised(spec)
            try:
                with db.begin_nested():
                    db.add(created)
                    db.flush()
            except IntegrityError:
                db.expunge(created)
                existing = db.query(Framework).filter(Framework.catalog_key == spec.catalog_key).one()
                _apply_advertised(existing, spec, control_count=len(keys.get(existing.id, [])))
            continue
        _apply_advertised(row, spec, control_count=len(keys.get(row.id, [])))

    for row in db.query(Framework).order_by(Framework.id).all():
        if row.catalog_key or row.catalog_kind == KIND_DEV:
            continue
        _apply_legacy(row)
    db.flush()
    present = {key for (key,) in db.query(Framework.catalog_key).all() if key}
    missing = [spec.catalog_key for spec in ADVERTISED_CATALOGS if spec.catalog_key not in present]
    if missing:
        raise RuntimeError("advertised catalog rows were not materialized: " + ",".join(missing))


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


def serialize_framework(row: Framework, control_keys: list[str]) -> dict[str, Any]:
    """Public list item. Existing id/name/version/created_at fields are kept.

    Provenance is rebuilt from the row kind so a stored blob cannot add
    control text to the response. content_version stays null: no licensed
    version is loaded. Control titles and descriptions are not read.
    """
    dev_only = _row_dev_test_only(row, control_keys)
    kind = row.catalog_kind or (KIND_DEV if dev_only else KIND_LEGACY)
    if row.catalog_key and not dev_only:
        kind = KIND_ADVERTISED
    advertised = kind == KIND_ADVERTISED and bool(row.catalog_key)
    reason = _DEV_REASON if dev_only else _BLOCKED_REASON
    return {
        "id": row.id,
        "name": row.name,
        "version": row.version,
        "created_at": _iso(row.created_at),
        "catalog_key": row.catalog_key,
        "source_provenance": provenance_for(KIND_DEV if dev_only else kind),
        "rights_status": row.rights_status,
        "licence_status": row.licence_status,
        "enablement_state": row.enablement_state,
        "catalog_kind": KIND_DEV if dev_only and not advertised else (row.catalog_kind or kind),
        "production_catalog": False,
        "rights_ticket": row.rights_ticket or RIGHTS_TICKET,
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
    """Return advertised catalogs first, then dev and legacy rows. Commits the reconcile."""
    reconcile_catalog(db)
    db.commit()
    keys = _control_keys_by_framework(db)
    rows = db.query(Framework).all()
    by_key = {row.catalog_key: row for row in rows if row.catalog_key}
    items: list[dict[str, Any]] = []
    seen: set[int] = set()
    for spec in ADVERTISED_CATALOGS:
        row = by_key.get(spec.catalog_key)
        if row is None:
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
        "rights_ticket": RIGHTS_TICKET,
        "partial_failure": partial_failure,
        "steps": steps or [],
    }


def _find_dev_row(db: Session, name: str) -> Framework | None:
    norm = normalize_catalog_name(name)
    if not norm:
        return None
    keys = _control_keys_by_framework(db)
    for row in db.query(Framework).order_by(Framework.id).all():
        if normalize_catalog_name(row.name) != norm and normalize_catalog_name(row.catalog_key) != norm:
            continue
        if row.catalog_kind == KIND_DEV or is_dev_catalog_row(row.name, row.version, keys.get(row.id, [])):
            return row
    return None


def _write_event(
    db: Session,
    *,
    framework: Framework,
    workspace_id: int | None,
    actor_user_id: int | None,
    actor_role: str | None,
    catalog_key: str | None,
    attempted_version: str | None,
    outcome: str,
    error_code: str,
    request_id: str,
    message: str,
) -> str | None:
    """Insert the audit event in a savepoint. Return a safe failure reason, or None."""
    if workspace_id is None:
        return "workspace_required"
    try:
        with db.begin_nested():
            db.add(
                FrameworkCatalogEvent(
                    framework_id=framework.id,
                    workspace_id=workspace_id,
                    actor_user_id=actor_user_id,
                    actor_role=(actor_role or None),
                    catalog_key=catalog_key,
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


def attempt_enable(
    db: Session,
    *,
    name: str | None,
    version: str | None,
    actor_user_id: int | None,
    actor_role: str | None,
    workspace_id: int | None,
    request_id: str,
) -> EnableResult:
    """Refuse enablement and persist the blocked or dev-only state.

    A foreign-key failure while writing the audit event is a partial failure:
    the catalog row stays blocked (or dev-only) and the event is not written.
    """
    cleaned = (name or "").strip()
    if not cleaned:
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

    if is_dev_enable_request(cleaned, attempted):
        reconcile_catalog(db)
        dev_row = _find_dev_row(db, cleaned)
        if dev_row is not None:
            label_dev_framework_row(dev_row)
            db.flush()
        message = (
            "Synthetic DEV catalog keys are dev/test only and cannot be enabled as a production catalog."
        )
        failure = None
        if dev_row is not None:
            failure = _write_event(
                db,
                framework=dev_row,
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                catalog_key=None,
                attempted_version=attempted,
                outcome="refused_dev",
                error_code=ERROR_DEV,
                request_id=request_id,
                message=message,
            )
        db.commit()
        if failure:
            return EnableResult(
                409,
                _error(
                    code=ERROR_PARTIAL,
                    message=(
                        "The synthetic dev catalog was kept dev/test only, but the audit record "
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
                        {"step": "catalog_state", "status": "persisted", "enablement_state": ENABLEMENT_DEV},
                        {"step": "audit_event", "status": "failed", "reason": failure},
                        {"step": "production_enablement", "status": "refused", "reason": "dev_test_only"},
                    ],
                ),
                dev_row.id if dev_row is not None else None,
            )
        return EnableResult(
            409,
            _error(
                code=ERROR_DEV,
                message=message,
                request_id=request_id,
                retryable=False,
                field_errors={"name": "dev_test_only"} if is_synthetic_dev_control_key(cleaned) or is_synthetic_dev_version(cleaned) else {"version": "dev_test_only"},
                rights_status=RIGHTS_DEV,
                licence_status=LICENCE_DEV,
                enablement_state=ENABLEMENT_DEV,
            ),
            dev_row.id if dev_row is not None else None,
        )

    spec = resolve_advertised(cleaned)
    if spec is None:
        bare_nist = normalize_catalog_name(cleaned) == "nist"
        message = (
            "No advertised framework catalog matches this name."
            if not bare_nist
            else "NIST is not a single production catalog. NIST CSF 2, NIST 800-53r5, and NIST 800-171r3 are separate catalogs."
        )
        message += " Every advertised framework is blocked pending content-rights decision TC-01-007."
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

    reconcile_catalog(db)
    row = db.query(Framework).filter(Framework.catalog_key == spec.catalog_key).one()
    keys = _control_keys_by_framework(db).get(row.id, [])
    _apply_advertised(row, spec, control_count=len(keys))
    db.flush()
    message = (
        f"{spec.name} cannot be enabled. Rights status is blocked pending content-rights "
        f"decision {RIGHTS_TICKET}. No licensed catalog is loaded."
    )
    failure = _write_event(
        db,
        framework=row,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        catalog_key=spec.catalog_key,
        attempted_version=attempted,
        outcome="refused_rights",
        error_code=ERROR_RIGHTS,
        request_id=request_id,
        message=message,
    )
    db.commit()
    db.refresh(row)
    if failure:
        return EnableResult(
            409,
            _error(
                code=ERROR_PARTIAL,
                message=(
                    f"{spec.name} stays blocked pending {RIGHTS_TICKET}. The blocked catalog state was saved, "
                    "but the audit record could not be written because a foreign-key check failed. "
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
                    {"step": "catalog_state", "status": "persisted", "enablement_state": ENABLEMENT_BLOCKED},
                    {"step": "audit_event", "status": "failed", "reason": failure},
                    {"step": "production_enablement", "status": "refused", "reason": "rights_not_cleared"},
                ],
            ),
            row.id,
        )
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
                {"step": "catalog_state", "status": "persisted", "enablement_state": ENABLEMENT_BLOCKED},
                {"step": "audit_event", "status": "persisted"},
                {"step": "production_enablement", "status": "refused", "reason": "rights_not_cleared"},
            ],
        ),
        row.id,
    )
