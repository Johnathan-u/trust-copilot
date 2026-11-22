# TC-10-006 storage checksums

Not accepted. Not counted toward DONE. The behaviour note is `docs/release/tickets/TC-10-006.md`. The runbook is `docs/ops/storage-checksums.md`. This folder does not edit the tracker and does not record CI run ids.

`pytest.txt` is the unchanged PARTIAL verification log. This folder adds the implementation evidence. It does not add `ci-runs.md`.

## Command

From `apps/api`:

```sh
python -m pytest tests/release/test_storage_checksums.py -q
```

The tests use the suite database and an in-memory object store. They create a synthetic user, document, and export, then delete those rows. With `TC_REQUIRE_DB=1` a missing database fails the run instead of skipping. This run used that setting. Nothing was skipped.

## Failing before

Product code was master `7e420af400b9defe359c9e668cb23fa41345ec78`. The new test ran against that code. Log: `failing-before.txt`.

Exit 1. 6 failed, 0 passed, 0 skipped. A document with no recorded hash returned 200 and the object bytes. The hash columns were not on `documents`. `app.services.storage_checksum` was not in the tree.

## Passing after

Same command on product code `2b9cc715f2be1530e936eef55c30dee93aa1e7ed`. Log: `passing-after.txt`.

6 passed, 0 failed, 0 skipped, exit 0. Pytest also printed 10 warnings from `datetime.utcnow` in existing models and from Alembic's `path_separator` default. A matching hash streams the document and the export with `nosniff`. A mismatch, a missing object, a null hash, and a key that names another workspace are refused. The body has no key and no hash. Another workspace's id is 404. An anonymous request is 401. Dry-run backfill writes nothing. Execute fills a null hash from the current object and leaves a disagreement, a missing object, and a job hash that does not match. Upgrade adds the nullable columns and downgrade drops them.

## Environment

`environment.txt`. Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55, Alembic 1.20.1, PostgreSQL 16.15, pgvector 0.6.0. Fixtures are synthetic. No customer document. Migration `tc10006_storage_checksums` is in this change.

## Legacy rows

A null hash is refused. `python -m app.services.storage_checksum` is a dry-run and prints counts only. `--execute` writes the hash of the current object when the key's workspace matches and the object exists. It does not write a hash for a cross-workspace key, a missing object, or an export whose job hash does not match the bytes. Downgrade drops the columns. The next upgrade leaves them null, and downloads stay refused until `--execute` runs again.
