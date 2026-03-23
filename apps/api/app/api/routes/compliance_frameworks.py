"""Compliance foundation: frameworks (list, enable)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_can_review
from app.core.database import get_db
from app.models import Framework

router = APIRouter(prefix="/compliance/frameworks", tags=["compliance-frameworks"])


class EnableFrameworkBody(BaseModel):
    name: str
    version: str | None = None


@router.get("", response_model=list)
def list_frameworks(
    session: dict = Depends(require_can_review),
    db: Session = Depends(get_db),
):
    """List all frameworks. Auth required."""
    rows = db.query(Framework).order_by(Framework.name).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "version": r.version,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.post("/enable", response_model=dict)
def enable_framework(
    body: EnableFrameworkBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Create or enable a framework by name. Requires admin."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    existing = db.query(Framework).filter(Framework.name == name).first()
    if existing:
        return {
            "id": existing.id,
            "name": existing.name,
            "version": existing.version or body.version,
            "created_at": existing.created_at.isoformat() if existing.created_at else None,
        }
    fw = Framework(name=name, version=body.version)
    db.add(fw)
    db.commit()
    db.refresh(fw)
    return {
        "id": fw.id,
        "name": fw.name,
        "version": fw.version,
        "created_at": fw.created_at.isoformat() if fw.created_at else None,
    }
