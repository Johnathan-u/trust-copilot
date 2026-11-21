# TC-25-001 dashboard card revision

Not accepted. Not counted toward DONE. The behaviour note is `docs/release/tickets/TC-25-001.md`. The operator note is `docs/ops/dashboard-cards.md`. This folder does not edit the tracker.

The earlier files in this directory are the PARTIAL verification. This change adds the named-test logs. It does not add a CI run id.

## Command

From `apps/api`:

```sh
TC_REQUIRE_DB=1 python -m pytest tests/release/test_domain_dashboard_cards.py -q
```

`TC_TEST_DATABASE_URL` pointed at local database `trustcopilot_test` on `127.0.0.1:5432`, user `postgres`. The password is the local development default and is not copied here.

## Failing before

Product code was master `b0b8a01fd2a11914a884630d90ae68fd00291841`. The test file in this change was already present. Log: `failing-before.txt`.

4 failed, 3 passed, exit 1, no skip. A patch with no `updated_at` was stored (HTTP 200). A patch that still held the revision from before a reorder was stored. A repeated create with the same Idempotency-Key inserted a second row. A rejected create followed by a corrected create with the same key inserted two rows on the corrected body.

## Passing after

Same command on the product code in this change. Log: `passing-after.txt`.

7 passed, exit 0, no skip. A stale `updated_at` is 409 and the stored title stays. Reorder moves `updated_at`, so the old revision is 409. The same Idempotency-Key returns one card, and a new process reads that card from `GET /api/dashboard/cards`. A rejected create does not keep the key.

`python -m pytest tests/test_dashboard_cards.py -q` on the same product code: 26 passed, exit 0.

The web unit test `apps/web/tests/unit/dashboard-card-form.test.ts` is 4 passed. It checks that an edit body sends the loaded `updated_at`, a create reuses one Idempotency-Key, and a 409 is not a save.

## Environment

Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55, Alembic 1.20.1, PostgreSQL 16.15, pgvector 0.6.0. The web unit test used Node 24.22.3. Also recorded under the gap-closure section of `environment.txt`. Fixtures are synthetic. No customer content. No migration.
