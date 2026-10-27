"""Narrow seams for TC-24-001 prerequisites that are not on this branch.

TC-06-001 (typed principal), TC-10-003 (job side-effect idempotency), and
TC-11-002 (model spend bounds) are not implemented here. Billing calls the
functions below so those concerns stay at named boundaries. See the
assumptions in docs/release/tickets/TC-24-001.md.
"""

from dataclasses import dataclass

_EVENT_ID_MAX = 255


@dataclass(frozen=True)
class BillingActor:
    """Minimal actor for billing routes.

    This is not the versioned RequestPrincipal from TC-06-001. It does not
    carry membership, permissions, session id, or deployment-operator state.
    """

    user_id: int | None
    workspace_id: int | None
    source: str


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def principal_for_billing_session(session: dict | None) -> BillingActor:
    """TC-06-001 seam. Adapt the legacy require_session() dict.

    Does not re-read membership, suspension, or API-key service-principal
    rules. Checkout and portal keep today's session dict as their only input.
    """
    raw = session or {}
    return BillingActor(
        user_id=_optional_int(raw.get("user_id")),
        workspace_id=_optional_int(raw.get("workspace_id")),
        source="session",
    )


def principal_for_stripe_event(metadata: dict | None) -> BillingActor:
    """TC-06-001 seam for a signature-verified Stripe event.

    user_id and workspace_id come from metadata this API wrote at checkout.
    They are not authorized against a membership row. Missing values become 0,
    matching the previous webhook handlers.
    """
    raw = metadata if isinstance(metadata, dict) else {}
    user_id = _optional_int(raw.get("user_id"))
    workspace_id = _optional_int(raw.get("workspace_id"))
    return BillingActor(
        user_id=0 if user_id is None else user_id,
        workspace_id=0 if workspace_id is None else workspace_id,
        source="stripe_event",
    )


def billing_idempotency_key(stripe_event_id: str) -> str:
    """TC-10-003 seam. Name the billing dedupe key and stop there.

    The stored unique value is the Stripe event id in stripe_webhook_events.
    This does not write idempotency_keys and does not cover parse, index,
    generate, or export side effects. Exactly-once job execution is not claimed.
    """
    if not isinstance(stripe_event_id, str):
        raise ValueError("stripe event id is required")
    cleaned = stripe_event_id.strip()
    if not cleaned or len(cleaned) > _EVENT_ID_MAX:
        raise ValueError("stripe event id is required")
    return f"stripe_event:{cleaned}"


def spend_bounds_enforced_for_billing() -> bool:
    """TC-11-002 seam. Always False until that ticket lands.

    Webhook handling must not call a model provider. Per-workspace token and
    retry ceilings are not consulted. Checkout still ensures a credit-ledger
    row exists, which is the previous local behavior and is not a model charge.
    """
    return False
