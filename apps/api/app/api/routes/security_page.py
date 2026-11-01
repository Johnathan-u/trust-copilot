"""Public security page API (P0-82) and owner-approved claims (TC-17-003)."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.routes.security_faq import _current_permission
from app.core.auth_deps import require_session
from app.core.database import get_db
from app.services import security_page_service as sp

router = APIRouter(prefix="/security-page", tags=["security-page"])

require_claims_admin = _current_permission("can_admin")


class ClaimDecision(BaseModel):
    status: Literal["not_claimed", "claimed"]
    statement: str | None = Field(default=None, max_length=500)
    value: str | None = Field(default=None, max_length=320)
    evidence_item_id: int | None = Field(default=None, gt=0, le=2147483647)
    expected_revision: int = Field(ge=0, le=2147483647)


@router.get("")
async def get_security_page(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return sp.get_public_security_page(db, session["workspace_id"])


@router.get("/claims")
async def list_security_claims(
    session: dict = Depends(require_claims_admin),
    db: Session = Depends(get_db),
):
    return {
        "schema_version": sp.SCHEMA_VERSION,
        "claims": sp.list_claims(db, session["workspace_id"]),
    }


@router.put("/claims/{claim_key}")
async def decide_security_claim(
    claim_key: str,
    body: ClaimDecision,
    session: dict = Depends(require_claims_admin),
    db: Session = Depends(get_db),
):
    try:
        result = sp.set_claim(
            db,
            session["workspace_id"],
            claim_key,
            status=body.status,
            statement=body.statement,
            value=body.value,
            evidence_item_id=body.evidence_item_id,
            expected_revision=body.expected_revision,
            actor_id=session.get("user_id"),
        )
        db.commit()
        return result
    except sp.ClaimError as exc:
        db.rollback()
        raise HTTPException(exc.status, exc.message) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409, "This claim changed since you loaded it. Reload and try again."
        ) from None
    except Exception:
        db.rollback()
        raise
