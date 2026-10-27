"""Stripe webhook trust for a buyer-owned account.

Signature
    Stripe's documented v1 scheme. The ``Stripe-Signature`` header carries
    ``t`` (unix seconds) and one or more ``v1`` hex digests. The signed
    string is ``{t}.{raw body}`` where the body is the exact request bytes
    decoded as UTF-8, and the HMAC-SHA256 key is the webhook secret as UTF-8.
    JSON is parsed only after a digest matches. Any one configured secret
    may match, so a secret can be rotated without a gap. ``t`` must fall
    within ``STRIPE_WEBHOOK_TOLERANCE_SECONDS`` of now (default 300) in both
    directions. The official SDK rejects only stale timestamps; this service
    also rejects future timestamps.

Ordering rule
    Subscription state for one Stripe subscription id moves forward only.
    An event applies when its ``created`` time is strictly newer than the
    watermark on the subscription row, or when ``created`` is equal and the
    event type ranks higher. Rank, low to high: ``checkout.session.completed``,
    ``invoice.payment_failed``, ``customer.subscription.updated``,
    ``customer.subscription.deleted``. A deleted event is terminal: after it
    has been applied, a later update, payment-failure, or checkout event for
    that same subscription id does not change status, plan, or period. An
    older event, including a delete that is older than an update already
    applied, is stored, acknowledged, and does not regress the row. The
    watermark stays on the subscription so pruning the replay store cannot
    reopen an old event. The signature tolerance applies to header ``t``,
    not to ``event.created``.

Replay store
    Each Stripe event id is inserted under a unique constraint. A second
    delivery, including a concurrent insert that loses the constraint,
    returns 2xx and does not run the effect again. Rows are pruned on
    ``processed_at`` after ``max(retention, tolerance + 1)`` seconds
    (retention default 7 days), which is past the tolerance window. Stripe
    retries for about 3 days, so the default still recognizes those retries.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.stripe_webhook_event import StripeWebhookEvent
from app.models.subscription import Subscription
from app.services.billing_seams import (
    billing_idempotency_key,
    principal_for_stripe_event,
    spend_bounds_enforced_for_billing,
)

logger = logging.getLogger(__name__)

SIG_MISSING = "Missing Stripe-Signature header"
SIG_MALFORMED = "Invalid Stripe-Signature header"
SIG_INVALID = "Invalid Stripe signature"
SIG_EXPIRED = "Stripe-Signature timestamp is outside the tolerance window (expired)"
SIG_FUTURE = "Stripe-Signature timestamp is outside the tolerance window (future)"
WEBHOOK_NOT_CONFIGURED = "Stripe webhook secret is not configured"
BILLING_UNAVAILABLE = "Billing is not available."
PAYLOAD_INVALID = "Invalid payload"
LIVEMODE_MISMATCH = "event livemode does not match configured Stripe mode"
MODE_UNCONFIGURED = "Stripe mode is not configured"

OUTCOME_APPLIED = "applied"
OUTCOME_STALE = "ignored_stale"
OUTCOME_TERMINAL = "ignored_terminal"
OUTCOME_UNKNOWN = "ignored_unknown"
OUTCOME_UNHANDLED = "ignored_unhandled"
OUTCOME_INCOMPLETE = "ignored_incomplete"

_TYPE_RANK = {
    "checkout.session.completed": 10,
    "invoice.payment_failed": 20,
    "customer.subscription.updated": 30,
    "customer.subscription.deleted": 40,
}

_TEST_KEY_PREFIXES = ("sk_test_", "rk_test_")
_LIVE_KEY_PREFIXES = ("sk_live_", "rk_live_")


class StripeSignatureError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PreflightIssue:
    code: str
    message: str
    fatal: bool


@dataclass(frozen=True)
class WebhookResult:
    status_code: int
    body: dict


def secret_key_mode(secret_key: str | None) -> str | None:
    """Return ``test``, ``live``, ``unknown``, or None when no key is set."""
    if not secret_key:
        return None
    if secret_key.startswith(_TEST_KEY_PREFIXES):
        return "test"
    if secret_key.startswith(_LIVE_KEY_PREFIXES):
        return "live"
    return "unknown"


def configured_stripe_mode(settings) -> str | None:
    """Explicit STRIPE_MODE, otherwise the mode implied by the secret key."""
    explicit = getattr(settings, "stripe_mode", None)
    if explicit in ("test", "live"):
        return explicit
    key_mode = secret_key_mode(getattr(settings, "stripe_secret_key", None))
    if key_mode in ("test", "live"):
        return key_mode
    return None


def stripe_preflight_issues(settings) -> list[PreflightIssue]:
    """Config problems. Fatal issues must stop startup and event handling."""
    issues: list[PreflightIssue] = []
    if getattr(settings, "stripe_mode", None) == "invalid":
        issues.append(
            PreflightIssue(
                "mode_invalid",
                "STRIPE_MODE must be test or live",
                True,
            )
        )
    if not getattr(settings, "stripe_webhook_tolerance_valid", True):
        issues.append(
            PreflightIssue(
                "tolerance_invalid",
                "STRIPE_WEBHOOK_TOLERANCE_SECONDS must be a non-negative integer",
                True,
            )
        )
    if not getattr(settings, "stripe_event_retention_valid", True):
        issues.append(
            PreflightIssue(
                "retention_invalid",
                "STRIPE_EVENT_RETENTION_SECONDS must be a non-negative integer",
                True,
            )
        )

    secret_key = getattr(settings, "stripe_secret_key", None)
    key_mode = secret_key_mode(secret_key)
    mode = configured_stripe_mode(settings)
    if not secret_key:
        # No key: billing is off. An unresolved mode is the same disabled state.
        issues.append(
            PreflightIssue(
                "billing_disabled",
                "Stripe billing is disabled because STRIPE_SECRET_KEY is unset",
                False,
            )
        )
        return issues
    if key_mode == "unknown":
        issues.append(
            PreflightIssue(
                "key_prefix_unknown",
                "STRIPE_SECRET_KEY must be a test or live Stripe key",
                True,
            )
        )
    if key_mode == "test" and mode == "live":
        issues.append(
            PreflightIssue(
                "test_key_live_mode",
                "STRIPE_SECRET_KEY is a test key but Stripe mode is live",
                True,
            )
        )
    if key_mode == "live" and mode == "test":
        issues.append(
            PreflightIssue(
                "live_key_test_mode",
                "STRIPE_SECRET_KEY is a live key but Stripe mode is test",
                True,
            )
        )
    if key_mode == "live" and getattr(settings, "app_env", "") != "production":
        issues.append(
            PreflightIssue(
                "live_key_outside_production",
                "A live Stripe secret key is refused outside production",
                True,
            )
        )

    secrets = tuple(getattr(settings, "stripe_webhook_secrets", ()) or ())
    if not secrets:
        issues.append(
            PreflightIssue(
                "webhook_secret_missing",
                "STRIPE_WEBHOOK_SECRET is required when STRIPE_SECRET_KEY is set",
                True,
            )
        )
    return issues


def raise_for_stripe_preflight(settings) -> None:
    """Startup preflight. Fatal Stripe config refuses to boot."""
    issues = stripe_preflight_issues(settings)
    for issue in issues:
        if not issue.fatal:
            logger.warning("Stripe preflight: %s", issue.message)
    fatal = [issue for issue in issues if issue.fatal]
    if fatal:
        detail = "; ".join(issue.message for issue in fatal)
        raise RuntimeError(f"Stripe configuration failed preflight: {detail}")


def first_fatal_message(settings) -> str | None:
    for issue in stripe_preflight_issues(settings):
        if issue.fatal:
            return issue.message
    return None


def retention_floor_seconds(retention_seconds: int, tolerance_seconds: int) -> int:
    """Keep replay rows at least one second past the signature tolerance."""
    return max(int(retention_seconds), int(tolerance_seconds) + 1)


def price_and_plan_for_interval(settings, interval: str) -> tuple[str, str] | None:
    """Return ``(plan key, price id)`` from config. No amounts are involved."""
    mapping = getattr(settings, "stripe_plan_price_ids", {}) or {}
    if interval == "annual":
        annual_key = settings.stripe_annual_plan
        annual_price = mapping.get(annual_key)
        if annual_price:
            return annual_key, annual_price
    monthly_key = settings.stripe_monthly_plan
    monthly_price = mapping.get(monthly_key)
    if monthly_price:
        return monthly_key, monthly_price
    return None


def plan_for_price_id(settings, price_id: str | None) -> str | None:
    if not price_id:
        return None
    for plan, mapped in (settings.stripe_plan_price_ids or {}).items():
        if mapped == price_id:
            return plan
    return None


def verify_stripe_signature(
    payload: bytes,
    sig_header: str | None,
    secrets: list[str] | tuple[str, ...],
    tolerance_seconds: int,
    now: datetime | None = None,
) -> str:
    """Authenticate ``payload`` and return the UTF-8 body. Does not parse JSON."""
    if not secrets:
        raise StripeSignatureError("missing_secret")
    if not sig_header or not str(sig_header).strip():
        raise StripeSignatureError("missing_header")
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StripeSignatureError("undecodable") from exc

    try:
        timestamp, signatures = _parse_signature_header(sig_header)
    except StripeSignatureError:
        raise
    except Exception as exc:
        raise StripeSignatureError("malformed_header") from exc

    matched = False
    for secret in secrets:
        expected = _compute_signature(timestamp, decoded, secret)
        if _signatures_match(expected, signatures):
            matched = True
    if not matched:
        raise StripeSignatureError("mismatch")

    current = _unix_seconds(now or datetime.now(timezone.utc))
    delta = current - timestamp
    if delta > tolerance_seconds:
        raise StripeSignatureError("timestamp_expired")
    if delta < -tolerance_seconds:
        raise StripeSignatureError("timestamp_future")
    return decoded


def process_stripe_webhook(
    db: Session,
    payload: bytes,
    sig_header: str | None,
    settings,
    now: datetime | None = None,
) -> WebhookResult:
    """Verify, dedupe, and apply one webhook. ``payload`` is the raw body."""
    moment = now or datetime.now(timezone.utc)
    if not getattr(settings, "stripe_secret_key", None):
        return WebhookResult(503, {"detail": BILLING_UNAVAILABLE})
    secrets = tuple(getattr(settings, "stripe_webhook_secrets", ()) or ())
    if not secrets:
        logger.warning("billing unavailable: %s", WEBHOOK_NOT_CONFIGURED)
        return WebhookResult(503, {"detail": BILLING_UNAVAILABLE})
    if not sig_header or not str(sig_header).strip():
        return WebhookResult(400, {"detail": SIG_MISSING})

    try:
        decoded = verify_stripe_signature(
            payload,
            sig_header,
            secrets,
            int(settings.stripe_webhook_tolerance_seconds),
            now=moment,
        )
    except StripeSignatureError as exc:
        return _signature_result(exc)

    fatal = first_fatal_message(settings)
    if fatal:
        logger.warning("billing unavailable: %s", fatal)
        return WebhookResult(503, {"detail": BILLING_UNAVAILABLE})

    try:
        event = _parse_event(decoded)
    except ValueError:
        return WebhookResult(400, {"detail": PAYLOAD_INVALID})

    mode_error = _livemode_error(event["livemode"], settings)
    if mode_error:
        return WebhookResult(400, {"detail": mode_error})

    try:
        namespaced = billing_idempotency_key(event["id"])
    except ValueError:
        return WebhookResult(400, {"detail": PAYLOAD_INVALID})
    if not namespaced.startswith("stripe_event:"):
        return WebhookResult(400, {"detail": PAYLOAD_INVALID})

    _safe_prune(db, settings, moment)

    row = StripeWebhookEvent(
        stripe_event_id=event["id"].strip(),
        event_type=event["type"],
        livemode=event["livemode"],
        stripe_created=event["created"],
        stripe_object_id=event["object_id"],
        outcome="pending",
        processed_at=moment,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        logger.info("stripe webhook duplicate event_id=%s", event["id"].strip())
        return WebhookResult(200, {"received": True, "duplicate": True})

    try:
        outcome, ledger_workspace = _dispatch(db, event, settings)
        row.outcome = outcome
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("stripe webhook apply failed event_id=%s", event["id"].strip())
        return WebhookResult(500, {"detail": "Webhook processing failed"})

    if ledger_workspace is not None:
        _ensure_ledger(db, ledger_workspace)
    logger.info(
        "stripe webhook event_id=%s type=%s outcome=%s",
        event["id"].strip(),
        event["type"],
        outcome,
    )
    return WebhookResult(200, {"received": True, "outcome": outcome})


def prune_stripe_webhook_events(
    db: Session,
    *,
    now: datetime,
    retention_seconds: int,
    tolerance_seconds: int,
) -> int:
    """Delete replay rows older than the retention floor. Returns the count."""
    floor = retention_floor_seconds(retention_seconds, tolerance_seconds)
    cutoff = now - timedelta(seconds=floor)
    deleted = (
        db.query(StripeWebhookEvent)
        .filter(StripeWebhookEvent.processed_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted or 0)


def _signature_result(exc: StripeSignatureError) -> WebhookResult:
    messages = {
        "missing_header": (400, SIG_MISSING),
        "malformed_header": (400, SIG_MALFORMED),
        "mismatch": (400, SIG_INVALID),
        "timestamp_expired": (400, SIG_EXPIRED),
        "timestamp_future": (400, SIG_FUTURE),
        "missing_secret": (503, BILLING_UNAVAILABLE),
        "undecodable": (400, PAYLOAD_INVALID),
    }
    status, detail = messages.get(exc.code, (400, SIG_INVALID))
    if status == 503:
        logger.warning("billing unavailable: %s", WEBHOOK_NOT_CONFIGURED)
    return WebhookResult(status, {"detail": detail})


def _parse_signature_header(header: str) -> tuple[int, list[str]]:
    # Same split as Stripe's WebhookSignature._get_timestamp_and_signatures:
    # first t= wins, every v1= is a candidate, v0 is ignored.
    items = [piece.split("=", 2) for piece in header.split(",")]
    timestamps = [item[1] for item in items if len(item) >= 2 and item[0] == "t"]
    signatures = [item[1] for item in items if len(item) >= 2 and item[0] == "v1"]
    if not timestamps or not signatures:
        raise StripeSignatureError("malformed_header")
    try:
        timestamp = int(timestamps[0])
    except ValueError as exc:
        raise StripeSignatureError("malformed_header") from exc
    return timestamp, signatures


def _compute_signature(timestamp: int, decoded_body: str, secret: str) -> str:
    signed = f"{timestamp}.{decoded_body}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def _signatures_match(expected: str, candidates: list[str]) -> bool:
    matched = False
    for candidate in candidates:
        if len(candidate) == len(expected) and hmac.compare_digest(expected, candidate):
            matched = True
    return matched


def _unix_seconds(moment: datetime) -> int:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp())


def _parse_event(decoded: str) -> dict:
    try:
        data = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid json") from exc
    if not isinstance(data, dict):
        raise ValueError("event must be an object")
    event_id = data.get("id")
    event_type = data.get("type")
    created = data.get("created")
    livemode = data.get("livemode")
    body = data.get("data")
    obj = body.get("object") if isinstance(body, dict) else None
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("missing id")
    if len(event_id.strip()) > 255:
        raise ValueError("id too long")
    if not isinstance(event_type, str) or not event_type.strip():
        raise ValueError("missing type")
    if isinstance(created, bool) or not isinstance(created, int):
        raise ValueError("missing created")
    if not isinstance(livemode, bool):
        raise ValueError("missing livemode")
    if not isinstance(obj, dict):
        raise ValueError("missing object")
    return {
        "id": event_id.strip(),
        "type": event_type.strip(),
        "created": created,
        "livemode": livemode,
        "object": obj,
        "object_id": _object_id(event_type.strip(), obj),
    }


def _object_id(event_type: str, obj: dict) -> str | None:
    if event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        value = obj.get("id")
    elif event_type in ("checkout.session.completed", "invoice.payment_failed"):
        value = obj.get("subscription") or obj.get("id")
    else:
        value = obj.get("id")
    if isinstance(value, str) and value.strip():
        return value.strip()[:255]
    return None


def _livemode_error(livemode: bool, settings) -> str | None:
    mode = configured_stripe_mode(settings)
    if mode is None:
        return MODE_UNCONFIGURED
    if livemode != (mode == "live"):
        return LIVEMODE_MISMATCH
    return None


def _safe_prune(db: Session, settings, now: datetime) -> None:
    try:
        prune_stripe_webhook_events(
            db,
            now=now,
            retention_seconds=int(settings.stripe_event_retention_seconds),
            tolerance_seconds=int(settings.stripe_webhook_tolerance_seconds),
        )
    except Exception:
        db.rollback()
        logger.warning("stripe webhook event prune failed", exc_info=True)


def _dispatch(db: Session, event: dict, settings) -> tuple[str, int | None]:
    event_type = event["type"]
    obj = event["object"]
    created = event["created"]
    if event_type == "checkout.session.completed":
        return _apply_checkout(db, obj, created, settings)
    if event_type == "customer.subscription.updated":
        return _apply_updated(db, obj, created, settings)
    if event_type == "customer.subscription.deleted":
        return _apply_deleted(db, obj, created)
    if event_type == "invoice.payment_failed":
        return _apply_payment_failed(db, obj, created)
    logger.info("Unhandled Stripe event type: %s", event_type)
    return OUTCOME_UNHANDLED, None


def _apply_checkout(db: Session, obj: dict, created: int, settings) -> tuple[str, int | None]:
    customer_id = obj.get("customer")
    subscription_id = obj.get("subscription")
    if not isinstance(customer_id, str) or not customer_id:
        logger.warning("checkout.session.completed missing customer or subscription")
        return OUTCOME_INCOMPLETE, None
    if not isinstance(subscription_id, str) or not subscription_id:
        logger.warning("checkout.session.completed missing customer or subscription")
        return OUTCOME_INCOMPLETE, None

    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    actor = principal_for_stripe_event(metadata)
    sub = _lock_subscription(db, subscription_id)
    if sub is not None:
        decision = _should_apply(sub, created, "checkout.session.completed")
        if decision:
            return decision, None
        if sub.status != "canceled":
            sub.status = "active"
        plan = _plan_for_checkout(obj, settings)
        if plan != "unmapped":
            sub.plan = plan
        _mark(sub, created, "checkout.session.completed", terminal=False)
        return OUTCOME_APPLIED, sub.workspace_id

    if not actor.workspace_id:
        logger.warning("checkout.session.completed rejected: missing workspace_id in metadata")
        return OUTCOME_INCOMPLETE, None
    plan = _plan_for_checkout(obj, settings)
    sub = Subscription(
        workspace_id=actor.workspace_id,
        user_id=actor.user_id or 0,
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        status="active",
        plan=plan,
    )
    _mark(sub, created, "checkout.session.completed", terminal=False)
    db.add(sub)
    db.flush()
    return OUTCOME_APPLIED, sub.workspace_id


def _apply_updated(db: Session, obj: dict, created: int, settings) -> tuple[str, int | None]:
    sub_id = obj.get("id")
    if not isinstance(sub_id, str) or not sub_id:
        return OUTCOME_INCOMPLETE, None
    sub = _lock_subscription(db, sub_id)
    if sub is None:
        logger.warning("subscription.updated for unknown sub_id=%s", sub_id)
        return OUTCOME_UNKNOWN, None
    decision = _should_apply(sub, created, "customer.subscription.updated")
    if decision:
        return decision, None
    status = obj.get("status")
    if isinstance(status, str) and status:
        sub.status = status
    sub.cancel_at_period_end = 1 if obj.get("cancel_at_period_end") else 0
    _apply_period(sub, obj)
    plan = _plan_from_subscription_items(obj, settings)
    if plan:
        sub.plan = plan
    _mark(sub, created, "customer.subscription.updated", terminal=False)
    return OUTCOME_APPLIED, None


def _apply_deleted(db: Session, obj: dict, created: int) -> tuple[str, int | None]:
    sub_id = obj.get("id")
    if not isinstance(sub_id, str) or not sub_id:
        return OUTCOME_INCOMPLETE, None
    sub = _lock_subscription(db, sub_id)
    if sub is None:
        return OUTCOME_UNKNOWN, None
    decision = _should_apply(sub, created, "customer.subscription.deleted")
    if decision:
        return decision, None
    sub.status = "canceled"
    _mark(sub, created, "customer.subscription.deleted", terminal=True)
    return OUTCOME_APPLIED, None


def _apply_payment_failed(db: Session, obj: dict, created: int) -> tuple[str, int | None]:
    sub_id = obj.get("subscription")
    if not isinstance(sub_id, str) or not sub_id:
        return OUTCOME_INCOMPLETE, None
    sub = _lock_subscription(db, sub_id)
    if sub is None:
        return OUTCOME_UNKNOWN, None
    decision = _should_apply(sub, created, "invoice.payment_failed")
    if decision:
        return decision, None
    if sub.status == "active":
        sub.status = "past_due"
    _mark(sub, created, "invoice.payment_failed", terminal=False)
    return OUTCOME_APPLIED, None


def _lock_subscription(db: Session, sub_id: str) -> Subscription | None:
    return (
        db.query(Subscription)
        .filter(Subscription.stripe_subscription_id == sub_id)
        .with_for_update()
        .one_or_none()
    )


def _should_apply(sub: Subscription, created: int, event_type: str) -> str | None:
    terminal = sub.stripe_terminal_event_created is not None
    if terminal and event_type != "customer.subscription.deleted":
        return OUTCOME_TERMINAL
    previous = sub.stripe_event_created
    if previous is None:
        return None
    previous_created = int(previous)
    if created > previous_created:
        return None
    if created < previous_created:
        return OUTCOME_STALE
    previous_rank = _TYPE_RANK.get(sub.stripe_event_type or "", 0)
    if _TYPE_RANK.get(event_type, 0) > previous_rank:
        return None
    return OUTCOME_STALE


def _mark(sub: Subscription, created: int, event_type: str, *, terminal: bool) -> None:
    sub.stripe_event_created = created
    sub.stripe_event_type = event_type
    if terminal:
        sub.stripe_terminal_event_created = created
    sub.updated_at = datetime.now(timezone.utc)


def _apply_period(sub: Subscription, obj: dict) -> None:
    start = obj.get("current_period_start")
    end = obj.get("current_period_end")
    if isinstance(start, int) and not isinstance(start, bool):
        sub.current_period_start = datetime.fromtimestamp(start, tz=timezone.utc)
    if isinstance(end, int) and not isinstance(end, bool):
        sub.current_period_end = datetime.fromtimestamp(end, tz=timezone.utc)


def _plan_for_checkout(obj: dict, settings) -> str:
    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    price_id = metadata.get("price_id")
    if isinstance(price_id, str):
        mapped = plan_for_price_id(settings, price_id)
        if mapped:
            return mapped
    plan = metadata.get("plan")
    if isinstance(plan, str) and plan in (settings.stripe_plan_price_ids or {}):
        return plan
    mapping = settings.stripe_plan_price_ids or {}
    if len(mapping) == 1:
        return next(iter(mapping))
    return "unmapped"


def _plan_from_subscription_items(obj: dict, settings) -> str | None:
    items = obj.get("items")
    data = items.get("data") if isinstance(items, dict) else None
    if not isinstance(data, list):
        return None
    for item in data:
        if not isinstance(item, dict):
            continue
        price = item.get("price")
        price_id = price.get("id") if isinstance(price, dict) else price
        if isinstance(price_id, str):
            mapped = plan_for_price_id(settings, price_id)
            if mapped:
                return mapped
    return None


def _ensure_ledger(db: Session, workspace_id: int) -> None:
    logger.debug(
        "billing seam spend_bounds_enforced=%s",
        spend_bounds_enforced_for_billing(),
    )
    try:
        from app.services import credit_service

        credit_service.get_or_create_ledger(db, workspace_id)
        db.commit()
    except Exception:
        db.rollback()
        logger.warning(
            "Failed to initialize credit ledger for workspace %s",
            workspace_id,
            exc_info=True,
        )
