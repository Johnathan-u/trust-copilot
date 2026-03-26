"""Credit balance and transaction API — admin for management, authenticated for read."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.services import credit_service

router = APIRouter(prefix="/credits", tags=["credits"])


class AddCreditsRequest(BaseModel):
    amount: int
    description: str | None = None


class UpdateAllocationRequest(BaseModel):
    monthly_allocation: int


@router.get("")
async def get_balance(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Return the current workspace's credit balance and cycle info."""
    workspace_id = session["workspace_id"]
    credit_service.auto_reset_if_due(db, workspace_id)
    db.commit()
    return credit_service.get_balance(db, workspace_id)


@router.get("/transactions")
async def list_transactions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Return credit transaction history for the current workspace."""
    workspace_id = session["workspace_id"]
    txns = credit_service.get_transactions(db, workspace_id, limit=limit, offset=offset)
    return {"transactions": txns}


@router.post("/add")
async def add_credits(
    req: AddCreditsRequest,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Add credits to the current workspace (admin only)."""
    workspace_id = session["workspace_id"]
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    result = credit_service.add_credits(
        db, workspace_id, req.amount,
        kind=credit_service.TX_PURCHASE,
        description=req.description,
    )
    db.commit()
    return result


@router.patch("/allocation")
async def update_allocation(
    req: UpdateAllocationRequest,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Update the monthly credit allocation for the workspace (admin only)."""
    workspace_id = session["workspace_id"]
    if req.monthly_allocation < 0:
        raise HTTPException(status_code=400, detail="Allocation must be non-negative")
    result = credit_service.update_allocation(db, workspace_id, req.monthly_allocation)
    db.commit()
    return result


@router.post("/reset-cycle")
async def reset_cycle(
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    """Manually reset the billing cycle for the workspace (admin only)."""
    workspace_id = session["workspace_id"]
    result = credit_service.reset_cycle(db, workspace_id)
    db.commit()
    return result


@router.get("/check")
async def check_credits(
    question_count: int = Query(..., ge=1),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Check if the workspace has sufficient credits for a given question count."""
    workspace_id = session["workspace_id"]
    sufficient, balance, required = credit_service.check_sufficient(db, workspace_id, question_count)
    return {
        "sufficient": sufficient,
        "balance": balance,
        "required": required,
    }
