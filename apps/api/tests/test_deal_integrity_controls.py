"""Synthetic transaction and amount controls; not PostgreSQL qualification."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.api.routes import deals
from app.core.idempotency import IdempotencyClaimLost
from app.services.deal_analytics_service import _sum_amounts

pytestmark = pytest.mark.unit


@pytest.fixture
def transaction_db():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE domain_changes (id INTEGER PRIMARY KEY)"))
        connection.execute(
            text("""
            CREATE TABLE idempotency_keys (
                idempotency_key TEXT PRIMARY KEY, status_code INTEGER,
                response_body TEXT, expires_at TIMESTAMP, owner_token TEXT
            )
        """)
        )
        connection.execute(
            text("""
            INSERT INTO idempotency_keys VALUES ('deal-key', 0, NULL, '2099-01-01', 'owner')
        """)
        )
    with Session(engine) as session:
        yield session
    engine.dispose()


def _work(db):
    db.execute(text("INSERT INTO domain_changes DEFAULT VALUES"))
    return {"id": db.execute(text("SELECT max(id) FROM domain_changes")).scalar()}


def test_response_failure_rolls_back_domain_and_same_key_retry_is_single(
    transaction_db, monkeypatch
):
    db = transaction_db
    real_set = deals.idempotency_set

    def fail_response(*args, **kwargs):
        raise RuntimeError("synthetic response failure")

    monkeypatch.setattr(deals, "idempotency_set", fail_response)
    with pytest.raises(RuntimeError, match="synthetic response failure"):
        deals._mutate(db, "deal-key", "owner", lambda: _work(db))
    assert db.execute(text("SELECT count(*) FROM domain_changes")).scalar() == 0
    # Reclaim after the failed/expired claim; retry must be the only domain effect.
    db.execute(text("DELETE FROM idempotency_keys WHERE idempotency_key='deal-key'"))
    db.execute(
        text("""
        INSERT INTO idempotency_keys VALUES ('deal-key', 0, NULL, '2099-01-01', 'retry-owner')
    """)
    )
    db.commit()
    monkeypatch.setattr(deals, "idempotency_set", real_set)
    payload = deals._mutate(db, "deal-key", "retry-owner", lambda: _work(db))
    assert db.execute(text("SELECT count(*) FROM domain_changes")).scalar() == 1
    assert deals.idempotency_get(db, "deal-key") == (200, payload)


def test_lost_owner_rolls_back_domain_and_preserves_new_owner(transaction_db):
    db = transaction_db
    with pytest.raises(IdempotencyClaimLost):
        deals._mutate(db, "deal-key", "stale-owner", lambda: _work(db))
    assert db.execute(text("SELECT count(*) FROM domain_changes")).scalar() == 0
    assert db.execute(text("SELECT owner_token FROM idempotency_keys")).scalar() == "owner"


def test_commit_failure_rolls_back_both_response_and_domain(transaction_db, monkeypatch):
    db = transaction_db
    real_commit = db.commit
    attempted = False

    def fail_first_commit():
        nonlocal attempted
        if not attempted:
            attempted = True
            # The response write and domain insert have both happened, but neither
            # may survive this failed transaction boundary.
            assert db.execute(text("SELECT response_body FROM idempotency_keys")).scalar()
            raise RuntimeError("synthetic commit failure")
        real_commit()

    monkeypatch.setattr(db, "commit", fail_first_commit)
    with pytest.raises(RuntimeError, match="synthetic commit failure"):
        deals._mutate(db, "deal-key", "owner", lambda: _work(db))
    assert db.execute(text("SELECT count(*) FROM domain_changes")).scalar() == 0
    assert deals.idempotency_get(db, "deal-key") is None


@pytest.mark.parametrize(
    "values,expected",
    [
        ([], {"amount": "0.00", "currency": None, "unavailable_reason": None}),
        ([(None, None)], {"amount": "0.00", "currency": None, "unavailable_reason": None}),
        (
            [("90071992547409.91", "USD"), ("0.01", "USD")],
            {"amount": "90071992547409.92", "currency": "USD", "unavailable_reason": None},
        ),
        (
            [("100.00", "USD"), ("100.00", "JPY")],
            {"amount": None, "currency": None, "unavailable_reason": "mixed_currency"},
        ),
        (
            [("100.00", None)],
            {"amount": None, "currency": None, "unavailable_reason": "unknown_currency"},
        ),
        (
            [("0.00", "USD"), ("0.00", None)],
            {"amount": None, "currency": None, "unavailable_reason": "unknown_currency"},
        ),
    ],
)
def test_amount_totals_require_one_known_currency(values, expected):
    rows = [
        SimpleNamespace(
            deal_value_arr=Decimal(amount) if amount is not None else None, currency=currency
        )
        for amount, currency in values
    ]
    assert _sum_amounts(rows) == expected
