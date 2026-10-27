"""TC-24-001 Stripe webhook trust. Fixtures are signed here with throwaway secrets.

No Stripe account and no network. The v1 scheme is Stripe's documented
HMAC over ``{timestamp}.{raw body}``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.config import get_settings

API_ROOT = Path(__file__).resolve().parents[2]
SECRET_A = "whsec_tc24001_primary"
SECRET_B = "whsec_tc24001_rotated"
TEST_KEY = "sk_test_tc24001_not_a_real_key"
LIVE_KEY = "sk_live_tc24001_not_a_real_key"
KNOWN_VECTOR_DIGEST = "181799648840baa60956d37e46cb72457fb28dce5554adddad16d051a935454d"

STRIPE_ENV_KEYS = (
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "STRIPE_WEBHOOK_SECRETS",
    "STRIPE_MODE",
    "STRIPE_PLAN_PRICE_IDS",
    "STRIPE_PRICE_ID",
    "STRIPE_ANNUAL_PRICE_ID",
    "STRIPE_MONTHLY_PLAN",
    "STRIPE_ANNUAL_PLAN",
    "STRIPE_WEBHOOK_TOLERANCE_SECONDS",
    "STRIPE_EVENT_RETENTION_SECONDS",
)


def sign(payload: bytes, secret: str, timestamp: int) -> str:
    signed = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def dumps(body: dict) -> bytes:
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


@pytest.fixture(autouse=True)
def _clear_stripe_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    for key in STRIPE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def stripe_settings(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("STRIPE_SECRET_KEY", TEST_KEY)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET_A)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRETS", raising=False)
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv(
        "STRIPE_PLAN_PRICE_IDS",
        "pro:price_tc24001_monthly,pro_annual:price_tc24001_annual",
    )
    monkeypatch.setenv("STRIPE_WEBHOOK_TOLERANCE_SECONDS", "300")
    monkeypatch.setenv("STRIPE_EVENT_RETENTION_SECONDS", "604800")
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def billing_client(_ensure_test_data):
    if not _ensure_test_data:
        pytest.fail("Postgres is required for TC-24-001; not skipping")
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(
        app,
        base_url="http://localhost",
        headers={"Origin": "http://localhost", "Referer": "http://localhost/"},
    ) as client:
        yield client


@pytest.fixture
def bag(_ensure_test_data):
    if not _ensure_test_data:
        pytest.fail("Postgres is required for TC-24-001; not skipping")
    state = {"sub": f"sub_tc24001_{uuid.uuid4().hex[:12]}", "events": []}
    yield state
    from app.core.database import SessionLocal
    from app.models import StripeWebhookEvent, Subscription

    db = SessionLocal()
    try:
        if state["events"]:
            db.query(StripeWebhookEvent).filter(
                StripeWebhookEvent.stripe_event_id.in_(state["events"])
            ).delete(synchronize_session=False)
        db.query(Subscription).filter(Subscription.stripe_subscription_id == state["sub"]).delete(
            synchronize_session=False
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def reload_settings():
    get_settings.cache_clear()
    return get_settings()


def new_event_id(bag, suffix: str) -> str:
    value = f"evt_tc24001_{suffix}_{uuid.uuid4().hex[:8]}"
    bag["events"].append(value)
    return value


def checkout_body(event_id: str, created: int, sub_id: str, *, livemode: bool = False) -> dict:
    return {
        "id": event_id,
        "object": "event",
        "type": "checkout.session.completed",
        "created": created,
        "livemode": livemode,
        "api_version": "2024-06-20",
        "data": {
            "object": {
                "id": f"cs_{event_id}",
                "object": "checkout.session",
                "customer": "cus_tc24001",
                "subscription": sub_id,
                "mode": "subscription",
                "metadata": {
                    "user_id": "1",
                    "workspace_id": "1",
                    "plan": "pro",
                    "price_id": "price_tc24001_monthly",
                },
            }
        },
    }


def subscription_body(
    event_id: str,
    event_type: str,
    created: int,
    sub_id: str,
    *,
    status: str = "active",
    livemode: bool = False,
    price_id: str | None = None,
) -> dict:
    obj = {
        "id": sub_id,
        "object": "subscription",
        "customer": "cus_tc24001",
        "status": status,
        "cancel_at_period_end": False,
        "current_period_start": created,
        "current_period_end": created + 2592000,
        "metadata": {"user_id": "1", "workspace_id": "1"},
    }
    if price_id:
        obj["items"] = {"object": "list", "data": [{"price": {"id": price_id}}]}
    return {
        "id": event_id,
        "object": "event",
        "type": event_type,
        "created": created,
        "livemode": livemode,
        "data": {"object": obj},
    }


def invoice_body(event_id: str, created: int, sub_id: str, *, livemode: bool = False) -> dict:
    return {
        "id": event_id,
        "object": "event",
        "type": "invoice.payment_failed",
        "created": created,
        "livemode": livemode,
        "data": {
            "object": {
                "id": f"in_{event_id}",
                "object": "invoice",
                "subscription": sub_id,
            }
        },
    }


def post_webhook(
    client,
    body: dict | None,
    secret: str,
    *,
    raw: bytes | None = None,
    timestamp: int | None = None,
    header: str | None = None,
    include_header: bool = True,
):
    payload = raw if raw is not None else dumps(body or {})
    ts = int(time.time()) if timestamp is None else timestamp
    headers = {"Content-Type": "application/json"}
    if include_header:
        headers["Stripe-Signature"] = header if header is not None else sign(payload, secret, ts)
    response = client.post("/api/billing/webhook", content=payload, headers=headers)
    return response


def sub_state(sub_id: str) -> dict | None:
    from app.core.database import SessionLocal
    from app.models import Subscription

    db = SessionLocal()
    try:
        row = (
            db.query(Subscription)
            .filter(Subscription.stripe_subscription_id == sub_id)
            .one_or_none()
        )
        if row is None:
            return None
        return {
            "status": row.status,
            "plan": row.plan,
            "watermark": (
                None if row.stripe_event_created is None else int(row.stripe_event_created)
            ),
            "watermark_type": row.stripe_event_type,
            "terminal": (
                None
                if row.stripe_terminal_event_created is None
                else int(row.stripe_terminal_event_created)
            ),
        }
    finally:
        db.close()


def event_rows(event_id: str) -> list[str]:
    from app.core.database import SessionLocal
    from app.models import StripeWebhookEvent

    db = SessionLocal()
    try:
        rows = (
            db.query(StripeWebhookEvent)
            .filter(StripeWebhookEvent.stripe_event_id == event_id)
            .all()
        )
        return [row.outcome for row in rows]
    finally:
        db.close()


def test_ordering_rule_is_documented():
    from app.services import billing_provider

    doc = billing_provider.__doc__ or ""
    assert "customer.subscription.deleted" in doc
    assert "customer.subscription.updated" in doc
    assert "created" in doc
    assert "terminal" in doc
    assert "tolerance" in doc


def test_no_default_stripe_secret_and_no_amounts(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRETS", raising=False)
    settings = reload_settings()
    assert settings.stripe_secret_key is None
    assert settings.stripe_webhook_secret is None
    assert settings.stripe_webhook_secrets == ()

    monkeypatch.setenv("STRIPE_PLAN_PRICE_IDS", "pro:price_tc24001_monthly")
    monkeypatch.setenv("STRIPE_ANNUAL_PRICE_ID", "price_tc24001_annual")
    settings = reload_settings()
    assert settings.stripe_plan_price_ids == {
        "pro": "price_tc24001_monthly",
        "pro_annual": "price_tc24001_annual",
    }
    blob = " ".join(settings.stripe_plan_price_ids.values())
    assert "$" not in blob
    for amount in ("399", "250"):
        assert amount not in blob

    source = Path(billing_provider_path()).read_text()
    assert "$" not in source
    for token in ("399", "$25", "$250"):
        assert token not in source


def billing_provider_path() -> Path:
    import app.services.billing_provider as module

    return Path(module.__file__)


def test_documented_v1_vector_and_tolerance_edges():
    from app.services.billing_provider import StripeSignatureError, verify_stripe_signature

    payload = b'{"id":"evt_test"}'
    header = f"t=1710000000,v1={KNOWN_VECTOR_DIGEST}"
    moment = datetime.fromtimestamp(1710000000, tz=timezone.utc)
    decoded = verify_stripe_signature(payload, header, ["whsec_test_secret"], 300, now=moment)
    assert decoded == payload.decode("utf-8")

    with pytest.raises(StripeSignatureError) as wrong:
        verify_stripe_signature(payload, header, ["whsec_other_secret"], 300, now=moment)
    assert wrong.value.code == "mismatch"

    again = verify_stripe_signature(payload, header, ["whsec_test_secret"], 300, now=moment)
    assert again == decoded
    later = datetime.fromtimestamp(1710000000 + 300, tz=timezone.utc)
    earlier = datetime.fromtimestamp(1710000000 - 300, tz=timezone.utc)
    verify_stripe_signature(payload, header, ["whsec_test_secret"], 300, now=later)
    verify_stripe_signature(payload, header, ["whsec_test_secret"], 300, now=earlier)
    with pytest.raises(StripeSignatureError) as expired:
        verify_stripe_signature(
            payload,
            header,
            ["whsec_test_secret"],
            300,
            now=datetime.fromtimestamp(1710000000 + 301, tz=timezone.utc),
        )
    assert expired.value.code == "timestamp_expired"
    with pytest.raises(StripeSignatureError) as future:
        verify_stripe_signature(
            payload,
            header,
            ["whsec_test_secret"],
            300,
            now=datetime.fromtimestamp(1710000000 - 301, tz=timezone.utc),
        )
    assert future.value.code == "timestamp_future"


def test_second_configured_secret_and_second_header_signature():
    from app.services.billing_provider import verify_stripe_signature

    payload = b'{"id":"evt_rotate"}'
    ts = 1710000000
    moment = datetime.fromtimestamp(ts, tz=timezone.utc)
    good = sign(payload, SECRET_B, ts)
    verify_stripe_signature(payload, good, [SECRET_A, SECRET_B], 300, now=moment)

    fake = "v1=" + ("ab" * 32)
    rotated_header = f"t={ts},{fake},{good.split(',', 1)[1]}"
    verify_stripe_signature(payload, rotated_header, [SECRET_B], 300, now=moment)


def test_signature_matches_stripe_sdk_v1_scheme():
    import stripe

    from app.services.billing_provider import verify_stripe_signature

    secret = "whsec_sdk_oracle_not_real"
    payload = dumps(
        {
            "id": "evt_sdk_oracle",
            "object": "event",
            "type": "customer.subscription.updated",
            "created": 1710000000,
            "livemode": False,
            "data": {"object": {"id": "sub_sdk", "object": "subscription"}},
        }
    )
    ts = int(time.time())
    sdk_header = stripe.WebhookSignature.generate_signature_header(
        payload.decode("utf-8"),
        secret,
        timestamp=ts,
    )
    verified = verify_stripe_signature(payload, sdk_header, [secret], 300)
    assert json.loads(verified)["id"] == "evt_sdk_oracle"
    stripe.WebhookSignature.verify_header(payload, sdk_header, secret, tolerance=300)
    our_header = sign(payload, secret, ts)
    stripe.WebhookSignature.verify_header(payload, our_header, secret, tolerance=300)
    with pytest.raises(stripe.SignatureVerificationError):
        stripe.WebhookSignature.verify_header(payload, our_header, "whsec_other", tolerance=300)


def test_valid_signature_maps_plan_from_price_id(billing_client, stripe_settings, bag):
    event_id = new_event_id(bag, "checkout")
    response = post_webhook(
        billing_client,
        checkout_body(event_id, 1_700_000_000, bag["sub"]),
        SECRET_A,
    )
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "applied"
    state = sub_state(bag["sub"])
    assert state is not None
    assert state["status"] == "active"
    assert state["plan"] == "pro"
    assert state["watermark"] == 1_700_000_000

    annual_id = new_event_id(bag, "annual")
    annual = post_webhook(
        billing_client,
        subscription_body(
            annual_id,
            "customer.subscription.updated",
            1_700_000_100,
            bag["sub"],
            status="active",
            price_id="price_tc24001_annual",
        ),
        SECRET_A,
    )
    assert annual.status_code == 200, annual.text
    assert sub_state(bag["sub"])["plan"] == "pro_annual"


def test_wrong_secret_tampered_body_and_missing_header(billing_client, stripe_settings, bag):
    body = checkout_body(new_event_id(bag, "bad"), 1_700_000_000, bag["sub"])
    payload = dumps(body)
    ts = int(time.time())
    wrong = post_webhook(billing_client, body, SECRET_B, timestamp=ts)
    assert wrong.status_code == 400
    assert wrong.json()["detail"] == "Invalid Stripe signature"
    assert sub_state(bag["sub"]) is None

    tampered = payload + b" "
    tampered_response = post_webhook(
        billing_client,
        None,
        SECRET_A,
        raw=tampered,
        header=sign(payload, SECRET_A, ts),
        timestamp=ts,
    )
    assert tampered_response.status_code == 400
    assert tampered_response.json()["detail"] == "Invalid Stripe signature"

    pretty = json.dumps(body, indent=2).encode("utf-8")
    pretty_response = post_webhook(
        billing_client,
        None,
        SECRET_A,
        raw=pretty,
        header=sign(payload, SECRET_A, ts),
    )
    assert pretty_response.status_code == 400
    assert pretty_response.json()["detail"] == "Invalid Stripe signature"

    missing = post_webhook(billing_client, body, SECRET_A, include_header=False)
    assert missing.status_code == 400
    assert missing.json()["detail"] == "Missing Stripe-Signature header"
    assert sub_state(bag["sub"]) is None
    assert event_rows(body["id"]) == []


def test_invalid_json_is_rejected_only_after_a_valid_signature(billing_client, stripe_settings):
    raw = b'{"id": '
    ts = int(time.time())
    bad_sig = post_webhook(
        billing_client,
        None,
        SECRET_A,
        raw=raw,
        header=sign(b'{"id": "evt"}', SECRET_A, ts),
        timestamp=ts,
    )
    assert bad_sig.status_code == 400
    assert bad_sig.json()["detail"] == "Invalid Stripe signature"

    good_sig = post_webhook(
        billing_client,
        None,
        SECRET_A,
        raw=raw,
        header=sign(raw, SECRET_A, ts),
        timestamp=ts,
    )
    assert good_sig.status_code == 400
    assert good_sig.json()["detail"] == "Invalid payload"


def test_expired_and_future_timestamps(billing_client, stripe_settings, bag):
    body = checkout_body(new_event_id(bag, "time"), 1_700_000_000, bag["sub"])
    now = int(time.time())
    expired = post_webhook(billing_client, body, SECRET_A, timestamp=now - 301)
    assert expired.status_code == 400
    assert "expired" in expired.json()["detail"]
    future = post_webhook(billing_client, body, SECRET_A, timestamp=now + 301)
    assert future.status_code == 400
    assert "future" in future.json()["detail"]
    assert sub_state(bag["sub"]) is None
    assert event_rows(body["id"]) == []


def test_rotated_second_secret_is_accepted(billing_client, stripe_settings, bag, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_tc24001_old")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRETS", SECRET_B)
    reload_settings()
    event_id = new_event_id(bag, "rotated")
    response = post_webhook(
        billing_client,
        checkout_body(event_id, 1_700_000_000, bag["sub"]),
        SECRET_B,
    )
    assert response.status_code == 200, response.text
    assert sub_state(bag["sub"])["status"] == "active"


def test_replay_is_a_noop_and_does_not_reapply(billing_client, stripe_settings, bag):
    from app.core.database import SessionLocal
    from app.models import Subscription

    checkout_id = new_event_id(bag, "replay_checkout")
    update_id = new_event_id(bag, "replay_update")
    assert (
        post_webhook(
            billing_client,
            checkout_body(checkout_id, 1_700_000_000, bag["sub"]),
            SECRET_A,
        ).status_code
        == 200
    )
    update = subscription_body(
        update_id,
        "customer.subscription.updated",
        1_700_000_200,
        bag["sub"],
        status="past_due",
    )
    first = post_webhook(billing_client, update, SECRET_A)
    assert first.status_code == 200, first.text
    assert first.json()["outcome"] == "applied"
    assert sub_state(bag["sub"])["status"] == "past_due"

    db = SessionLocal()
    try:
        row = db.query(Subscription).filter(Subscription.stripe_subscription_id == bag["sub"]).one()
        row.status = "active"
        db.commit()
    finally:
        db.close()

    second = post_webhook(billing_client, update, SECRET_A)
    assert second.status_code == 200, second.text
    assert second.json()["duplicate"] is True
    assert sub_state(bag["sub"])["status"] == "active"
    assert event_rows(update_id) == ["applied"]


def test_concurrent_duplicate_event_ids_hit_unique_constraint(stripe_settings, bag, monkeypatch):
    from app.core.database import SessionLocal
    from app.services import billing_provider

    calls = {"n": 0}
    lock = threading.Lock()
    real_dispatch = billing_provider._dispatch

    def counting_dispatch(db, event, settings):
        with lock:
            calls["n"] += 1
        return real_dispatch(db, event, settings)

    monkeypatch.setattr(billing_provider, "_dispatch", counting_dispatch)
    event_id = new_event_id(bag, "concurrent")
    payload = dumps(checkout_body(event_id, 1_700_000_000, bag["sub"]))
    ts = int(time.time())
    header = sign(payload, SECRET_A, ts)
    barrier = threading.Barrier(2, timeout=20)
    results = []
    errors = []

    def worker():
        db = SessionLocal()
        try:
            barrier.wait()
            result = billing_provider.process_stripe_webhook(
                db,
                payload,
                header,
                stripe_settings,
            )
            with lock:
                results.append(result)
        except Exception as exc:  # noqa: BLE001 - the test asserts on this list
            with lock:
                errors.append(exc)
        finally:
            db.rollback()
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert not errors, errors
    assert len(results) == 2
    assert [item.status_code for item in results] == [200, 200]
    assert sorted(item.body.get("duplicate", False) for item in results) == [False, True]
    assert calls["n"] == 1
    assert event_rows(event_id) == ["applied"]
    assert sub_state(bag["sub"])["status"] == "active"


def test_out_of_order_events_do_not_regress_state(billing_client, stripe_settings, bag):
    sub = bag["sub"]
    assert (
        post_webhook(
            billing_client,
            checkout_body(new_event_id(bag, "oo_checkout"), 1_700_000_000, sub),
            SECRET_A,
        ).status_code
        == 200
    )

    newer = post_webhook(
        billing_client,
        subscription_body(
            new_event_id(bag, "oo_new"),
            "customer.subscription.updated",
            1_700_000_500,
            sub,
            status="past_due",
        ),
        SECRET_A,
    )
    assert newer.json()["outcome"] == "applied"
    older = post_webhook(
        billing_client,
        subscription_body(
            new_event_id(bag, "oo_old"),
            "customer.subscription.updated",
            1_700_000_100,
            sub,
            status="active",
        ),
        SECRET_A,
    )
    assert older.status_code == 200, older.text
    assert older.json()["outcome"] == "ignored_stale"
    assert sub_state(sub)["status"] == "past_due"

    old_delete = post_webhook(
        billing_client,
        subscription_body(
            new_event_id(bag, "oo_old_delete"),
            "customer.subscription.deleted",
            1_700_000_200,
            sub,
            status="canceled",
        ),
        SECRET_A,
    )
    assert old_delete.json()["outcome"] == "ignored_stale"
    assert sub_state(sub)["status"] == "past_due"

    deleted = post_webhook(
        billing_client,
        subscription_body(
            new_event_id(bag, "oo_delete"),
            "customer.subscription.deleted",
            1_700_000_800,
            sub,
            status="canceled",
        ),
        SECRET_A,
    )
    assert deleted.json()["outcome"] == "applied"
    assert sub_state(sub)["status"] == "canceled"
    assert sub_state(sub)["terminal"] == 1_700_000_800

    resurrect = post_webhook(
        billing_client,
        subscription_body(
            new_event_id(bag, "oo_resurrect"),
            "customer.subscription.updated",
            1_700_000_900,
            sub,
            status="active",
        ),
        SECRET_A,
    )
    assert resurrect.status_code == 200, resurrect.text
    assert resurrect.json()["outcome"] == "ignored_terminal"
    failed = post_webhook(
        billing_client,
        invoice_body(new_event_id(bag, "oo_invoice"), 1_700_001_000, sub),
        SECRET_A,
    )
    assert failed.json()["outcome"] == "ignored_terminal"
    assert sub_state(sub)["status"] == "canceled"
    assert sub_state(sub)["watermark"] == 1_700_000_800


def test_equal_created_delete_outranks_update(billing_client, stripe_settings, bag):
    sub = bag["sub"]
    created = 1_700_000_300
    assert (
        post_webhook(
            billing_client,
            subscription_body(
                new_event_id(bag, "tie_update"),
                "customer.subscription.updated",
                created,
                sub,
                status="active",
            ),
            SECRET_A,
        ).json()["outcome"]
        == "ignored_unknown"
    )
    # No row yet: seed with checkout at an earlier created, then a same-timestamp pair.
    assert (
        post_webhook(
            billing_client,
            checkout_body(new_event_id(bag, "tie_checkout"), created - 10, sub),
            SECRET_A,
        ).status_code
        == 200
    )
    assert (
        post_webhook(
            billing_client,
            subscription_body(
                new_event_id(bag, "tie_update2"),
                "customer.subscription.updated",
                created,
                sub,
                status="past_due",
            ),
            SECRET_A,
        ).json()["outcome"]
        == "applied"
    )
    deleted = post_webhook(
        billing_client,
        subscription_body(
            new_event_id(bag, "tie_delete"),
            "customer.subscription.deleted",
            created,
            sub,
            status="canceled",
        ),
        SECRET_A,
    )
    assert deleted.json()["outcome"] == "applied"
    assert sub_state(sub)["status"] == "canceled"


def test_livemode_mismatch_is_rejected(billing_client, stripe_settings, bag):
    event_id = new_event_id(bag, "liveflag")
    response = post_webhook(
        billing_client,
        checkout_body(event_id, 1_700_000_000, bag["sub"], livemode=True),
        SECRET_A,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "event livemode does not match configured Stripe mode"
    assert sub_state(bag["sub"]) is None
    assert event_rows(event_id) == []


def test_live_mode_accepts_only_live_events(billing_client, stripe_settings, bag, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("STRIPE_MODE", "live")
    monkeypatch.setenv("STRIPE_SECRET_KEY", LIVE_KEY)
    reload_settings()
    rejected = post_webhook(
        billing_client,
        checkout_body(new_event_id(bag, "live_reject"), 1_700_000_000, bag["sub"], livemode=False),
        SECRET_A,
    )
    assert rejected.status_code == 400
    assert "livemode" in rejected.json()["detail"]
    accepted_id = new_event_id(bag, "live_ok")
    accepted = post_webhook(
        billing_client,
        checkout_body(accepted_id, 1_700_000_000, bag["sub"], livemode=True),
        SECRET_A,
    )
    assert accepted.status_code == 200, accepted.text
    assert sub_state(bag["sub"])["status"] == "active"


def test_test_key_with_live_mode_is_rejected(billing_client, stripe_settings, bag, monkeypatch):
    from app.services.billing_provider import stripe_preflight_issues

    monkeypatch.setenv("STRIPE_MODE", "live")
    monkeypatch.setenv("STRIPE_SECRET_KEY", TEST_KEY)
    settings = reload_settings()
    codes = [issue.code for issue in stripe_preflight_issues(settings) if issue.fatal]
    assert "test_key_live_mode" in codes
    response = post_webhook(
        billing_client,
        checkout_body(new_event_id(bag, "mix"), 1_700_000_000, bag["sub"], livemode=True),
        SECRET_A,
    )
    assert response.status_code == 503
    assert "test key" in response.json()["detail"]
    assert sub_state(bag["sub"]) is None


def test_live_key_outside_production_is_rejected(billing_client, stripe_settings, bag, monkeypatch):
    from app.services.billing_provider import raise_for_stripe_preflight, stripe_preflight_issues

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("STRIPE_MODE", "live")
    monkeypatch.setenv("STRIPE_SECRET_KEY", LIVE_KEY)
    settings = reload_settings()
    codes = [issue.code for issue in stripe_preflight_issues(settings) if issue.fatal]
    assert "live_key_outside_production" in codes
    with pytest.raises(RuntimeError, match="outside production"):
        raise_for_stripe_preflight(settings)
    response = post_webhook(
        billing_client,
        checkout_body(new_event_id(bag, "livekey"), 1_700_000_000, bag["sub"], livemode=True),
        SECRET_A,
    )
    assert response.status_code == 503
    assert "outside production" in response.json()["detail"]
    assert sub_state(bag["sub"]) is None


def test_production_missing_webhook_secret_fails_closed(
    billing_client, stripe_settings, bag, monkeypatch
):
    from app.services.billing_provider import raise_for_stripe_preflight

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRETS", raising=False)
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", TEST_KEY)
    settings = reload_settings()
    with pytest.raises(RuntimeError, match="STRIPE_WEBHOOK_SECRET"):
        raise_for_stripe_preflight(settings)

    before = _event_table_count()
    response = post_webhook(
        billing_client,
        checkout_body(new_event_id(bag, "nosecret"), 1_700_000_000, bag["sub"]),
        SECRET_A,
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Stripe webhook secret is not configured"
    assert sub_state(bag["sub"]) is None
    assert _event_table_count() == before


def test_production_lifespan_reports_missing_webhook_secret(_ensure_test_data, monkeypatch):
    if not _ensure_test_data:
        pytest.fail("Postgres is required for TC-24-001; not skipping")
    import asyncio

    from app.main import app, lifespan

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", "p" * 40)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRETS", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.setenv("STRIPE_MODE", "test")
    reload_settings()

    async def enter():
        async with lifespan(app):
            raise AssertionError("production startup should have failed preflight")

    with pytest.raises(RuntimeError, match="STRIPE_WEBHOOK_SECRET"):
        asyncio.run(enter())


def test_development_without_stripe_does_not_fail_preflight():
    from app.services.billing_provider import raise_for_stripe_preflight

    raise_for_stripe_preflight(reload_settings())


def test_retention_floor_and_prune_keep_the_tolerance_window(stripe_settings, _ensure_test_data):
    if not _ensure_test_data:
        pytest.fail("Postgres is required for TC-24-001; not skipping")
    from app.core.database import SessionLocal
    from app.models import StripeWebhookEvent
    from app.services.billing_provider import prune_stripe_webhook_events, retention_floor_seconds

    assert retention_floor_seconds(1, 300) == 301
    assert retention_floor_seconds(604800, 300) == 604800
    now = datetime.now(timezone.utc)
    recent_id = f"evt_tc24001_prune_recent_{uuid.uuid4().hex[:8]}"
    old_id = f"evt_tc24001_prune_old_{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        db.add(_prune_row(recent_id, now - timedelta(seconds=30)))
        db.add(_prune_row(old_id, now - timedelta(seconds=5000)))
        db.commit()
        deleted = prune_stripe_webhook_events(
            db,
            now=now,
            retention_seconds=1,
            tolerance_seconds=300,
        )
        assert deleted >= 1
        remaining = {
            row.stripe_event_id
            for row in db.query(StripeWebhookEvent).filter(
                StripeWebhookEvent.stripe_event_id.in_([recent_id, old_id])
            )
        }
        assert remaining == {recent_id}
        db.query(StripeWebhookEvent).filter(StripeWebhookEvent.stripe_event_id == recent_id).delete(
            synchronize_session=False
        )
        db.commit()
    finally:
        db.rollback()
        db.close()


def test_prune_does_not_allow_a_stale_event_to_regress(billing_client, stripe_settings, bag):
    from app.core.database import SessionLocal
    from app.models import StripeWebhookEvent

    sub = bag["sub"]
    delete_id = new_event_id(bag, "prune_delete")
    assert (
        post_webhook(
            billing_client,
            checkout_body(new_event_id(bag, "prune_checkout"), 1_700_000_000, sub),
            SECRET_A,
        ).status_code
        == 200
    )
    assert (
        post_webhook(
            billing_client,
            subscription_body(
                delete_id,
                "customer.subscription.deleted",
                1_700_000_500,
                sub,
                status="canceled",
            ),
            SECRET_A,
        ).json()["outcome"]
        == "applied"
    )

    db = SessionLocal()
    try:
        row = (
            db.query(StripeWebhookEvent)
            .filter(StripeWebhookEvent.stripe_event_id == delete_id)
            .one()
        )
        row.processed_at = datetime.now(timezone.utc) - timedelta(days=10)
        db.commit()
    finally:
        db.close()

    update = post_webhook(
        billing_client,
        subscription_body(
            new_event_id(bag, "prune_update"),
            "customer.subscription.updated",
            1_700_000_900,
            sub,
            status="active",
        ),
        SECRET_A,
    )
    assert update.status_code == 200, update.text
    assert update.json()["outcome"] == "ignored_terminal"
    assert sub_state(sub)["status"] == "canceled"
    assert event_rows(delete_id) == []


def test_migration_fresh_install_upgrade_and_downgrade():
    url = "postgresql://postgres:postgres@127.0.0.1:5432/trustcopilot_tc24001_mig"
    _recreate_database("trustcopilot_tc24001_mig")
    try:
        fresh = _alembic(url, "upgrade", "head")
        assert fresh.returncode == 0, fresh.stderr
        _assert_webhook_schema(url, present=True)
        down = _alembic(url, "downgrade", "075")
        assert down.returncode == 0, down.stderr
        _assert_webhook_schema(url, present=False)
        again = _alembic(url, "upgrade", "head")
        assert again.returncode == 0, again.stderr
        _assert_webhook_schema(url, present=True)
        current = _alembic(url, "current")
        assert current.returncode == 0, current.stderr
        assert "076" in current.stdout
    finally:
        _drop_database("trustcopilot_tc24001_mig")


def _prune_row(event_id: str, processed_at: datetime):
    from app.models import StripeWebhookEvent

    return StripeWebhookEvent(
        stripe_event_id=event_id,
        event_type="customer.subscription.updated",
        livemode=False,
        stripe_created=1_700_000_000,
        stripe_object_id="sub_tc24001_prune",
        outcome="applied",
        processed_at=processed_at,
    )


def _event_table_count() -> int:
    from app.core.database import SessionLocal
    from app.models import StripeWebhookEvent

    db = SessionLocal()
    try:
        return db.query(StripeWebhookEvent).count()
    finally:
        db.close()


def _recreate_database(name: str) -> None:
    _drop_database(name)
    from sqlalchemy import create_engine, text

    engine = create_engine(
        "postgresql://postgres:postgres@127.0.0.1:5432/postgres",
        isolation_level="AUTOCOMMIT",
    )
    with engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine.dispose()


def _drop_database(name: str) -> None:
    from sqlalchemy import create_engine, text

    engine = create_engine(
        "postgresql://postgres:postgres@127.0.0.1:5432/postgres",
        isolation_level="AUTOCOMMIT",
    )
    with engine.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": name},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    engine.dispose()


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    env = {
        **__import__("os").environ,
        "DATABASE_URL": url,
        "TRUST_COPILOT_TESTING": "1",
        "APP_ENV": "development",
    }
    for key in STRIPE_ENV_KEYS:
        env.pop(key, None)
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(API_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _assert_webhook_schema(url: str, *, present: bool) -> None:
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    with engine.connect() as conn:
        table = conn.execute(text("SELECT to_regclass('public.stripe_webhook_events')")).scalar()
        constraint = conn.execute(
            text("SELECT 1 FROM pg_constraint WHERE conname = 'uq_stripe_webhook_events_event_id'")
        ).scalar()
        columns = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'subscriptions' AND column_name IN "
                    "('stripe_event_created', 'stripe_event_type', 'stripe_terminal_event_created')"
                )
            )
        }
    engine.dispose()
    expected_columns = {
        "stripe_event_created",
        "stripe_event_type",
        "stripe_terminal_event_created",
    }
    if present:
        assert table == "stripe_webhook_events"
        assert constraint == 1
        assert columns == expected_columns
    else:
        assert table is None
        assert constraint is None
        assert columns == set()
