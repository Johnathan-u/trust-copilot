# TC-08-011 acceptance evidence

Synthetic fixtures only. No customer documents, no provider calls, and no credentials.
This folder does not accept TC-08-011 and does not mark it DONE.

## Command

From `apps/api`:

```sh
TC_REQUIRE_DB=1 python -m pytest tests/release/test_tag_vocabulary.py -q
```

The backlog command is the same pytest invocation. `TC_REQUIRE_DB=1` makes a missing database a failure instead of a skip.

## Environment

Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55, Alembic 1.20.1, PostgreSQL 16.15, pgvector 0.6.0.
Database `trustcopilot_test` on localhost:5432, migrated to Alembic head `tc04007b_rate_buckets`.
Details: [environment.txt](environment.txt).

## Results

| Run | Product code | Exit | Totals |
|---|---|---|---|
| Failing-before | master `75437e34e570a16500cbea5e5c24f9f8578f47f3` | 1 | 9 failed, 2 passed |
| Passing-after | `6769a2c86f8c0d674fa9b6d70c65a03ef506707c` | 0 | 11 passed, 0 skipped |

Log: [failing-before.txt](failing-before.txt), [passing-after.txt](passing-after.txt).

The failing run used this change's test module and `docs/product/tag-vocabulary.json` against master `tag_service.py` and `app/api/routes/tags.py`. The packaged vocabulary module was absent. The two passing tests were the alias-disjoint check of the docs file and creation of an unknown custom key. The nine failures are the gaps: the runtime catalog is not loaded from the docs file, `SOC II` is stored as its own key, an unapproved suggestion replaces `frameworks_json`, add / approve / remove leave the mapping `approved`, relabel is missing, an editor receives 404 rather than 403, and a reviewer relabel returns 404.

The passing run is 11 passed and exit 0. There is no skip.

`tests/test_tags.py` was run in the same environment after the fix: 53 passed, exit 0. That file is the existing tag suite. It is not the backlog command.
