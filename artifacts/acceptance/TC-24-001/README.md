# TC-24-001: Configure buyer-owned Stripe sandbox and webhook trust

Real Stripe sandbox qualification is **BLOCKED** (owner decision OD-5). This run used throwaway secrets and hand-built fixtures. It did not call Stripe and did not use a network key.

| AC | Result |
|---|---|
| TC-24-001-AC1 Webhook signature, origin, and bounded replay | Met by `apps/api/tests/release/test_billing_provider.py`. Raw-body v1 signature, 300s past and future tolerance, a second rotated secret, unique event ids, concurrent duplicates, out-of-order subscription events, and retention pruning. |
| TC-24-001-AC2 No seller account; test and live cannot be mixed | Met by the same tests plus startup preflight. No default secret. Production with a missing webhook secret fails closed. Test key with live mode, live key outside production, and event `livemode` mismatch are rejected. |
| Real Stripe sandbox | BLOCKED. Pricing amounts are also pending (OD-8) and are not hardcoded. |

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python` (the repo venv is not created by this ticket).

```text
python -m pytest tests/release/test_billing_provider.py tests/test_credit_ledger.py tests/test_credit_prompts.py -q --tb=line
```

## SHA

Tests ran on the tree committed as `2cc4ca8d08a101242fdd679f718165cd2bd9ff86` (`TC-24-001: verify Stripe webhooks and separate test from live`). This evidence file was added after that commit and does not change the code under test.

## Environment

- Python 3.12.3
- PostgreSQL 16.15, database `trustcopilot_test` at `localhost:5432`, user `postgres`
- stripe 16.0.1 installed and not contacted (fixtures signed in-process)
- SQLAlchemy 2.1.6
- psycopg 3.3.6 (SQLAlchemy 2.1's default driver for `postgresql://`). `psycopg2-binary` 2.9.13 is the dependency declared in `apps/api/pyproject.toml`.
- No `STRIPE_SECRET_KEY` from the environment. Tests set `sk_test_tc24001_not_a_real_key`, `sk_live_tc24001_not_a_real_key`, `whsec_tc24001_primary`, and `whsec_tc24001_rotated`.

## Totals

| Command | Exit | Total |
|---|---|---|
| `pytest tests/release/test_billing_provider.py tests/test_credit_ledger.py tests/test_credit_prompts.py -q --tb=line` | 0 | 45 passed, 26 warnings, 6.37s |

The 45 are 24 in `tests/release/test_billing_provider.py` and 21 in `tests/test_credit_ledger.py` plus `tests/test_credit_prompts.py`.

Not run: `tests/test_alerts_api.py` and `tests/test_coverage_api.py`. Both issue live HTTP requests at import time. No other billing test module exists.
