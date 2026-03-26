"""Credit burn and overage prompts service (P1-62)."""

from sqlalchemy.orm import Session

from app.services import credit_service


def get_credit_status(db: Session, workspace_id: int) -> dict:
    """Get credit burn status and prompt recommendations."""
    ledger = credit_service.get_or_create_ledger(db, workspace_id)
    balance = ledger.balance
    allocation = ledger.monthly_allocation

    burn_pct = round((1 - balance / allocation) * 100, 1) if allocation > 0 else 0
    remaining_pct = round(balance / allocation * 100, 1) if allocation > 0 else 0

    prompt = None
    severity = "info"

    if balance <= 0:
        prompt = "Credits exhausted. Processing is blocked. Purchase additional credits or wait for cycle reset."
        severity = "critical"
    elif remaining_pct <= 10:
        prompt = f"Only {balance} credits remaining ({remaining_pct}% of allocation). Consider purchasing more."
        severity = "warning"
    elif remaining_pct <= 25:
        prompt = f"{balance} credits remaining ({remaining_pct}% of allocation). Monitor usage."
        severity = "info"

    return {
        "balance": balance,
        "monthly_allocation": allocation,
        "burn_pct": burn_pct,
        "remaining_pct": remaining_pct,
        "is_exhausted": balance <= 0,
        "prompt": prompt,
        "severity": severity,
        "cycle_start": ledger.cycle_start.isoformat() if ledger.cycle_start else None,
        "cycle_end": ledger.cycle_end.isoformat() if ledger.cycle_end else None,
    }
