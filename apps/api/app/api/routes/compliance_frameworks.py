"""Compliance foundation: framework catalog list and enablement.

GET /api/compliance/frameworks and POST /api/compliance/frameworks/enable keep
their paths and the historical list fields (id, name, version, created_at).
Catalog metadata is additive. Every advertised framework is blocked until
TC-01-007. Synthetic DEV keys are refused as a production catalog.

Enablement refusals use the versioned error contract framework-catalog-error/v1
in the FastAPI `detail` object. Authentication and permission errors keep the
existing auth responses.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_can_review
from app.core.database import get_db
from app.services.framework_catalog import attempt_enable, list_catalog
from app.services.framework_catalog_registry import CATALOG_CONTRACT_VERSION

router = APIRouter(prefix="/compliance/frameworks", tags=["compliance-frameworks"])


class EnableFrameworkBody(BaseModel):
    """Historical enablement request. Additional properties are rejected."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=64)
    version: str | None = Field(default=None, max_length=32)
    catalog_key: str | None = Field(default=None, max_length=64)


class FrameworkCatalogItem(BaseModel):
    """List item. The first four fields are the baseline response."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    name: str
    version: str | None = None
    created_at: str | None = None
    catalog_key: str | None = None
    source_provenance: dict
    rights_status: str | None = None
    licence_status: str | None = None
    enablement_state: str | None = None
    catalog_kind: str | None = None
    production_catalog: bool = False
    contract_version: str = CATALOG_CONTRACT_VERSION
    content_version: str | None = None
    content_origin: str | None = None
    blocked_reason: str
    synthetic_dev_content_present: bool = False
    dev_test_only: bool = False
    stored_control_count: int = 0
    controls_are_production_catalog: bool = False


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return str(value) if value else "unknown"


@router.get("", response_model=list[FrameworkCatalogItem])
def list_frameworks(
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """List advertised framework catalogs. Read-only; blocked state is computed in memory."""
    del session
    return list_catalog(db)


@router.post("/enable", response_model=None)
def enable_framework(
    body: EnableFrameworkBody,
    request: Request,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Refuse to enable a framework whose rights are not cleared.

    The only write is the audit event. Catalog rows are not inserted or updated.
    A foreign-key failure on the audit event returns the partial-failure contract.
    Error contract: framework-catalog-error/v1.
    """
    result = attempt_enable(
        db,
        name=body.name,
        version=body.version,
        catalog_key=body.catalog_key,
        actor_user_id=session.get("user_id"),
        actor_role=session.get("role"),
        workspace_id=session.get("workspace_id"),
        request_id=_request_id(request),
    )
    raise HTTPException(status_code=result.http_status, detail=result.error)
