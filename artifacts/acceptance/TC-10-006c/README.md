# TC-10-006c checksum backfill versions

Not accepted. Not counted toward DONE. The behaviour note is `docs/release/tickets/TC-10-006c.md`. The runbook is `docs/ops/storage-checksums.md`. This folder does not edit the tracker and does not record CI run ids.

## Command

From `apps/api`:

```sh
TC_REQUIRE_DB=1 python -m pytest tests/release/test_storage_checksums.py -q --tb=line -p no:cacheprovider
```

The tests use the suite database and an in-memory object store. They create a synthetic user, document, and export, then delete those rows. With `TC_REQUIRE_DB=1` a missing database fails the run instead of skipping. Nothing was skipped.

The three new tests are `test_backfill_skips_agreeing_versioned_rows`, `test_backfill_rerun_after_interrupted_stamp_keeps_versions`, and `test_moved_document_is_disagreed_and_download_stays_refused`.

`ruff check` and `ruff format --check` passed on the changed Python files. `pre-commit run --files` passed (ruff, ruff-format, trailing whitespace, end of file).

## Failing before

Product code was master `ccd333670e3306a8c4102ec0dc86d77aef39cde2`. The new tests ran against that code. Log: `failing-before.txt`.

Command from `apps/api`:

```sh
TC_REQUIRE_DB=1 python -m pytest tests/release/test_storage_checksums.py -k "agreeing_versioned or interrupted_stamp or moved_document" -q --tb=line -p no:cacheprovider
```

Exit 1. 2 failed, 1 passed, 0 skipped. Dry-run counted an agreeing version-2 document and a version-3 export as pending (`pending` 2 against a baseline of 0). `--execute` then reset those versions to 1 (`(1, 1, 1)` against `(1, 2, 3)`). The moved-document test passed on master: the old storage key stays, the download is 409, and the backfill count is `disagreed`.

## Passing after

The whole-file command on product code `93f500716ee7d5a6159ed85bb21a70422e596d83`. Log: `passing-after.txt`.

Exit 0. 9 passed, 0 failed, 0 skipped. Pytest also printed warnings from `datetime.utcnow` in existing models and from Alembic's `path_separator` default. An agreeing document at version 2 and an agreeing export at version 3 are counted `already`. `--execute` does not replace those objects or reset the versions. A mismatched hash and a key that names another workspace stay refused. An interrupted stamp (object written, row still null) is filled on the next `--execute` at version 1, and the agreeing versions stay 2 and 3. A second run does not rewrite them. A document moved with `reassign_parent_workspace` keeps its key, the download stays 409, and the backfill counts `disagreed`.

This evidence commit does not change that product code.

## Environment

`environment.txt`. Python 3.12.3, pytest 9.1.1, ruff 0.5.6, SQLAlchemy 2.0.55, Alembic 1.20.1, PostgreSQL 16.15, pgvector 0.6.0. Fixtures are synthetic. No customer document. No migration in this change.
