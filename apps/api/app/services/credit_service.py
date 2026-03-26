"""Credit ledger service — balance management, consumption, and billing-cycle resets."""

import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.credit_ledger import CreditLedger, CreditTransaction

logger = logging.getLogger(__name__)

TX_ALLOCATION = "allocation"
TX_CONSUMPTION = "consumption"
TX_PURCHASE = "purchase"
TX_ADJUSTMENT = "adjustment"
TX_RESET = "reset"

DEFAULT_MONTHLY_CREDITS = 15


def get_or_create_ledger(db: Session, workspace_id: int) -> CreditLedger:
    """Return the workspace's credit ledger, creating one with defaults if missing."""
    ledger = db.query(CreditLedger).filter(CreditLedger.workspace_id == workspace_id).first()
    if ledger:
        return ledger
    now = datetime.now(timezone.utc)
    ledger = CreditLedger(
        workspace_id=workspace_id,
        balance=DEFAULT_MONTHLY_CREDITS,
        monthly_allocation=DEFAULT_MONTHLY_CREDITS,
        cycle_start=now,
        cycle_end=now + timedelta(days=30),
    )
    db.add(ledger)
    db.flush()
    _record_tx(db, workspace_id, TX_ALLOCATION, DEFAULT_MONTHLY_CREDITS, ledger.balance, description="Initial credit allocation")
    return ledger


def get_balance(db: Session, workspace_id: int) -> dict:
    """Return credit balance summary for a workspace."""
    ledger = get_or_create_ledger(db, workspace_id)
    return {
        "balance": ledger.balance,
        "monthly_allocation": ledger.monthly_allocation,
        "cycle_start": ledger.cycle_start.isoformat() if ledger.cycle_start else None,
        "cycle_end": ledger.cycle_end.isoformat() if ledger.cycle_end else None,
    }


def credits_required(question_count: int) -> int:
    """Calculate credits needed for a questionnaire. 1 credit per 100 questions, minimum 1."""
    if question_count <= 0:
        return 1
    return max(1, math.ceil(question_count / 100))


def check_sufficient(db: Session, workspace_id: int, question_count: int) -> tuple[bool, int, int]:
    """Check if a workspace has enough credits. Returns (sufficient, balance, required)."""
    ledger = get_or_create_ledger(db, workspace_id)
    required = credits_required(question_count)
    return ledger.balance >= required, ledger.balance, required


def consume(
    db: Session,
    workspace_id: int,
    question_count: int,
    questionnaire_id: int | None = None,
) -> dict:
    """Deduct credits for processing a questionnaire. Raises ValueError if insufficient."""
    ledger = get_or_create_ledger(db, workspace_id)
    required = credits_required(question_count)
    if ledger.balance < required:
        raise ValueError(
            f"Insufficient credits: {ledger.balance} available, {required} required "
            f"({question_count} questions)"
        )
    ledger.balance -= required
    db.flush()
    _record_tx(
        db, workspace_id, TX_CONSUMPTION, -required, ledger.balance,
        questionnaire_id=questionnaire_id,
        description=f"Consumed {required} credit(s) for {question_count} questions",
    )
    return {"consumed": required, "balance": ledger.balance}


def add_credits(
    db: Session,
    workspace_id: int,
    amount: int,
    kind: str = TX_PURCHASE,
    description: str | None = None,
) -> dict:
    """Add credits to a workspace (purchase, adjustment, or allocation)."""
    if amount <= 0:
        raise ValueError("Amount must be positive")
    ledger = get_or_create_ledger(db, workspace_id)
    ledger.balance += amount
    db.flush()
    _record_tx(db, workspace_id, kind, amount, ledger.balance, description=description or f"Added {amount} credits")
    return {"added": amount, "balance": ledger.balance}


def reset_cycle(db: Session, workspace_id: int) -> dict:
    """Reset credits for a new billing cycle. Sets balance to monthly_allocation."""
    ledger = get_or_create_ledger(db, workspace_id)
    old_balance = ledger.balance
    now = datetime.now(timezone.utc)
    ledger.balance = ledger.monthly_allocation
    ledger.cycle_start = now
    ledger.cycle_end = now + timedelta(days=30)
    db.flush()
    _record_tx(
        db, workspace_id, TX_RESET,
        ledger.monthly_allocation - old_balance,
        ledger.balance,
        description=f"Billing cycle reset: {old_balance} -> {ledger.monthly_allocation}",
    )
    return {"balance": ledger.balance, "cycle_start": now.isoformat(), "cycle_end": ledger.cycle_end.isoformat()}


def auto_reset_if_due(db: Session, workspace_id: int) -> bool:
    """Reset credits if the current billing cycle has ended. Returns True if reset happened."""
    ledger = get_or_create_ledger(db, workspace_id)
    if not ledger.cycle_end:
        return False
    now = datetime.now(timezone.utc)
    if now >= ledger.cycle_end:
        reset_cycle(db, workspace_id)
        return True
    return False


def get_transactions(
    db: Session,
    workspace_id: int,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Return credit transaction history for a workspace."""
    rows = (
        db.query(CreditTransaction)
        .filter(CreditTransaction.workspace_id == workspace_id)
        .order_by(CreditTransaction.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "amount": r.amount,
            "balance_after": r.balance_after,
            "questionnaire_id": r.questionnaire_id,
            "description": r.description,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def update_allocation(db: Session, workspace_id: int, monthly_allocation: int) -> dict:
    """Update the monthly credit allocation for a workspace (admin action)."""
    if monthly_allocation < 0:
        raise ValueError("Allocation must be non-negative")
    ledger = get_or_create_ledger(db, workspace_id)
    ledger.monthly_allocation = monthly_allocation
    db.flush()
    return {"monthly_allocation": ledger.monthly_allocation, "balance": ledger.balance}


def _record_tx(
    db: Session,
    workspace_id: int,
    kind: str,
    amount: int,
    balance_after: int,
    questionnaire_id: int | None = None,
    description: str | None = None,
) -> CreditTransaction:
    tx = CreditTransaction(
        workspace_id=workspace_id,
        kind=kind,
        amount=amount,
        balance_after=balance_after,
        questionnaire_id=questionnaire_id,
        description=description,
    )
    db.add(tx)
    db.flush()
    return tx
